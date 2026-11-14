# SPDX-License-Identifier: GPL-3.0-or-later
"""La plataforma: huella y rasante, y su aplicación sobre la superficie de partida (spec 015, T06 y
T07; RF-015-19, los rechazos de geometría de RF-015-08, RF-015-20, RF-015-21, RF-015-06 y RF-015-13;
plan 015 §5.1 y §5.4, A0, A1 y A2; CE-015-02 y CE-015-03). Dominio puro: sin proyecto y sin ``bpy``.

Lo que entrega:

- :class:`PlatformJob` (el homólogo de ``quarry.QuarryJob``): todo lo que el cálculo necesita **ya
  leído** y nada del proyecto —la petición, el código de la entidad, la rejilla, la superficie de
  partida, la geometría de origen (:class:`PlatformGeometry`: una línea con su ancho o un polígono con
  su eje enlazado o sin él), los parámetros resueltos (por último segmento de su clave, los de
  :class:`~.params.PlatformParam`) y las máscaras ``cut_allowed`` y ``fill_allowed`` como arrays— para
  probarlo sin proyecto y reproducirlo.
- :func:`platform_footprint` (A0 y A1): la :class:`Footprint` de la plataforma —su huella, la abscisa
  σ de cada celda, la rasante, el eje usado con su sentido, la longitud medida de la huella y los
  avisos— en su **ventana de trabajo** (:func:`work_window`: la huella ampliada por el alcance y dos
  celdas, recortada a la rejilla).
- :func:`axis_of_polygon` (A1): el eje principal de las celdas de un polígono.
- :func:`apply_platform` y :func:`apply_platform_steps` (A2): la superficie que deja la plataforma
  sobre la de partida (:class:`Applied`), con lo que no se mueve y por qué (:class:`OffLevel`).

**Con eje y ancho** la huella es la del corredor de extremos planos de RF-014-09
(:func:`~.quarry.axis_abscissa`, que mide lo que su eje ± 1 celda: error 20) y la abscisa σ, la del
punto más próximo de todo el eje (a igual distancia de dos tramos, la menor; la abscisa 0 está en el
primer vértice). **Con polígono**, las celdas son las de su centro (D-16 de la 013) y el eje, la parte
dentro del polígono de la línea enlazada —que lo cruza de lado a lado— o, sin enlace, el eje principal
de las celdas (con el aviso ``des.platform_axis_principal``); σ es la del punto más próximo del eje,
fijada en sus extremos. En los dos casos la sección es horizontal: la rasante de una celda es ``cota
inicial + σ · pendiente / 100``.

Rechaza (``DesignError``, nombrando la capa, la entidad, el campo y el valor, y sin elegir ninguno por
la persona; RF-015-08), en este orden: una capa de puntos (``des.platform_layer_kind``); un ancho, una
cota inicial, una pendiente o un alcance que falta o sale de rango (``des.entity_param_*``); una línea
de varias partes, sin longitud, cerrada o que se corta a sí misma (``des.platform_axis_parts``,
``_axis_length_zero``, ``_axis_closed`` y ``_self_intersects``); un polígono sin área, que se corta o
sin celdas (``des.platform_area_zero``, ``_self_intersects`` y ``_no_cells``); un eje enlazado que no
cruza su polígono de lado a lado (``des.platform_axis_not_crossing``); una cota inicial o final de la
rasante fuera de las del terreno ± 1.000 m (``des.platform_level_range``); y una línea fuera de la
rejilla (``des.platform_no_cells``).

**Aplicar** (A2): en el modo «en corte» (el de por defecto, D-5) la superficie es ``z' = mín(z,
rasante)`` en las celdas de la huella donde el corte se admite (``cut_allowed``) y **ninguna celda
sube**: la plataforma es el fondo de su corredor, no una cota mínima (B7). En «en corte y relleno»,
además ``z' = rasante`` donde ``z < rasante`` y el relleno se admite (``fill_allowed``). Las celdas de
la huella que las máscaras no dejan mover quedan como en la partida; las que no quedan en la rasante
(a 10⁻⁹ m) se agrupan (4-conexas) con su área, su diferencia máxima, su lugar absoluto y su causa
(:class:`OffLevelCause`: ``cut_allowed`` falso, ``fill_allowed`` falso o, por debajo en «en corte», el
modo), y las máscaras de lo que se impide quedan en :class:`Applied` para que la zona se mire contra
las restricciones de otras entidades (el resumen es de la T12). Las celdas que quedan en la rasante
(:attr:`Applied.at_level`) son las semillas del borde (T08). Sin dato en la huella lo rechaza la
preparación (RF-015-09, T11): aquí es un error del programa, no se oculta con un valor.

Las coordenadas absolutas son float64 y se pasan a locales respecto a la esquina de la rejilla solo
dentro del cálculo (principio 6, ADR-0005). Ninguna entrada se modifica. El borde, la contrapendiente
y las cifras son de las tareas siguientes (T08 y T09).
"""

from __future__ import annotations

import math
from collections.abc import Generator, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

import numpy as np

from ..core.project.model import Progress
from ..gis.grid import Grid
from ..gis.masks.compile import STEP_BUDGET_S
from .grids import _label_units
from .messages import DesignError
from .model import Axis, PlatformMode, PlatformRequest
from .params import PLATFORM_PARAMS, PlatformParam, check_entity_param, entity_segment
from .preview import Notice
from .quarry import (
    FLOOR_LEVEL_MARGIN_M,
    _segment_frame,
    axis_abscissa,
    axis_paths,
    corridor_window,
)
from .seeds import pace_progress
from .zones import _paint, _polygon_spans

__all__ = [
    "Applied",
    "Footprint",
    "OffLevel",
    "OffLevelCause",
    "PlatformGeometry",
    "PlatformJob",
    "apply_platform",
    "apply_platform_steps",
    "axis_of_polygon",
    "platform_footprint",
    "work_window",
]

_GEOMETRY = "geometría"
_KINDS_ES = MappingProxyType({"point": "puntos", "line": "líneas", "polygon": "polígonos"})
_LINK_FIELD = "eje"
_TOL_M = 1e-9
"""Lo que separa dos puntos distintos (m): la resolución de un float64 a 4,4 Mm de norte."""
_REL = 1e-12
"""La tolerancia relativa de un paralelismo y de un parámetro dentro de un tramo."""

_Parts = tuple[tuple[np.ndarray, ...], ...]


# --- Lo leído ----------------------------------------------------------------------------------


def _xy(points: object) -> np.ndarray:
    """``points`` como array float64 ``(k, 2)`` de vértices finitos (la Z, si la trae, no cuenta);
    ``ValueError`` si no son puntos o no son finitos."""
    array = np.asarray(points, dtype=np.float64)
    if array.ndim == 2 and array.shape[1] in (2, 3):
        array = array[:, :2]
    elif array.size % 2 == 0:
        array = array.reshape(-1, 2)
    else:
        raise ValueError(f"unos vértices son un array (k, 2), no de forma {array.shape}")
    if not np.all(np.isfinite(array)):
        raise ValueError("una geometría tiene coordenadas no finitas")
    return array


def _parts(parts: object) -> _Parts:
    """Las partes de una geometría (por parte, sus caminos o sus anillos) con cada uno como array
    float64 ``(k, 2)``, sin copiar los que ya lo son."""
    return tuple(tuple(_xy(path) for path in part) for part in parts)  # type: ignore[attr-defined]


@dataclass(frozen=True, slots=True, eq=False)
class PlatformGeometry:
    """La geometría de origen de una plataforma, ya leída de su capa: su ``kind`` (``point``,
    ``line`` o ``polygon``, el de la capa; un punto se rechaza al calcular) y sus ``parts`` (por
    parte, su camino o sus anillos —el primero, el exterior—, X e Y ABSOLUTAS en float64, como las da
    ``gis.vector.FeatureLayer``). Un polígono lleva, si tiene eje enlazado, las partes de esa línea
    (``axis_parts``) y su nombre (``axis_name``, para decirlo en un rechazo); sin ellas, el eje es el
    principal de sus celdas. Una línea no lleva eje enlazado (``ValueError``, como un tipo que no es
    de una capa de entidades: errores del programa)."""

    kind: str
    parts: _Parts
    axis_parts: _Parts | None = None
    axis_name: str = ""

    def __post_init__(self) -> None:
        if self.kind not in _KINDS_ES:
            raise ValueError(f"la geometría de una plataforma es de puntos, líneas o polígonos, "
                             f"no «{self.kind}»")
        if self.axis_parts is not None and self.kind != "polygon":
            raise ValueError("solo un polígono lleva un eje enlazado (RF-015-19)")
        object.__setattr__(self, "parts", _parts(self.parts))
        if self.axis_parts is not None:
            object.__setattr__(self, "axis_parts", _parts(self.axis_parts))


def _grid_array(values: object, grid: Grid, dtype: type, what: str) -> np.ndarray:
    """``values`` como array de la forma de ``grid`` (``ValueError`` si no lo es)."""
    array = np.asarray(values, dtype=dtype)
    if array.shape != grid.shape:
        raise ValueError(f"{what} es de la forma de la rejilla {grid.shape}, no {array.shape}")
    return array


@dataclass(frozen=True, slots=True, eq=False)
class PlatformJob:
    """Lo que necesita calcular una plataforma, ya leído y sin proyecto (plan 015 §5.3.1; lo que
    ``quarry.QuarryJob`` a la 014): la ``request`` (su nombre y la capa con sus campos), el ``code``
    de la entidad (``PLT-001``, para nombrar la clave de un parámetro en un rechazo), la rejilla
    (``grid``), la superficie de partida ``start`` (m, float64 de la forma de la rejilla; ``NaN``,
    sin dato), la ``geometry`` de origen, los parámetros resueltos (``values``: por último segmento
    de su clave, los de :class:`~.params.PlatformParam`: ``width_m`` —solo con una línea—,
    ``start_level_m``, ``gradient_pct``, ``reach_m``…) y las máscaras de la versión como arrays
    booleanos de la forma de la rejilla (``cut_allowed`` y ``fill_allowed``: las usan la
    aplicación y el borde, T07 y T08). ``ValueError`` (errores del programa) si el código no es el
    de una entidad, una clave no es de una plataforma o un array no es de la forma de la rejilla."""

    request: PlatformRequest
    code: str
    grid: Grid
    start: np.ndarray
    geometry: PlatformGeometry
    values: Mapping[str, object]
    cut_allowed: np.ndarray
    fill_allowed: np.ndarray

    def __post_init__(self) -> None:
        entity_segment(self.code)
        object.__setattr__(self, "start",
                           _grid_array(self.start, self.grid, np.float64,
                                       "la superficie de partida"))
        for name in ("cut_allowed", "fill_allowed"):
            object.__setattr__(self, name, _grid_array(getattr(self, name), self.grid, np.bool_,
                                                       f"la máscara «{name}»"))
        known = {param.value for param in PlatformParam}
        unknown = sorted(set(self.values) - known)
        if unknown:
            raise ValueError(f"los valores de una plataforma son de {', '.join(sorted(known))}, "
                             f"no «{unknown[0]}»")
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))


@dataclass(frozen=True, slots=True, eq=False)
class Footprint:
    """La huella y la rasante de una plataforma (A0 y A1), en su ventana de trabajo (``window``:
    filas y columnas de la rejilla, :func:`work_window`; todas las rejillas de abajo son de su
    forma): ``cells`` (la huella; booleana), ``sigma`` (la abscisa σ, m, a lo largo del eje desde su
    primer vértice, de la celda: la de su punto más próximo; ``NaN`` fuera de la huella) y ``levels``
    (la rasante, m: ``cota inicial + σ · pendiente / 100``; ``NaN`` fuera). ``axis`` es el eje usado
    (:class:`~.model.Axis`, con su sentido, su longitud y si es el principal), ``length_m`` la
    longitud medida de la huella (m; el máximo menos el mínimo de la abscisa sin recortar de sus
    celdas: error 20, no los 220 m de un *buffer*), ``start_level_m`` y ``gradient_pct`` los de la
    rasante, ``cell_area_m2`` el área de una celda y ``notices`` los avisos (el eje principal)."""

    window: tuple[slice, slice]
    cells: np.ndarray
    sigma: np.ndarray
    levels: np.ndarray
    axis: Axis
    length_m: float
    start_level_m: float
    gradient_pct: float
    cell_area_m2: float
    notices: tuple[Notice, ...] = ()

    @property
    def cell_count(self) -> int:
        """Las celdas de la huella."""
        return int(np.count_nonzero(self.cells))

    @property
    def area_m2(self) -> float:
        """El área de la huella (m²): sus celdas por el área de una."""
        return self.cell_count * self.cell_area_m2

    @property
    def end_level_m(self) -> float:
        """La cota de la rasante en el último vértice del eje (m)."""
        return self.start_level_m + self.axis.length_m * self.gradient_pct / 100.0


def work_window(rows: slice, cols: slice, reach_m: float, grid: Grid) -> tuple[slice, slice]:
    """**A0** (plan 015 §5.4): la ventana de trabajo de una entidad, la caja de su huella (``rows``
    y ``cols``: filas y columnas de ``grid``) ampliada por el alcance ``reach_m`` (m) y dos celdas,
    recortada a la rejilla: ``⌈alcance / paso⌉ + 2`` celdas por cada lado (el paso de cada eje). Así
    veinte plataformas de una hectárea no cuestan veinte envolventes de la rejilla entera.
    ``ValueError`` si el alcance no es un número mayor o igual que 0."""
    if not reach_m >= 0.0:
        raise ValueError(f"el alcance es un número mayor o igual que 0, no {reach_m!r}")
    across_rows = math.ceil(reach_m / grid.dy) + 2
    across_cols = math.ceil(reach_m / grid.dx) + 2
    return (slice(max(rows.start - across_rows, 0), min(rows.stop + across_rows, grid.nrows)),
            slice(max(cols.start - across_cols, 0), min(cols.stop + across_cols, grid.ncols)))


# --- Rechazos ----------------------------------------------------------------------------------


def _reject(code: str, request: PlatformRequest, field: str, value: object,
            **values: object) -> DesignError:
    """El rechazo ``code`` de la plataforma de ``request``: nombra la capa, la entidad, el campo y
    el valor."""
    return DesignError(code, obj=f"Plataforma «{request.name}» de la capa «{request.layer}»",
                       field=field, value=value, layer=request.layer, entity=request.name, **values)


def _resolved(job: PlatformJob, *, line: bool) -> tuple[float, float, float, float | None]:
    """Los valores que calcula la huella, ya comprobados (``des.entity_param_missing`` o
    ``des.entity_param_range`` con la clave de su campo): ``(cota inicial, pendiente, alcance,
    ancho)``, y el ancho solo con una línea (un polígono no lo tiene: ``None``)."""
    name, code, found = job.request.name, job.code, job.values

    def one(param: PlatformParam) -> float:
        value = check_entity_param(name, code, param, found.get(param.value))
        assert isinstance(value, float)
        return value

    width = one(PlatformParam.WIDTH) if line else None
    return (one(PlatformParam.START_LEVEL), one(PlatformParam.GRADIENT), one(PlatformParam.REACH),
            width)


def _check_levels(job: PlatformJob, axis_m: float, start_level: float, gradient: float) -> None:
    """**RF-015-08**: la cota inicial de la rasante y la del final del eje (de ``axis_m`` m) dentro
    de ``[mín(z) − 1.000, máx(z) + 1.000]`` m con las celdas con dato de la superficie de partida;
    si no, ``des.platform_level_range`` con la capa, la entidad, el campo (el de la cota inicial o,
    para la final, «<cota inicial> + <pendiente>»), el valor y el rango. ``ValueError`` si la
    superficie de partida no tiene ninguna celda con dato (lo rechaza antes la preparación)."""
    finite = np.isfinite(job.start)
    if not finite.any():
        raise ValueError("la superficie de partida no tiene ninguna celda con dato")
    low = float(np.min(job.start, where=finite, initial=np.inf)) - FLOOR_LEVEL_MARGIN_M
    high = float(np.max(job.start, where=finite, initial=-np.inf)) + FLOOR_LEVEL_MARGIN_M
    fields = job.request.fields
    end_level = start_level + axis_m * gradient / 100.0
    for field, level in ((fields.start_level_field, start_level),
                         (f"{fields.start_level_field} + {fields.gradient_field}", end_level)):
        if not low <= level <= high:
            raise _reject("des.platform_level_range", job.request, field, level, low=low,
                          high=high)


# --- Geometría: cruces y puntos ----------------------------------------------------------------


def _hits(p: np.ndarray, r: np.ndarray, a: np.ndarray, s: np.ndarray
          ) -> tuple[np.ndarray, np.ndarray]:
    """El tramo ``p + t·r`` (``t`` en [0, 1]) frente a los tramos ``a + u·s`` (``a`` y ``s``,
    ``(n, 2)``): para cada uno, si se tocan (un cruce, un contacto o un solape sobre la misma
    recta) y el ``t`` del primer punto común. En locales (float64)."""
    ap = a - p
    denom = r[0] * s[:, 1] - r[1] * s[:, 0]
    cross_s = ap[:, 0] * s[:, 1] - ap[:, 1] * s[:, 0]
    cross_r = ap[:, 0] * r[1] - ap[:, 1] * r[0]
    length_r = math.hypot(r[0], r[1])
    length_s = np.hypot(s[:, 0], s[:, 1])
    parallel = np.abs(denom) <= _REL * length_r * length_s
    safe = np.where(parallel, 1.0, denom)
    t = cross_s / safe
    u = cross_r / safe
    crossing = (~parallel & (t >= -_REL) & (t <= 1.0 + _REL) & (u >= -_REL) & (u <= 1.0 + _REL))
    on_line = parallel & (np.abs(cross_r) <= _TOL_M * length_r)
    along_a = (ap @ r) / (length_r * length_r)
    along_b = along_a + (s @ r) / (length_r * length_r)
    first = np.maximum(np.minimum(along_a, along_b), 0.0)
    last = np.minimum(np.maximum(along_a, along_b), 1.0)
    overlap = on_line & (first <= last + _REL)
    return crossing | overlap, np.where(overlap, first, t)


def _first_crossing(rings: Sequence[np.ndarray], *, closed: bool) -> tuple[float, float] | None:
    """El primer punto (locales) en que una polilínea, o los anillos de un polígono, se tocan a sí
    mismos: un cruce, un contacto o un solape de dos tramos que no son vecinos, o un tramo que
    vuelve sobre el anterior por la misma recta; ``None`` si no. ``rings``: cada camino (``closed``
    falso) o anillo (``closed`` verdadero, **sin** repetir el primer vértice al final) en
    locales, sin vértices repetidos seguidos. Un anillo con otro (un hueco con su exterior) cuenta."""
    first_edges, last_edges, identity, position, size = [], [], [], [], []
    for index, ring in enumerate(rings):
        if ring.shape[0] < 2:
            continue
        begin = ring if closed else ring[:-1]
        end = np.roll(ring, -1, axis=0) if closed else ring[1:]
        count = begin.shape[0]
        first_edges.append(begin)
        last_edges.append(end)
        identity.append(np.full(count, index))
        position.append(np.arange(count))
        size.append(np.full(count, count))
    if not first_edges:
        return None
    a, b = np.concatenate(first_edges), np.concatenate(last_edges)
    ids, pos, count = np.concatenate(identity), np.concatenate(position), np.concatenate(size)
    r = b - a
    for i in range(a.shape[0] - 1):
        j = np.arange(i + 1, a.shape[0])
        gap = pos[j] - pos[i]
        neighbours = (ids[j] == ids[i]) & ((gap == 1) | ((gap == count[i] - 1) & closed))
        j = j[~neighbours]
        if j.size == 0:
            continue
        hit, t = _hits(a[i], r[i], a[j], r[j])
        if hit.any():
            point = a[i] + t[int(np.flatnonzero(hit)[0])] * r[i]
            return float(point[0]), float(point[1])
    for index in range(len(rings)):
        own = ids == index
        if not own.any():
            continue
        steps, ends = r[own], b[own]
        now, then = (steps, np.roll(steps, -1, axis=0)) if closed else (steps[:-1], steps[1:])
        cross = now[:, 0] * then[:, 1] - now[:, 1] * then[:, 0]
        scale = np.hypot(now[:, 0], now[:, 1]) * np.hypot(then[:, 0], then[:, 1])
        back = (np.abs(cross) <= _REL * scale) & ((now * then).sum(axis=1) < 0.0)
        if back.any():
            vertex = ends[int(np.flatnonzero(back)[0])]
            return float(vertex[0]), float(vertex[1])
    return None


def _inside(points: np.ndarray, parts: Sequence[Sequence[np.ndarray]]) -> np.ndarray:
    """Si cada punto de ``points`` (``(m, 2)``, locales) está dentro de alguna de las partes de un
    polígono (``parts``: por parte, sus anillos cerrados sin repetir el primer vértice; el
    par-impar de sus anillos, un hueco incluido)."""
    found = np.zeros(points.shape[0], dtype=bool)
    px, py = points[:, 0][:, None], points[:, 1][:, None]
    for rings in parts:
        parity = np.zeros(points.shape[0], dtype=bool)
        for ring in rings:
            a, b = ring, np.roll(ring, -1, axis=0)
            straddles = (a[:, 1][None, :] > py) != (b[:, 1][None, :] > py)
            rise = np.where(b[:, 1] == a[:, 1], 1.0, b[:, 1] - a[:, 1])
            at = a[:, 0] + (py - a[:, 1]) * (b[:, 0] - a[:, 0]) / rise
            parity ^= ((straddles & (px < at)).sum(axis=1) % 2) == 1
        found |= parity
    return found


def _on_boundary(point: np.ndarray, begin: np.ndarray, end: np.ndarray) -> bool:
    """Si ``point`` (local) está a ≤ :data:`_TOL_M` de algún tramo ``begin → end``."""
    step = end - begin
    length2 = (step * step).sum(axis=1)
    along = np.where(length2 > 0.0, ((point - begin) * step).sum(axis=1)
                     / np.where(length2 > 0.0, length2, 1.0), 0.0)
    near = begin + np.clip(along, 0.0, 1.0)[:, None] * step
    return bool((np.hypot(near[:, 0] - point[0], near[:, 1] - point[1]) <= _TOL_M).any())


def _dedupe(points: np.ndarray) -> np.ndarray:
    """``points`` sin los vértices que repiten al anterior (a ≤ :data:`_TOL_M`)."""
    if points.shape[0] < 2:
        return points
    step = np.hypot(*np.diff(points, axis=0).T)
    return points[np.concatenate(([True], step > _TOL_M))]


def _ring(points: np.ndarray) -> np.ndarray:
    """Un anillo (locales) sin vértices repetidos y sin el que repite el primero al final."""
    ring = _dedupe(points)
    if ring.shape[0] > 1 and math.hypot(*(ring[-1] - ring[0])) <= _TOL_M:
        ring = ring[:-1]
    return ring


def _degenerate(ring: np.ndarray) -> bool:
    """Si todos los vértices de ``ring`` están alineados (a ≤ :data:`_TOL_M` de la recta del primero
    al más lejano): no tiene área."""
    if ring.shape[0] < 3:
        return True
    offset = ring - ring[0]
    far = offset[int(np.argmax(np.hypot(offset[:, 0], offset[:, 1])))]
    norm = math.hypot(far[0], far[1])
    if norm <= _TOL_M:
        return True
    return bool((np.abs(offset[:, 0] * far[1] - offset[:, 1] * far[0]) / norm).max() <= _TOL_M)


def _shoelace(ring: np.ndarray) -> float:
    """El área (m²) de un anillo en locales, sin signo."""
    nxt = np.roll(ring, -1, axis=0)
    return abs(0.5 * float((ring[:, 0] * nxt[:, 1] - nxt[:, 0] * ring[:, 1]).sum()))


def _origin(grid: Grid) -> np.ndarray:
    """La esquina noroeste de la rejilla: el origen de las coordenadas locales de un cálculo."""
    return np.array([grid.west, grid.north], dtype=np.float64)


# --- A1: el eje de una línea -------------------------------------------------------------------


def _line_path(job: PlatformJob) -> np.ndarray:
    """El camino (absoluto, ``(k, 2)``) de la línea de la plataforma, comprobado (RF-015-08): una
    sola parte (``des.platform_axis_parts``), con longitud (``des.platform_axis_length_zero``), abierta
    (``des.platform_axis_closed``) y que no se corta a sí misma (``des.platform_self_intersects``,
    con el punto, absoluto)."""
    request = job.request
    paths = [path for path in axis_paths(job.geometry.parts) if path.shape[0] > 0]
    if len(paths) > 1:
        raise _reject("des.platform_axis_parts", request, _GEOMETRY, len(paths))
    path = paths[0] if paths else np.empty((0, 2))
    length = (math.fsum(np.hypot(*np.diff(path, axis=0).T).tolist())
              if path.shape[0] > 1 else 0.0)
    if not length > 0.0:
        raise _reject("des.platform_axis_length_zero", request, _GEOMETRY, 0.0)
    if path.shape[0] >= 3 and math.hypot(*(path[-1] - path[0])) <= _TOL_M:
        raise _reject("des.platform_axis_closed", request, _GEOMETRY, length)
    origin = _origin(job.grid)
    hit = _first_crossing([_dedupe(path - origin)], closed=False)
    if hit is not None:
        x, y = hit[0] + float(origin[0]), hit[1] + float(origin[1])
        raise _reject("des.platform_self_intersects", request, _GEOMETRY, f"{x:.3f}, {y:.3f}",
                      x=x, y=y)
    return path


def _trim(cells: np.ndarray, rows: slice, cols: slice) -> tuple[slice, slice, np.ndarray] | None:
    """La caja de las celdas ``True`` de ``cells`` (la ventana ``rows`` × ``cols`` de la rejilla):
    ``(filas, columnas, celdas dentro de la caja)``; ``None`` si no hay ninguna."""
    found_rows = np.flatnonzero(cells.any(axis=1))
    if found_rows.size == 0:
        return None
    found_cols = np.flatnonzero(cells.any(axis=0))
    r0, r1 = int(found_rows[0]), int(found_rows[-1]) + 1
    c0, c1 = int(found_cols[0]), int(found_cols[-1]) + 1
    return (slice(rows.start + r0, rows.start + r1), slice(cols.start + c0, cols.start + c1),
            cells[r0:r1, c0:c1])


# --- A1: el eje de un polígono -----------------------------------------------------------------


def axis_of_polygon(cells: np.ndarray, grid: Grid, *, offset: tuple[int, int] = (0, 0)) -> Axis:
    """**A1** (RF-015-19): el **eje principal** de las celdas ``cells`` (booleana: toda la rejilla
    ``grid`` o una ventana suya cuya primera celda es la ``offset`` = (fila, columna)): la dirección
    propia mayor de la matriz de covarianza de los centros de celda (con la misma varianza en las dos
    direcciones, la este-oeste), por el centro de las celdas y de extremo a extremo de la huella (de
    los centros extremos, ampliados media celda en cada extremo). Su sentido, el de la abscisa 0: el
    extremo más al oeste y, a igual abscisa x (a ≤ :data:`_TOL_M`), el del sur. Devuelve un
    :class:`~.model.Axis` ``principal`` de coordenadas absolutas float64 (los cálculos van en locales
    desde la esquina de la rejilla). ``ValueError`` si no hay ninguna celda (lo rechaza antes
    :func:`platform_footprint`). Ninguna entrada se modifica."""
    rows, cols = np.nonzero(cells)
    if rows.size == 0:
        raise ValueError("el eje principal de un polígono pide al menos una celda")
    x = (cols + offset[1] + 0.5) * grid.dx
    y = -(rows + offset[0] + 0.5) * grid.dy  # locales desde la esquina noroeste, Y hacia el norte
    ex, ey = x - x.mean(), y - y.mean()
    var_x, var_y, covariance = float((ex * ex).mean()), float((ey * ey).mean()), float(
        (ex * ey).mean())
    if covariance == 0.0:
        ux, uy = (1.0, 0.0) if var_x >= var_y else (0.0, 1.0)
    else:
        angle = 0.5 * math.atan2(2.0 * covariance, var_x - var_y)
        ux, uy = math.cos(angle), math.sin(angle)
    along = ex * ux + ey * uy
    half_cell = 0.5 * (abs(ux) * grid.dx + abs(uy) * grid.dy)
    ends = [(float(x.mean()) + (t * ux), float(y.mean()) + (t * uy))
            for t in (float(along.min()) - half_cell, float(along.max()) + half_cell)]
    (xa, ya), (xb, yb) = ends
    if xb - xa < -_TOL_M or (abs(xb - xa) <= _TOL_M and yb < ya):
        (xa, ya), (xb, yb) = (xb, yb), (xa, ya)
    return Axis(((grid.west + xa, grid.north + ya), (grid.west + xb, grid.north + yb)),
                principal=True)


def _polygon_rings(job: PlatformJob) -> list[list[np.ndarray]]:
    """Los anillos (locales, cerrados sin repetir el primer vértice) de cada parte con área del
    polígono, comprobados (RF-015-08): sin área (``des.platform_area_zero``: todas las partes
    degeneradas o un área neta de 0) o que se corta a sí misma o a un hueco
    (``des.platform_self_intersects``, con el punto, absoluto)."""
    request, origin = job.request, _origin(job.grid)
    live: list[list[np.ndarray]] = []
    for part in job.geometry.parts:
        rings = [_ring(points - origin) for points in part]
        if not rings or _degenerate(rings[0]):
            continue
        live.append([rings[0], *(ring for ring in rings[1:] if not _degenerate(ring))])
    if not live:
        raise _reject("des.platform_area_zero", request, _GEOMETRY, 0.0)
    for rings in live:
        hit = _first_crossing(rings, closed=True)
        if hit is not None:
            x, y = hit[0] + float(origin[0]), hit[1] + float(origin[1])
            raise _reject("des.platform_self_intersects", request, _GEOMETRY,
                          f"{x:.3f}, {y:.3f}", x=x, y=y)
    area = math.fsum(_shoelace(rings[0]) - math.fsum(_shoelace(hole) for hole in rings[1:])
                     for rings in live)
    if not area > 0.0:
        raise _reject("des.platform_area_zero", request, _GEOMETRY, area)
    return live


def _linked_axis(job: PlatformJob, parts: list[list[np.ndarray]]) -> Axis:
    """El eje de un polígono con su línea enlazada: **la parte de la línea que está dentro del
    polígono** (de su entrada a su salida, con los vértices de la línea que haya dentro), que ha de
    cruzarlo de lado a lado: una sola parte dentro, con sus dos extremos en el contorno y con
    longitud. Si no (la línea empieza o acaba dentro, no lo toca, lo cruza varias veces o roza el
    contorno), ``des.platform_axis_not_crossing`` con el campo del enlace y el nombre del eje; una línea de
    varias partes, ``des.platform_axis_parts``. ``parts``: los anillos de :func:`_polygon_rings`."""
    request, geometry, grid = job.request, job.geometry, job.grid
    assert geometry.axis_parts is not None
    paths = [path for path in axis_paths(geometry.axis_parts) if path.shape[0] > 0]
    if len(paths) > 1:
        raise _reject("des.platform_axis_parts", request, _GEOMETRY, len(paths))

    def not_crossing() -> DesignError:
        return _reject("des.platform_axis_not_crossing", request,
                       request.fields.axis_field or _LINK_FIELD, geometry.axis_name)

    if not paths or paths[0].shape[0] < 2:
        raise not_crossing()
    path, origin = paths[0], _origin(grid)
    line = path - origin
    begin = np.concatenate([ring for rings in parts for ring in rings])
    end = np.concatenate([np.roll(ring, -1, axis=0) for rings in parts for ring in rings])
    pieces: list[tuple[int, float, float]] = []
    for k in range(line.shape[0] - 1):
        step = line[k + 1] - line[k]
        length = math.hypot(step[0], step[1])
        if not length > 0.0:
            continue
        hit, t = _hits(line[k], step, begin, end - begin)
        cuts = np.unique(np.concatenate(([0.0, 1.0], np.clip(t[hit], 0.0, 1.0))))
        pieces.extend((k, float(t0), float(t1)) for t0, t1 in zip(cuts[:-1], cuts[1:], strict=True)
                      if (t1 - t0) * length > _TOL_M)
    if not pieces:
        raise not_crossing()
    k_of = np.array([piece[0] for piece in pieces])
    mid_t = np.array([0.5 * (piece[1] + piece[2]) for piece in pieces])
    middles = line[k_of] + mid_t[:, None] * (line[k_of + 1] - line[k_of])
    runs: list[list[int]] = []
    current: list[int] | None = None
    for index, inside in enumerate(_inside(middles, parts)):
        if not inside:
            current = None
            continue
        if current is None:
            current = []
            runs.append(current)
        current.append(index)
    if len(runs) != 1:
        raise not_crossing()
    first, last = pieces[runs[0][0]], pieces[runs[0][-1]]
    starts_in = first[0] == 0 and first[1] == 0.0 and not _on_boundary(line[0], begin, end)
    ends_in = (last[0] == line.shape[0] - 2 and last[2] == 1.0
               and not _on_boundary(line[-1], begin, end))
    if starts_in or ends_in:
        raise not_crossing()

    def point(k: int, t: float) -> tuple[float, float]:
        if t == 0.0:
            return float(path[k][0]), float(path[k][1])
        if t == 1.0:
            return float(path[k + 1][0]), float(path[k + 1][1])
        found = line[k] + t * (line[k + 1] - line[k])
        return float(found[0] + origin[0]), float(found[1] + origin[1])

    points: list[tuple[float, float]] = []
    for position, index in enumerate(runs[0]):
        k, t0, t1 = pieces[index]
        for t in ((t0, t1) if position == 0 else (t1,)):
            found = point(k, t)
            if not points or math.hypot(found[0] - points[-1][0],
                                        found[1] - points[-1][1]) > _TOL_M:
                points.append(found)
    if len(points) < 2:
        raise not_crossing()
    return Axis(tuple(points))


def _nearest_abscissa(path: np.ndarray, grid: Grid, rows: slice, cols: slice
                      ) -> tuple[np.ndarray, np.ndarray]:
    """La abscisa σ (m desde el primer vértice de ``path``, absoluto) del punto del camino más
    próximo al centro de cada celda de las filas ``rows`` y columnas ``cols`` (fijada en los
    extremos del camino: es la de su vértice; a igual distancia de dos tramos, la menor) y la
    abscisa **sin recortar** (la de la proyección sobre la recta de ese tramo), dos rejillas de la
    forma de la ventana. Todas las celdas, a diferencia de :func:`~.quarry.axis_abscissa`, que mide
    un corredor."""
    row_index = np.arange(rows.start, rows.stop, dtype=np.float64)
    col_index = np.arange(cols.start, cols.stop, dtype=np.float64)
    shape = (row_index.size, col_index.size)
    best = np.full(shape, np.inf)
    sigma = np.full(shape, np.nan)
    reach = np.full(shape, np.nan)
    lengths = np.hypot(*np.diff(path, axis=0).T)
    walked = 0.0
    for i in range(lengths.size):
        length = float(lengths[i])
        if not length > 0.0:
            continue
        along, across = _segment_frame(path[i], path[i + 1], length, grid, row_index, col_index)
        clamped = np.clip(along, 0.0, length)
        distance2 = across * across + (along - clamped) ** 2
        better = distance2 < best
        best[better] = distance2[better]
        sigma[better] = (walked + clamped)[better]
        reach[better] = (walked + along)[better]
        walked += length
    return sigma, reach


# --- A0 y A1: la huella y la rasante -----------------------------------------------------------


def platform_footprint(job: PlatformJob) -> Footprint:
    """**A0 y A1** (RF-015-19, RF-015-08; plan 015 §5.4): la huella y la rasante de la plataforma de
    ``job`` en su ventana de trabajo. Con una **línea** (su eje, con el ancho ``width_m``), la huella
    es la del corredor de extremos planos de RF-014-09 y σ, la abscisa del punto más próximo de todo
    el eje; con un **polígono**, las celdas por su centro y σ la del punto más próximo de su eje
    (fijada en los extremos): el enlazado —su parte de dentro, de lado a lado— o, sin enlace, el
    principal (:func:`axis_of_polygon`), con el aviso ``des.platform_axis_principal``. La rasante de
    cada celda es ``cota inicial + σ · pendiente / 100`` (sección horizontal), a ≤ 10⁻⁹ m del
    cálculo a mano. Los rechazos, en el orden de la documentación del módulo; no modifica la
    entrada."""
    request, geometry, grid = job.request, job.geometry, job.grid
    if geometry.kind not in ("line", "polygon"):
        raise _reject("des.platform_layer_kind", request, _GEOMETRY, _KINDS_ES[geometry.kind])
    line = geometry.kind == "line"
    start_level, gradient, reach_m, width = _resolved(job, line=line)
    notices: list[Notice] = []
    if line:
        assert width is not None
        path = _line_path(job)
        axis = Axis(tuple((float(x), float(y)) for x, y in path))
        _check_levels(job, axis.length_m, start_level, gradient)
        window = corridor_window([path], width / 2.0, grid)
        sigma, reach = axis_abscissa([path], width / 2.0, grid, window)
        cells = np.isfinite(sigma)
        box = _trim(cells, *window)
        if box is None:
            raise _reject("des.platform_no_cells", request, _GEOMETRY, 0)
        rows, cols, _ = box
        inner = (slice(rows.start - window[0].start, rows.stop - window[0].start),
                 slice(cols.start - window[1].start, cols.stop - window[1].start))
        cells, sigma, reach = cells[inner], sigma[inner], reach[inner]
    else:
        parts = _polygon_rings(job)
        top, left, block = _paint(_polygon_spans(geometry.parts, grid), grid.nrows, grid.ncols)
        box = _trim(block, slice(top, top + block.shape[0]), slice(left, left + block.shape[1]))
        if box is None:
            raise _reject("des.platform_no_cells", request, _GEOMETRY, 0)
        rows, cols, cells = box
        if geometry.axis_parts is None:
            axis = axis_of_polygon(cells, grid, offset=(rows.start, cols.start))
            (xa, ya), (xb, yb) = axis.vertices
            notices.append(Notice("des.platform_axis_principal", {
                "entity": request.name, "x": xa, "y": ya, "x_end": xb, "y_end": yb}))
        else:
            axis = _linked_axis(job, parts)
        _check_levels(job, axis.length_m, start_level, gradient)
        sigma, reach = _nearest_abscissa(np.array(axis.vertices), grid, rows, cols)
        sigma, reach = np.where(cells, sigma, np.nan), np.where(cells, reach, np.nan)
    window = work_window(rows, cols, reach_m, grid)
    shape = (window[0].stop - window[0].start, window[1].stop - window[1].start)
    at = (slice(rows.start - window[0].start, rows.stop - window[0].start),
          slice(cols.start - window[1].start, cols.stop - window[1].start))
    footprint = np.zeros(shape, dtype=bool)
    footprint[at] = cells
    abscissa = np.full(shape, np.nan)
    abscissa[at] = sigma
    levels = np.full(shape, np.nan)
    levels[footprint] = start_level + abscissa[footprint] * gradient / 100.0
    found = reach[cells]
    return Footprint(window, footprint, abscissa, levels, axis, float(found.max() - found.min()),
                     start_level, gradient, grid.cell_area, tuple(notices))


# --- A2: aplicar la plataforma -----------------------------------------------------------------


class OffLevelCause(StrEnum):
    """Por qué una celda de la huella no queda en la rasante (RF-015-13, RF-015-24): ``CUT_DENIED``
    (``cut_allowed`` falso: está por encima y las máscaras no dejan cortar), ``FILL_DENIED``
    (``fill_allowed`` falso: en «en corte y relleno» está por debajo y las máscaras no dejan
    rellenar) y ``NOT_FILLED`` (está por debajo en el modo «en corte», que no rellena: no es lo que
    una máscara impide). El valor es el nombre de la máscara o del modo."""

    CUT_DENIED = "cut_allowed"
    FILL_DENIED = "fill_allowed"
    NOT_FILLED = "cut_mode"


@dataclass(frozen=True, slots=True)
class OffLevel:
    """Un grupo 4-conexo de celdas de la huella que no quedan en la rasante (A2, RF-015-24): su
    número ``group`` (desde 1, en el orden de su primera celda recorriendo la rejilla fila a fila
    desde el norte), su ``cause``, sus ``cells``, su ``area_m2``, su diferencia máxima con la rasante
    ``max_m`` (m, positiva) y su centro ``x``, ``y`` (m, absolutos en float64: la media de los
    centros de sus celdas)."""

    group: int
    cause: OffLevelCause
    cells: int
    area_m2: float
    max_m: float
    x: float
    y: float


@dataclass(frozen=True, slots=True, eq=False)
class Applied:
    """La plataforma aplicada sobre su superficie de partida (A2; RF-015-20, RF-015-21), en la
    ventana de trabajo de su huella (``window``; todas las rejillas son de su forma) y en el
    ``mode`` pedido: ``surface`` (m, float64, **nueva**: la superficie de partida con la huella
    aplicada; el resto, igual) y ``at_level`` (la huella que queda en la rasante a 10⁻⁹ m: las
    semillas del borde).

    ``cut_m3`` y ``fill_m3`` son el corte y el relleno **de la huella** (m³; el borde, de la T08) y
    ``cut_cells`` y ``fill_cells``, las celdas que bajan y que suben. Lo que no queda en la rasante:
    ``above`` (por encima, que son las celdas que las máscaras no dejan cortar) y ``below`` (por
    debajo: lo que el modo «en corte» no rellena o, en «en corte y relleno», lo que las máscaras no
    dejan rellenar), cada uno en grupos (:class:`OffLevel`); y las máscaras de lo que **las máscaras**
    impiden, ``cut_denied`` y ``fill_denied`` (esta, solo en «en corte y relleno»), para mirar de qué
    restricción es esa zona (RF-015-13)."""

    window: tuple[slice, slice]
    mode: PlatformMode
    surface: np.ndarray
    at_level: np.ndarray
    cut_cells: int
    fill_cells: int
    cut_m3: float
    fill_m3: float
    cut_denied: np.ndarray
    fill_denied: np.ndarray
    above: tuple[OffLevel, ...]
    below: tuple[OffLevel, ...]
    cell_area_m2: float

    @property
    def blocked_cells(self) -> int:
        """Las celdas de la huella que las máscaras no dejan mover (cortar o rellenar)."""
        return int(np.count_nonzero(self.cut_denied)) + int(np.count_nonzero(self.fill_denied))

    @property
    def blocked_area_m2(self) -> float:
        """El área (m²) que las máscaras no dejan mover: la de ``blocked_cells``."""
        return self.blocked_cells * self.cell_area_m2


def _mode(job: PlatformJob) -> PlatformMode:
    """El modo de la plataforma de ``job`` (``des.entity_param_choice`` si no es de su lista); sin el
    valor, el de la familia de parámetros («en corte», D-5)."""
    found = job.values.get(PlatformParam.MODE.value)
    if found is None:
        found = PLATFORM_PARAMS[PlatformParam.MODE.value].default
    return PlatformMode(check_entity_param(job.request.name, job.code, PlatformParam.MODE, found))


def _check_footprint(job: PlatformJob, footprint: Footprint) -> None:
    """``ValueError`` (error del programa) si la ventana de ``footprint`` no cabe en la rejilla de
    ``job`` o sus rejillas no son de su forma."""
    rows, cols = footprint.window
    grid = job.grid
    if not (0 <= rows.start < rows.stop <= grid.nrows and 0 <= cols.start < cols.stop <= grid.ncols
            and rows.step in (None, 1) and cols.step in (None, 1)):
        raise ValueError(f"la ventana de la huella ({rows}, {cols}) no cabe en la rejilla del "
                         f"trabajo de {grid.nrows} filas y {grid.ncols} columnas")
    shape = (rows.stop - rows.start, cols.stop - cols.start)
    for name in ("cells", "levels"):
        found = getattr(footprint, name).shape
        if found != shape:
            raise ValueError(f"«{name}» de la huella es de la forma {found}, no de la de su "
                             f"ventana {shape}")


def _group_units(chosen: np.ndarray, rows: np.ndarray, cols: np.ndarray, depth: np.ndarray,
                 cause: OffLevelCause, grid: Grid, window: tuple[slice, slice],
                 box: tuple[slice, slice]) -> Generator[None, None, tuple[OffLevel, ...]]:
    """Los grupos 4-conexos (:class:`OffLevel`) de las celdas de la huella ``chosen`` (de las
    celdas de la huella, en su orden): ``rows`` y ``cols`` son su posición en la ventana, ``depth``
    su diferencia con la rasante y ``box`` la caja de la huella en la ventana (el etiquetado solo
    recorre esa caja). Las unidades del etiquetado son las de ``grids._label_units``."""
    if not chosen.any():
        return ()
    picked_rows, picked_cols = rows[chosen], cols[chosen]
    mask = np.zeros((box[0].stop - box[0].start, box[1].stop - box[1].start), dtype=bool)
    mask[picked_rows - box[0].start, picked_cols - box[1].start] = True
    labels = yield from _label_units(mask)
    tags = labels.grid[picked_rows - box[0].start, picked_cols - box[1].start]
    count = labels.count + 1
    row_sum = np.bincount(tags, weights=picked_rows + window[0].start, minlength=count)
    col_sum = np.bincount(tags, weights=picked_cols + window[1].start, minlength=count)
    top = np.zeros(count)
    np.maximum.at(top, tags, depth[chosen])
    found = []
    for index in range(1, count):
        cells = int(labels.sizes[index - 1])
        x = grid.west + (col_sum[index] / cells + 0.5) * grid.dx
        y = grid.north - (row_sum[index] / cells + 0.5) * grid.dy
        found.append(OffLevel(index, cause, cells, cells * grid.cell_area, float(top[index]),
                              float(x), float(y)))
    return tuple(found)


def _apply_units(job: PlatformJob, footprint: Footprint, mode: PlatformMode
                 ) -> Generator[None, None, Applied]:
    """Las unidades de :func:`apply_platform_steps`: las celdas de la huella (sin bucle por celda,
    sobre las de la huella y no sobre la ventana), la superficie y los grupos."""
    window, cells, grid = footprint.window, footprint.cells, job.grid
    start = job.start[window]
    z = start[cells]
    level = footprint.levels[cells]
    missing = int(np.count_nonzero(~np.isfinite(z)))
    if missing or not np.isfinite(level).all():
        raise ValueError(
            f"la plataforma «{job.request.name}» ({job.code}) tiene {missing} celdas sin dato en "
            "su huella (o una rasante sin cota): la preparación lo rechaza antes de calcular "
            "(RF-015-09)")
    yield None
    new = np.where(job.cut_allowed[window][cells], np.minimum(z, level), z)
    if mode is PlatformMode.CUT_FILL:
        new = np.where(job.fill_allowed[window][cells] & (z < level), level, new)
    drop = z - new
    gap = new - level
    near = np.abs(gap) <= _TOL_M
    above = gap > _TOL_M
    below = gap < -_TOL_M
    cut_m3 = float(np.sum(np.maximum(drop, 0.0))) * grid.cell_area
    fill_m3 = float(np.sum(np.maximum(-drop, 0.0))) * grid.cell_area
    yield None
    surface = np.array(start, dtype=np.float64, copy=True)
    surface[cells] = new
    at_level = np.zeros(cells.shape, dtype=bool)
    at_level[cells] = near
    cut_denied = np.zeros(cells.shape, dtype=bool)
    cut_denied[cells] = above
    fill_denied = np.zeros(cells.shape, dtype=bool)
    if mode is PlatformMode.CUT_FILL:
        fill_denied[cells] = below
    yield None
    rows, cols = np.nonzero(cells)
    box = (slice(int(rows.min()), int(rows.max()) + 1), slice(int(cols.min()), int(cols.max()) + 1))
    over = yield from _group_units(above, rows, cols, gap, OffLevelCause.CUT_DENIED, grid, window,
                                   box)
    why = OffLevelCause.FILL_DENIED if mode is PlatformMode.CUT_FILL else OffLevelCause.NOT_FILLED
    under = yield from _group_units(below, rows, cols, -gap, why, grid, window, box)
    return Applied(window, mode, surface, at_level, int(np.count_nonzero(drop > 0.0)),
                   int(np.count_nonzero(drop < 0.0)), cut_m3, fill_m3, cut_denied, fill_denied,
                   over, under, grid.cell_area)


def apply_platform_steps(job: PlatformJob, footprint: Footprint, *,
                         budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """**A2** (RF-015-20, RF-015-21, RF-015-06, RF-015-13; plan 015 §5.4): aplica la plataforma de
    ``job`` con su ``footprint`` (:func:`platform_footprint`) sobre su superficie de partida, por
    pasos de ``budget_s`` como mucho: el último ``Progress`` (fase ``platform_apply``) lleva el
    :class:`Applied`.

    En el modo «en corte» (el de por defecto) ``z' = mín(z, rasante)`` en las celdas de la huella con
    ``cut_allowed``: **ninguna celda sube** (el lomo de B7: la plataforma es el fondo de su corredor,
    no una cota mínima). En «en corte y relleno», además ``z' = rasante`` donde ``z < rasante`` y
    ``fill_allowed``. Fuera de la huella y donde las máscaras no dejan mover, ``z' = z`` bit a bit.
    El corte y el relleno son los de la huella (m³); el borde, de la T08. Lo que no queda en la
    rasante se agrupa con su área, su diferencia máxima, su lugar y su causa (:class:`Applied`).

    Rechazos al llamar: un modo que no es de la lista (``des.entity_param_choice``, con la entidad, el
    campo y el valor; sin el valor ``mode``, el de por defecto) y ``ValueError`` (errores del
    programa) si la ventana de la huella no es de la rejilla del trabajo; al avanzar, ``ValueError``
    si falta dato en la huella (lo rechaza antes la preparación, RF-015-09, T11: no se oculta con un
    valor). Ninguna entrada se modifica y no se escribe nada; cerrar el generador a mitad no deja
    nada."""
    mode = _mode(job)
    _check_footprint(job, footprint)
    work = _apply_units(job, footprint, mode)
    return pace_progress(work, budget_s, phase="platform_apply",
                         running="Aplicando la plataforma…", finished="Plataforma aplicada")


def apply_platform(job: PlatformJob, footprint: Footprint) -> Applied:
    """**A2**: :func:`apply_platform_steps` hasta el final, sin pasos: el :class:`Applied` de la
    plataforma de ``job`` con su ``footprint``. Los mismos rechazos."""
    mode = _mode(job)
    _check_footprint(job, footprint)
    work = _apply_units(job, footprint, mode)
    while True:
        try:
            next(work)
        except StopIteration as done:
            return done.value
