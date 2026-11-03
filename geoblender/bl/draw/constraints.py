# SPDX-License-Identifier: GPL-3.0-or-later
"""La superposición «Ver restricciones y límites» en la Vista 3D (spec 012, T26; HU-012-1 a
HU-012-4; RF-012-18; RNF-012-05, RNF-012-06; plan 012 §5.3.3, §5.5, D-30; comprobación manual M4).

Con el control 30 (``geoblender.core_toggle_constraints_overlay``) activo, la Vista 3D muestra,
encima de la escena y **sin escribir nada en el proyecto** (ni objetos en la escena: D-30), lo que
dicen las restricciones de la versión activa:

- **el contorno de cada restricción**, con un color por tipo (el mismo de su estilo en QGIS,
  ``core.constraints.styles.COLORS``): los límites, algo más gruesos; una desactivada en la
  versión, tenue; un punto, con una cruz de :data:`POINT_ARM_M` m de brazo;
- **su zona en la rejilla** (con las máscaras de la versión al día): rayas horizontales por el
  centro de las celdas de sus tramos de fila (a lo sumo :data:`ZONE_LINES` por zona), con el color
  de su tipo; no el interior de los límites, que es el dominio; sí la banda hacia dentro del
  límite legal;
- **el dominio por defecto** y **la franja de solo relleno** (los bits de la rejilla de clases),
  rayados con su color;
- **sus nombres** (``blf``, junto a un punto de cada una; como mucho :data:`MAX_LABELS`, los
  más cercanos al centro de la vista) y **una leyenda** abajo a la derecha: una fila con el color
  de cada tipo presente (y cuántas hay), el dominio y la franja, y una nota si faltan las máscaras
  (sin compilar u obsoletas) o si no hay versión activa.

Todo va **sobre la superficie elegida** en la ventana Restricciones… (``overlay_surface``) o, si no
hay ninguna, sobre la rejilla del proyecto más reciente, o, sin ninguna, a la cota del GeoOrigin;
los segmentos largos se parten para que sigan su cota. Las posiciones son locales respecto al
GeoOrigin (float64 hasta el último paso, ADR-0005).

**Lotes** (:class:`Batch`): un lote de segmentos por tipo y papel (contorno, zona, dominio,
franja; :class:`Built` los guarda), de ``numpy`` en coordenadas locales; el lote de ``gpu`` se
crea la primera vez que se dibuja y se reutiliza (RNF-012-05: el redibujo, ≤ 5 ms). Lo que se
dibuja en píxeles (:func:`screen_items`) se calcula sin ``gpu``, para probarlo.

**Construcción por pasos** (:func:`build_steps`; RNF-012-06): nada se lee ni se calcula de una
vez. Un temporizador (:func:`tick`) avanza los pasos, de :data:`STEP_BUDGET_S` s como mucho cada
uno; activar la superposición ocupa lo que cabe en el siguiente ciclo y no el hilo de Blender. Se
**rehace** (:func:`rebuild`) al cambiar la versión activa, al compilar o cambiar lo que dibuja
(:func:`stamp`: la versión, el estado de sus máscaras, las operaciones, los datos y los
parámetros), al elegir otra superficie; y se **quita** (:func:`disable`) al pulsar el control otra
vez, al cerrar o cambiar de proyecto, al conmutar a la interfaz de Blender
(``bl.ui.switcher.add_blender_hook``) y al desactivar Geoblender (:func:`unregister`, principio 8).
Un error al dibujar se registra una vez y deja de dibujar: nunca una traza por fotograma.

**Lo que reutiliza la vista previa del diseño** (spec 013, T25; ``bl.draw.design``): sus zonas,
contornos, nombres y leyenda (:func:`build_steps`, que acepta las máscaras y la superficie ya
leídas), las rayas de una máscara (:func:`mask_hatch_steps`), la superficie y el ajuste a ella
(:func:`ground_steps`, :func:`drape_segments_steps`, :func:`drape_points_steps`) y el dibujo de
los lotes (:func:`draw_lines`, :func:`pulled`).
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable, Generator, Sequence
from dataclasses import dataclass, field
from typing import Any

import blf
import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix

from ...core.constraints.model import Constraint, ConstraintType, GeometryKind
from ...core.constraints.styles import COLORS, ELSE_COLOR
from ...core.errors import GeoblenderError
from ...core.georef import world_to_local
from ...core.i18n import language, tr
from ...gis.grid import Grid
from ...gis.masks import access as mask_access
from ...gis.masks import store as mask_store
from ...gis.masks.combine import ClassBit
from ...gis.masks.zones import Runs
from ...gis.raster import Raster, sample
from ...reserves import surfaces as res_surfaces
from ..props.core_constraints import WINDOW_MANAGER_PROPERTY
from ..scene import project_session
from ..scene import versions as scene_versions
from ..scene.constraint_views import terrain_choices
from . import dh_overlay
from .dh_overlay import Box, LegendRow, Text

__all__ = [
    "DOMAIN", "LABEL_OFFSET", "MAX_LABELS", "OUTLINE", "OUTLINE_PX", "POINT_ARM_M", "STRIP",
    "UNTYPED", "ZONE", "Batch", "Built", "Label", "Pace", "Request", "Surface", "HATCH_PX",
    "LIMIT_PX",
    "build_steps", "building", "built", "color_of", "disable", "draw_lines", "drape_points_steps",
    "drape_segments_steps", "drawing", "enable", "enabled", "ground_steps", "hatch_segments",
    "mask_hatch_steps", "on_project_changed", "on_project_read", "on_surface_changed",
    "on_version_changed", "pulled", "rebuild", "register", "screen_items", "stamp", "tick",
    "unregister",
]

LOGGER = logging.getLogger("geoblender.bl.draw")

OUTLINE = "outline"
"""El papel de un lote: el contorno de las restricciones de un tipo."""
ZONE = "zone"
"""El papel de un lote: las rayas de las zonas de un tipo."""
DOMAIN = "domain"
"""El papel (y la clave) del lote del dominio por defecto."""
STRIP = "strip"
"""El papel (y la clave) del lote de la franja de solo relleno."""
UNTYPED = "untyped"
"""La clave de las restricciones sin tipo (dibujadas en QGIS y aún sin completar)."""

STEP_BUDGET_S = 0.015
"""Lo que dura como mucho cada paso de la construcción (RNF-012-06: ninguna llamada de más de
0,2 s; los pasos, de ≤ 50 ms)."""
TICK_BUDGET_S = 0.03
"""Lo que avanza como mucho cada llamada del temporizador."""
TICK_INTERVAL_S = 0.005
"""La espera entre dos llamadas del temporizador: la justa para que Blender atienda la interfaz."""
POINT_ARM_M = 3.0
"""El brazo (m) de la cruz que representa un punto."""
ZONE_LINES = 10
"""Las rayas como mucho de una zona (por sus filas)."""
DOMAIN_LINES = 48
STRIP_LINES = 96
"""Las rayas del dominio por defecto y de la franja, a lo largo de toda la rejilla."""
MAX_ZONE_SEGMENTS = 4000
"""Los segmentos como mucho de las rayas de una zona (las zonas muy fragmentadas, aclaradas)."""
ROWS_PER_STEP = 32
"""Las filas de la rejilla de clases que se rayan en cada unidad."""
POINTS_PER_STEP = 20_000
"""Los puntos cuya cota se lee de la superficie en cada unidad."""
CONSTRAINTS_PER_STEP = 64
"""Las restricciones cuyo contorno se prepara como mucho en cada unidad."""
DRAPE_CELLS = 4.0
"""Lo que miden como mucho los segmentos sobre una superficie, en celdas de ella."""
DRAPE_MIN_M = 5.0
"""Y como mínimo en metros."""

OUTLINE_PX = 2.5
LIMIT_PX = 3.5
HATCH_PX = 1.2
"""El trazo (px) de un contorno, de un límite y de las rayas."""
INACTIVE_ALPHA = 0.3
"""La opacidad del contorno de una restricción desactivada en la versión."""
HATCH_ALPHA = 0.75
DOMAIN_COLOR = (0.92, 0.92, 0.92, 0.45)
STRIP_COLOR = (0.96, 0.96, 0.6, 0.9)
"""El color de las rayas del dominio por defecto y de la franja de solo relleno."""

MAX_LABELS = 60
"""Los nombres que se dibujan como mucho en cada Vista 3D."""
LABEL_OFFSET = (8.0, 6.0)
"""Dónde va un nombre respecto a su sitio, en px (arriba a la derecha)."""
CULL_PX = 64.0
"""Lo que puede quedar fuera de la región algo que se dibuja (más lejos, no)."""
LEGEND_COLOR = (1.0, 1.0, 1.0, 1.0)
FONT_ID = 0
FONT_PX = 12.0
SHADER = "POLYLINE_UNIFORM_COLOR"
DEPTH_PULL = 0.002
"""Lo que se acerca el trazo a la cámara, en fracción de su distancia (como las maestras:
``bl.draw.contours``), para que no lo tape la superficie sobre la que está."""

type Color = tuple[float, float, float, float]


# --- Los datos de lo que se dibuja --------------------------------------------------------------


def color_of(key: str) -> Color:
    """El color RGBA (0–1) de la clave ``key`` (un tipo de restricción, :data:`UNTYPED`,
    :data:`DOMAIN` o :data:`STRIP`): el de su estilo en QGIS, opaco; el dominio y la franja, los
    suyos."""
    if key == DOMAIN:
        return DOMAIN_COLOR
    if key == STRIP:
        return STRIP_COLOR
    red, green, blue = ELSE_COLOR if key == UNTYPED else COLORS[ConstraintType(key)]
    return (red / 255.0, green / 255.0, blue / 255.0, 1.0)


def _hex(color: Color) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(round(part * 255.0) for part in color[:3]))


@dataclass(frozen=True, eq=False)
class Batch:
    """Un lote de segmentos de un color: ``key`` (el tipo, :data:`UNTYPED`, :data:`DOMAIN` o
    :data:`STRIP`), su ``role`` (:data:`OUTLINE`, :data:`ZONE`, :data:`DOMAIN` o :data:`STRIP`),
    su color y su trazo, y ``positions`` (float32 ``(2k, 3)``, locales respecto al GeoOrigin: cada
    dos filas, un segmento). ``dim``: el contorno de una restricción desactivada. El lote de
    ``gpu`` se crea al dibujarlo la primera vez."""

    key: str
    role: str
    color: Color
    width_px: float
    positions: np.ndarray = field(repr=False)
    dim: bool = False
    _gpu: list[Any] = field(default_factory=list, repr=False)

    @property
    def segments(self) -> int:
        """Cuántos segmentos tiene."""
        return int(len(self.positions) // 2)

    def gpu_batch(self, shader: Any) -> Any:
        """El lote de ``gpu`` de sus segmentos (se crea la primera vez y se guarda)."""
        if not self._gpu:
            self._gpu.append(batch_for_shader(shader, "LINES", {"pos": self.positions}))
        return self._gpu[0]


@dataclass(frozen=True)
class Label:
    """El nombre de una restricción: su texto, su sitio (local, float) y su color."""

    text: str
    xyz: tuple[float, float, float]
    color: Color


@dataclass(frozen=True, eq=False)
class Built:
    """Lo construido para una versión: su uid y su código (``None`` y ``""`` sin versión), el
    estado de sus máscaras (``current``, ``stale``, ``missing`` o ``""`` sin versión), el nombre
    de la superficie sobre la que se dibuja (``""``: la cota del GeoOrigin), los lotes
    (:class:`Batch`; los de debajo primero), los nombres, la leyenda y el sello con que se
    construyó (:func:`stamp`)."""

    version_uid: str | None
    version_code: str
    masks: str
    surface: str
    batches: tuple[Batch, ...]
    labels: tuple[Label, ...]
    legend: tuple[LegendRow, ...]
    stamp: tuple[Any, ...]

    def batch(self, key: str, role: str, *, dim: bool = False) -> Batch | None:
        """El lote de ``key`` y ``role`` (``dim``: el de las desactivadas); ``None`` si no hay."""
        return next((batch for batch in self.batches
                     if (batch.key, batch.role, batch.dim) == (key, role, dim)), None)


@dataclass(frozen=True, eq=False)
class Surface:
    """La superficie sobre la que se dibuja: el nombre de su dato y su rejilla de cotas."""

    name: str
    raster: Raster

    def elevations(self, xy: np.ndarray, fallback: float) -> np.ndarray:
        """Las cotas de los puntos ``xy`` (``(n, 2)`` absolutos): la interpolación bilineal entre
        los centros de celda; en el borde (donde falta algún vecino), la de la celda que contiene
        el punto; y donde no hay dato, ``fallback``."""
        found = sample(self.raster, xy)
        bad = ~np.isfinite(found)
        if bad.any():
            found[bad] = sample(self.raster, xy[bad], method="nearest")
            bad = ~np.isfinite(found)
            found[bad] = fallback
        return found


@dataclass(frozen=True, eq=False)
class Request:
    """Lo que se construye: el proyecto, la versión (``None``: ninguna), su código, la superficie
    elegida (``""``: la más reciente), el idioma de los textos y el sello de lo que se lee."""

    project: Any
    version_uid: str | None
    version_code: str
    surface: str
    language: str
    stamp: tuple[Any, ...]


# --- Construir ----------------------------------------------------------------------------------


class _Pace:
    """Cuándo ceder el hilo: ``due()`` dice si ya pasó el presupuesto de un paso (y empieza el
    siguiente)."""

    def __init__(self, budget_s: float) -> None:
        self.budget_s = budget_s
        self.mark = time.perf_counter()

    def due(self) -> bool:
        now = time.perf_counter()
        if now - self.mark < self.budget_s:
            return False
        self.mark = now
        return True


Pace = _Pace
""":class:`_Pace`, para quien da pasos con el mismo ritmo (``bl.draw.design``)."""


def _row_segments(row: np.ndarray, col0: np.ndarray, col1: np.ndarray, grid: Grid) -> np.ndarray:
    """Los segmentos horizontales ``(k, 2, 2)`` absolutos por el centro de las celdas de los
    tramos (fila, primera columna, columna siguiente a la última)."""
    found = np.empty((len(row), 2, 2), dtype=np.float64)
    y = grid.north - (row.astype(np.float64) + 0.5) * grid.dy
    found[:, 0, 0] = grid.west + col0 * grid.dx
    found[:, 1, 0] = grid.west + col1 * grid.dx
    found[:, :, 1] = y[:, None]
    return found


def hatch_segments(runs: Runs, grid: Grid, lines: int) -> np.ndarray:
    """Las rayas de la zona ``runs`` de ``grid``: segmentos ``(k, 2, 2)`` absolutos, uno por tramo
    de las filas elegidas (a lo sumo ``lines`` filas, a intervalos iguales desde la primera de la
    zona; con menos filas que rayas, todas). Una zona vacía no da ninguna; la muy fragmentada se
    aclara hasta :data:`MAX_ZONE_SEGMENTS`."""
    if len(runs) == 0:
        return np.empty((0, 2, 2), dtype=np.float64)
    first, last = int(runs.row[0]), int(runs.row[-1])
    stride = max(1, -(-(last - first + 1) // max(1, int(lines))))
    keep = (runs.row - first) % stride == 0
    found = _row_segments(runs.row[keep], runs.col0[keep], runs.col1[keep], grid)
    if len(found) > MAX_ZONE_SEGMENTS:
        found = found[::-(-len(found) // MAX_ZONE_SEGMENTS)]
    return found


def _rows_hatch_steps(select: Callable[[np.ndarray], np.ndarray], grid: Grid, lines: int,
                      pace: _Pace) -> Generator[None, None, np.ndarray]:
    """Las rayas de las celdas que ``select`` elige (dadas unas filas, su máscara booleana), en
    ``lines`` filas repartidas por la rejilla ``grid``, por trozos de :data:`ROWS_PER_STEP`
    filas: segmentos ``(k, 2, 2)`` absolutos."""
    stride = max(1, grid.nrows // max(1, int(lines)))
    chosen = np.arange(stride // 2, grid.nrows, stride)
    parts: list[np.ndarray] = []
    for top in range(0, len(chosen), ROWS_PER_STEP):
        rows = chosen[top:top + ROWS_PER_STEP]
        found = Runs.from_mask(select(rows))
        if len(found):
            parts.append(_row_segments(rows[found.row], found.col0, found.col1, grid))
        if pace.due():
            yield
    return np.concatenate(parts) if parts else np.empty((0, 2, 2), dtype=np.float64)


def _class_hatch_steps(masks: Any, wanted: ClassBit, unwanted: ClassBit, lines: int,
                       pace: _Pace) -> Generator[None, None, np.ndarray]:
    """Las rayas de las celdas de la rejilla de clases de ``masks`` que tienen todos los bits de
    ``wanted`` y ninguno de ``unwanted``, en ``lines`` filas repartidas por la rejilla, por
    trozos de :data:`ROWS_PER_STEP` filas: segmentos ``(k, 2, 2)`` absolutos."""
    classes = masks.classes
    low, high = np.uint16(int(wanted)), np.uint16(int(unwanted))

    def select(rows: np.ndarray) -> np.ndarray:
        sub = classes[rows]
        return ((sub & low) == low) & ((sub & high) == 0)

    return (yield from _rows_hatch_steps(select, masks.grid, lines, pace))


def mask_hatch_steps(mask: np.ndarray, grid: Grid, lines: int, *,
                     budget_s: float = STEP_BUDGET_S) -> Generator[None, None, np.ndarray]:
    """Las rayas de las celdas verdaderas de ``mask`` (booleana, de la forma de ``grid``): como
    las del dominio por defecto, en ``lines`` filas repartidas por la rejilla y por trozos de
    :data:`ROWS_PER_STEP` filas (``bl.draw.design`` las usa para el dominio de trabajo): segmentos
    ``(k, 2, 2)`` absolutos. El resultado es el ``StopIteration.value``."""
    return (yield from _rows_hatch_steps(lambda rows: mask[rows], grid, lines, _Pace(budget_s)))


def _outline(item: Constraint) -> np.ndarray:
    """Los segmentos ``(k, 2, 2)`` absolutos del contorno de ``item``: los lados de sus anillos
    (cerrados), los tramos de su camino o la cruz de su punto."""
    pieces: list[np.ndarray] = []
    for part in item.parts:
        for path in part:
            if item.kind is GeometryKind.POINT:
                x, y = (float(value) for value in path.reshape(-1, 2)[0])
                arm = POINT_ARM_M
                pieces.append(np.array([[[x - arm, y], [x + arm, y]],
                                        [[x, y - arm], [x, y + arm]]], dtype=np.float64))
                continue
            points = path
            if item.kind is GeometryKind.POLYGON and not np.array_equal(points[0], points[-1]):
                points = np.vstack([points, points[:1]])
            if len(points) >= 2:
                pieces.append(np.stack([points[:-1], points[1:]], axis=1))
    return np.concatenate(pieces) if pieces else np.empty((0, 2, 2), dtype=np.float64)


def _anchor(item: Constraint) -> tuple[float, float] | None:
    """El sitio del nombre de ``item`` (absoluto): el centro de la caja de su primer anillo, el
    vértice del medio de su camino o su punto."""
    for part in item.parts:
        for path in part:
            if item.kind is GeometryKind.POLYGON:
                low, high = path.min(axis=0), path.max(axis=0)
                return (float((low[0] + high[0]) / 2.0), float((low[1] + high[1]) / 2.0))
            point = path[len(path) // 2]
            return (float(point[0]), float(point[1]))
    return None


def _densify(segments: np.ndarray, longest: float) -> np.ndarray:
    """``segments`` ``(n, 2, 2)`` con cada uno de más de ``longest`` partido en trozos iguales."""
    if len(segments) == 0:
        return segments
    delta = segments[:, 1] - segments[:, 0]
    length = np.hypot(delta[:, 0], delta[:, 1])
    parts = np.maximum(1, np.ceil(length / longest)).astype(np.int64)
    if int(parts.max()) == 1:
        return segments
    owner = np.repeat(np.arange(len(segments)), parts)
    index = np.arange(int(parts.sum())) - np.repeat(np.cumsum(parts) - parts, parts)
    count = parts[owner].astype(np.float64)
    start = segments[owner, 0] + delta[owner] * (index / count)[:, None]
    end = segments[owner, 0] + delta[owner] * ((index + 1) / count)[:, None]
    return np.stack([start, end], axis=1)


def _local_steps(xy: np.ndarray, surface: Surface | None, origin: Any,
                 pace: _Pace) -> Generator[None, None, np.ndarray]:
    """Las posiciones locales (float32 ``(n, 3)``) de los puntos absolutos ``xy`` ``(n, 2)``: a la
    cota de la superficie o, sin ella, a la del GeoOrigin, y respecto al GeoOrigin con
    ``core.georef.world_to_local`` (float64; solo después, float32: ADR-0005). Las cotas se leen
    por trozos de :data:`POINTS_PER_STEP`."""
    height = np.full(len(xy), float(origin.z0), dtype=np.float64)
    if surface is not None:
        for start in range(0, len(xy), POINTS_PER_STEP):
            chunk = xy[start:start + POINTS_PER_STEP]
            height[start:start + len(chunk)] = surface.elevations(chunk, float(origin.z0))
            if pace.due():
                yield
    return world_to_local(np.column_stack([xy, height]), origin).astype(np.float32)


def _positions_steps(segments: np.ndarray, surface: Surface | None, origin: Any,
                     pace: _Pace) -> Generator[None, None, np.ndarray]:
    """Los vértices locales de ``segments`` ``(n, 2, 2)`` absolutos, de dos en dos, partidos
    para que sigan la superficie."""
    if surface is not None:
        grid = surface.raster.grid
        segments = _densify(segments, max(DRAPE_CELLS * max(grid.dx, grid.dy), DRAPE_MIN_M))
    flat = segments.reshape(-1, 2)
    return (yield from _local_steps(flat, surface, origin, pace))


def _latest(project: Any, choices: Sequence[Any]) -> Any:
    """La más reciente de las superficies ``choices`` (por la fecha de su dato)."""
    marks = ", ".join("?" for _ in choices)
    with project.read() as conn:
        found = conn.execute(f"SELECT uid FROM gb_dataset WHERE uid IN ({marks}) "
                             "ORDER BY created_at DESC, fid DESC LIMIT 1",
                             [choice.uid for choice in choices]).fetchone()
    return next((choice for choice in choices if found and choice.uid == found[0]), choices[-1])


def _surface_steps(project: Any, chosen: str, version_uid: str | None,
                   pace: _Pace) -> Generator[None, None, Surface | None]:
    """La superficie sobre la que se dibuja: la rejilla del proyecto ``chosen`` o, si no hay o no
    está, la más reciente; ``None`` si el proyecto no tiene ninguna o no se puede leer (se dibuja
    a la cota del GeoOrigin). La lee por bandas de filas."""
    try:
        choices = terrain_choices(project, version_uid)
        if not choices:
            return None
        pick = next((choice for choice in choices if choice.name == chosen), None)
        if pick is None:
            pick = _latest(project, choices)
        yield
        source = res_surfaces.surface_source(project, pick.ref, version_uid=version_uid or "")
        grid = source.grid
        if grid is None:
            return None
        values = np.full(grid.shape, np.nan, dtype=np.float64)
        for top, band in res_surfaces.band_reader(source, grid):
            values[top:top + np.shape(band)[0]] = band
            if pace.due():
                yield
    except (GeoblenderError, sqlite3.Error, OSError, ValueError):
        LOGGER.warning("No se pudo leer la superficie de las restricciones: se dibujan a la "
                       "cota del GeoOrigin", exc_info=True)
        return None
    return Surface(pick.name, Raster(grid, values, source.header.crs, source.header.vertical))


def ground_steps(project: Any, chosen: str, version_uid: str | None, *,
                 budget_s: float = STEP_BUDGET_S) -> Generator[None, None, Surface | None]:
    """La superficie sobre la que se dibuja (la rejilla ``chosen`` o, si no hay o no está, la más
    reciente; ``None`` si no hay ninguna), leída por bandas de filas. La comparte la vista previa
    del diseño (``bl.draw.design``) para dibujar sobre la misma superficie que las restricciones."""
    return (yield from _surface_steps(project, chosen, version_uid, _Pace(budget_s)))


def drape_segments_steps(segments: np.ndarray, ground: Surface | None, origin: Any, *,
                         budget_s: float = STEP_BUDGET_S) -> Generator[None, None, np.ndarray]:
    """Los vértices locales (float32) de ``segments`` ``(n, 2, 2)`` absolutos, de dos en dos y
    partidos para que sigan ``ground`` (a la cota del GeoOrigin sin ella)."""
    return (yield from _positions_steps(segments, ground, origin, _Pace(budget_s)))


def drape_points_steps(xy: np.ndarray, ground: Surface | None, origin: Any, *,
                       budget_s: float = STEP_BUDGET_S) -> Generator[None, None, np.ndarray]:
    """Las posiciones locales (float32 ``(n, 3)``) de los puntos absolutos ``xy`` ``(n, 2)`` sobre
    ``ground`` (a la cota del GeoOrigin sin ella)."""
    return (yield from _local_steps(xy, ground, origin, _Pace(budget_s)))


_READ: Any = object()
"""El valor por defecto de ``ground`` de :func:`build_steps`: que lea la superficie ella misma."""


def build_steps(request: Request, *, budget_s: float = STEP_BUDGET_S,
                loaded: Any = None, ground: Any = _READ) -> Generator[None, None, Built]:
    """Los pasos que construyen lo que dibuja la superposición para ``request`` (véase el módulo):
    leer las restricciones con su «activa» en la versión, las máscaras (si están al día) y la
    superficie, y preparar los lotes, los nombres y la leyenda. Solo lee. Cada paso dura como
    mucho ``budget_s`` s (salvo una lectura, nunca de más de 0,2 s); el resultado es el
    ``StopIteration.value``. Cerrarlo a mitad no deja nada.

    Quien ya tiene las máscaras de la versión al día (``loaded``) o la superficie sobre la que
    dibujar (``ground``, de :func:`ground_steps`; ``None``: a la cota del GeoOrigin) las pasa
    para no leerlas dos veces (la vista previa del diseño)."""
    project, version_uid, shown = request.project, request.version_uid, request.language
    origin, pace = project.origin, _Pace(budget_s)
    listed = yield from mask_store.shown_constraints_steps(project, version=version_uid)
    state, masks = "", None
    if version_uid:
        try:
            found, _pending = mask_access.mask_state(project, version_uid)
            state = found.value
            yield
            if found is mask_access.MaskState.CURRENT:
                masks = loaded if loaded is not None else (
                    yield from mask_access.load_masks_steps(project, version_uid))
        except (GeoblenderError, sqlite3.Error, OSError):
            LOGGER.warning("No se pudieron leer las máscaras de la versión", exc_info=True)
            state, masks = "missing", None
    surface = ((yield from _surface_steps(project, request.surface, version_uid, pace))
               if ground is _READ else ground)

    outlines: dict[tuple[str, bool], list[np.ndarray]] = {}
    counts: dict[str, int] = {}
    switched_off = 0
    anchors: list[tuple[str, tuple[float, float], Color]] = []
    types: dict[str, ConstraintType | None] = {}
    for number, entry in enumerate(listed, start=1):
        item = entry.constraint
        types[item.code] = item.ctype
        found_segments = _outline(item)
        if len(found_segments) == 0:
            continue
        key = UNTYPED if item.ctype is None else item.ctype.value
        dim = entry.state == "inactive"
        outlines.setdefault((key, dim), []).append(found_segments)
        if dim:
            switched_off += 1
        else:
            counts[key] = counts.get(key, 0) + 1
        place = _anchor(item)
        if place is not None:
            base = color_of(key)
            anchors.append((item.shown_name(shown), place,
                            (*base[:3], INACTIVE_ALPHA + 0.2 if dim else 1.0)))
        if number % CONSTRAINTS_PER_STEP == 0 and pace.due():
            yield

    zones: dict[str, list[np.ndarray]] = {}
    domain = strip = np.empty((0, 2, 2), dtype=np.float64)
    if masks is not None:
        for code, runs in masks.zones.items():
            base_code, _, inner = code.partition(":")
            ctype = types.get(base_code)
            if ctype is None or (ctype.is_limit and not inner):
                continue
            found_segments = hatch_segments(runs, masks.grid, ZONE_LINES)
            if len(found_segments):
                zones.setdefault(ctype.value, []).append(found_segments)
            if pace.due():
                yield
        domain = yield from _class_hatch_steps(
            masks, ClassBit.PERIMETER | ClassBit.LEGAL, ClassBit.UNTOUCHABLE, DOMAIN_LINES, pace)
        strip = yield from _class_hatch_steps(masks, ClassBit.FILL_STRIP, ClassBit(0),
                                              STRIP_LINES, pace)

    wanted: list[tuple[str, str, bool, Color, float, np.ndarray]] = []
    if len(domain):
        wanted.append((DOMAIN, DOMAIN, False, DOMAIN_COLOR, HATCH_PX, domain))
    if len(strip):
        wanted.append((STRIP, STRIP, False, STRIP_COLOR, HATCH_PX, strip))
    for ctype in ConstraintType:
        if ctype.value in zones:
            wanted.append((ctype.value, ZONE, False,
                           (*color_of(ctype.value)[:3], HATCH_ALPHA), HATCH_PX,
                           np.concatenate(zones[ctype.value])))
    for key in (*(ctype.value for ctype in ConstraintType), UNTYPED):
        for dim in (False, True):
            if (key, dim) not in outlines:
                continue
            base = color_of(key)
            width = LIMIT_PX if key != UNTYPED and ConstraintType(key).is_limit else OUTLINE_PX
            wanted.append((key, OUTLINE, dim, (*base[:3], INACTIVE_ALPHA if dim else 1.0),
                           width, np.concatenate(outlines[(key, dim)])))
    batches: list[Batch] = []
    for key, role, dim, color, width, found_segments in wanted:
        positions = yield from _positions_steps(found_segments, surface, origin, pace)
        batches.append(Batch(key, role, color, width, positions, dim))
    places = np.array([place for _text, place, _color in anchors],
                      dtype=np.float64).reshape(-1, 2)
    spots = yield from _local_steps(places, surface, origin, pace)
    labels = tuple(Label(text, (float(x), float(y), float(z)), color)
                   for (text, _place, color), (x, y, z) in zip(anchors, spots.tolist(),
                                                               strict=True))
    legend = _legend(request, state, counts, switched_off, bool(len(domain)), bool(len(strip)),
                     surface)
    return Built(version_uid, request.version_code, state, "" if surface is None else surface.name,
                 tuple(batches), labels, legend, request.stamp)


def _legend(request: Request, state: str, counts: dict[str, int], switched_off: int,
            has_domain: bool, has_strip: bool, surface: Surface | None) -> tuple[LegendRow, ...]:
    """La leyenda: el título con la versión, una fila por tipo presente (con cuántas hay), las
    desactivadas, el dominio y la franja, y las notas (máscaras, superficie)."""
    rows = [LegendRow(tr("Constraints and limits · {version}",
                         version=request.version_code or tr("No version")))]
    for ctype in ConstraintType:
        if counts.get(ctype.value):
            rows.append(LegendRow(tr("{type} ({count})", type=ctype.label(request.language),
                                     count=counts[ctype.value]), _hex(color_of(ctype.value))))
    if counts.get(UNTYPED):
        rows.append(LegendRow(tr("{type} ({count})", type=tr("Without a type"),
                                 count=counts[UNTYPED]), _hex(color_of(UNTYPED))))
    if switched_off:
        rows.append(LegendRow(tr("Switched off in {version} ({count})",
                                 version=request.version_code, count=switched_off),
                              _hex(color_of(UNTYPED))))
    if has_domain:
        rows.append(LegendRow(tr("Default domain"), _hex(DOMAIN_COLOR)))
    if has_strip:
        rows.append(LegendRow(tr("Fill-only strip"), _hex(STRIP_COLOR)))
    if not request.version_uid:
        rows.append(LegendRow(tr("No active version: outlines only")))
    elif state == "stale":
        rows.append(LegendRow(tr("Masks out of date: compile them to see the zones")))
    elif state != "current":
        rows.append(LegendRow(tr("Masks not compiled: outlines only")))
    rows.append(LegendRow(tr("At the elevation of the GeoOrigin") if surface is None
                          else tr("On the surface «{name}»", name=surface.name)))
    return tuple(rows)


# --- Qué cambió ---------------------------------------------------------------------------------


def stamp(project: Any, version_uid: str | None) -> tuple[Any, ...]:
    """El sello de lo que dibuja la superposición para ``version_uid`` (``None``: ninguna): el
    estado de sus máscaras (y los sectores sin búsqueda vigente), cuántas operaciones y datos
    tiene el proyecto, cuándo cambió un dato por última vez y el último cambio de un parámetro.
    Dos sellos distintos: hay que rehacerla. Solo lee (unas lecturas pequeñas)."""
    masks: tuple[Any, ...] = ()
    if version_uid:
        try:
            found, pending = mask_access.mask_state(project, version_uid)
            masks = (found.value, pending)
        except (GeoblenderError, sqlite3.Error, OSError):
            masks = ("error",)
    with project.read() as conn:
        operations = tuple(conn.execute(
            "SELECT count(*), coalesce(max(fid), 0) FROM gb_operation").fetchone())
        datasets = tuple(conn.execute(
            "SELECT count(*), coalesce(max(modified_at), '') FROM gb_dataset").fetchone())
        (changes,) = conn.execute(
            "SELECT coalesce(max(fid), 0) FROM gb_parameter_history").fetchone()
    return (version_uid, masks, operations, datasets, int(changes))


# --- Lo que se dibuja en píxeles ----------------------------------------------------------------


def _label_items(labels: Sequence[Label], matrix: Any, size: tuple[float, float],
                 scale: float) -> list[Any]:
    """Los nombres que caben en la región (``size``), cada uno junto a su sitio: como mucho
    :data:`MAX_LABELS`, los más cercanos al centro."""
    if not labels:
        return []
    shown = dh_overlay.to_screen([label.xyz for label in labels], matrix, size)
    inside = (np.isfinite(shown[:, 0]) & np.isfinite(shown[:, 1])
              & (shown[:, 0] >= -CULL_PX) & (shown[:, 0] <= size[0] + CULL_PX)
              & (shown[:, 1] >= -CULL_PX) & (shown[:, 1] <= size[1] + CULL_PX))
    index = np.flatnonzero(inside)
    if len(index) > MAX_LABELS:
        centre = np.array(size, dtype=np.float64) / 2.0
        distance = np.hypot(shown[index, 0] - centre[0], shown[index, 1] - centre[1])
        index = np.sort(index[np.argsort(distance, kind="stable")[:MAX_LABELS]])
    dx, dy = LABEL_OFFSET[0] * scale, LABEL_OFFSET[1] * scale
    return [Text(float(shown[i, 0]) + dx, float(shown[i, 1]) + dy, labels[i].text,
                 labels[i].color) for i in index.tolist()]


def _rgba(color: str) -> Color:
    return (int(color[1:3], 16) / 255.0, int(color[3:5], 16) / 255.0,
            int(color[5:7], 16) / 255.0, 1.0)


def _legend_items(rows: Sequence[LegendRow], measure: Callable[[str], float], scale: float,
                  size: tuple[float, float]) -> list[Any]:
    """La leyenda abajo a la derecha: su fondo y, de arriba abajo, cada fila (los títulos y las
    notas a la izquierda; las entradas, su cuadro de color y su texto)."""
    if not rows:
        return []
    row, swatch, gap = (dh_overlay.ROW_PX * scale, dh_overlay.SWATCH_PX * scale,
                        dh_overlay.GAP_PX * scale)
    margin, pad = dh_overlay.MARGIN_PX * scale, dh_overlay.PAD_PX * scale
    width = max(float(measure(item.text)) + (swatch + gap if item.color else 0.0)
                for item in rows)
    height = len(rows) * row
    right = size[0] - margin
    left = right - width
    items: list[Any] = [Box(left - pad, margin - pad, right + pad, margin + height + pad,
                            dh_overlay.PANEL)]
    baseline = (row - FONT_PX * scale) / 2.0 + 2.0 * scale
    for index, item in enumerate(rows):
        bottom = margin + height - (index + 1) * row
        if item.color is None:
            items.append(Text(left, bottom + baseline, item.text, LEGEND_COLOR))
            continue
        low = bottom + (row - swatch) / 2.0
        items.append(Box(left, low, left + swatch, low + swatch, _rgba(item.color)))
        items.append(Text(left + swatch + gap, bottom + baseline, item.text, LEGEND_COLOR))
    return items


def screen_items(built: Built, matrix: Any, size: tuple[float, float], *,
                 measure: Callable[[str], float], scale: float = 1.0) -> list[Any]:
    """Lo que la superposición dibuja en píxeles de la región (``size``) con la matriz de la
    vista ``matrix``: los nombres que caben y la leyenda (``bl.draw.dh_overlay.Text`` y ``Box``,
    que :func:`bl.draw.dh_overlay.paint` pinta). ``measure`` da el ancho en px de un texto;
    ``scale``, la escala de la interfaz."""
    items = _label_items(built.labels, matrix, size, scale)
    items.extend(_legend_items(built.legend, measure, scale, size))
    return items


def _pulled(view_matrix: Matrix, perspective: bool, view_distance: float) -> Matrix:
    """``view_matrix`` con lo que dibuja acercado a la cámara :data:`DEPTH_PULL` (como las curvas
    maestras, ``bl.draw.contours``)."""
    if perspective:
        scale = 1.0 - DEPTH_PULL
        return Matrix.Diagonal((scale, scale, scale, 1.0)) @ view_matrix
    return Matrix.Translation((0.0, 0.0, DEPTH_PULL * max(float(view_distance), 1.0))) @ (
        view_matrix)


pulled = _pulled
""":func:`_pulled`, para quien dibuja con las mismas matrices (``bl.draw.design``)."""


def draw_lines(built: Built, *, view_matrix: Matrix, projection_matrix: Matrix, perspective: bool,
               view_distance: float, viewport_size: tuple[float, float], pixel_size: float) -> int:
    """Dibuja en el *framebuffer* activo los lotes de ``built`` (los de debajo primero) con las
    matrices dadas (la de vista, acercada a la cámara) y la prueba de profundidad ``LESS_EQUAL``
    sin escribir profundidad; el lote de ``gpu`` de cada uno se crea la primera vez. Deja el
    estado de ``gpu`` como estaba. Devuelve cuántos lotes dibujó."""
    shader = gpu.shader.from_builtin(SHADER)
    view = _pulled(view_matrix, perspective, view_distance)
    drawn = 0
    state = (gpu.state.depth_test_get(), gpu.state.depth_mask_get(), gpu.state.blend_get())
    with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
        gpu.matrix.load_projection_matrix(projection_matrix)
        gpu.matrix.load_matrix(view)
        gpu.state.depth_test_set("LESS_EQUAL")
        gpu.state.depth_mask_set(False)
        gpu.state.blend_set("ALPHA")
        try:
            for item in built.batches:
                lot = item.gpu_batch(shader)
                shader.uniform_float("viewportSize", tuple(viewport_size))
                shader.uniform_float("lineWidth", item.width_px * float(pixel_size))
                shader.uniform_float("color", tuple(item.color))
                lot.draw(shader)
                drawn += 1
        finally:
            gpu.state.depth_test_set(state[0])
            gpu.state.depth_mask_set(state[1])
            gpu.state.blend_set(state[2])
    return drawn


# --- Activar y quitar ---------------------------------------------------------------------------


class _State:
    """Lo de la sesión (no se guarda en el ``.blend``)."""

    def __init__(self) -> None:
        self.enabled = False
        self.handles: list[Any] = []
        self.built: Built | None = None
        self.steps: Generator[None, None, Built] | None = None
        self.request: Request | None = None
        self.undo: list[Callable[[], object]] = []
        self.failed = False


_STATE = _State()


def enabled() -> bool:
    """Si la superposición está activa (el control 30 pulsado)."""
    return _STATE.enabled


def drawing() -> bool:
    """Si el manejador de dibujo está puesto."""
    return bool(_STATE.handles)


def building() -> bool:
    """Si quedan pasos por dar para construirla."""
    return _STATE.steps is not None


def built() -> Built | None:
    """Lo último construido (se dibuja mientras se rehace); ``None`` si no hay."""
    return _STATE.built


def _measure(text: str) -> float:
    return float(blf.dimensions(FONT_ID, text)[0])


def _region_ready() -> tuple[Any, Any, Any] | None:
    """El espacio, la región y los datos de la vista que dibuja, o ``None`` si no hay o tiene las
    superposiciones apagadas."""
    context = bpy.context
    space, region, rv3d = context.space_data, context.region, context.region_data
    if space is None or region is None or rv3d is None or not space.overlay.show_overlays:
        return None
    return space, region, rv3d


def _fail(what: str) -> None:
    _STATE.failed = True
    LOGGER.exception("No se pueden dibujar %s de las restricciones: la superposición se apaga",
                     what)


def _draw_view() -> None:
    """El manejador ``POST_VIEW`` de cada Vista 3D: los lotes."""
    if _STATE.failed or _STATE.built is None:
        return
    try:
        ready = _region_ready()
        if ready is None:
            return
        _space, region, rv3d = ready
        if _STATE.built.batches:
            draw_lines(_STATE.built, view_matrix=gpu.matrix.get_model_view_matrix(),
                       projection_matrix=gpu.matrix.get_projection_matrix(),
                       perspective=bool(rv3d.is_perspective),
                       view_distance=float(rv3d.view_distance),
                       viewport_size=(float(region.width), float(region.height)),
                       pixel_size=float(bpy.context.preferences.system.pixel_size))
    except Exception:  # una traza por fotograma no ayuda a nadie
        _fail("las líneas")


def _draw_pixels() -> None:
    """El manejador ``POST_PIXEL`` de cada Vista 3D: los nombres y la leyenda."""
    if _STATE.failed or _STATE.built is None:
        return
    try:
        ready = _region_ready()
        if ready is None:
            return
        _space, region, rv3d = ready
        scale = float(bpy.context.preferences.system.ui_scale)
        size = (float(region.width), float(region.height))
        blf.size(FONT_ID, FONT_PX * scale)
        items = screen_items(_STATE.built, np.array(rv3d.perspective_matrix), size,
                             measure=_measure, scale=scale)
        if items:
            dh_overlay.paint(items, size, scale=scale)
    except Exception:  # una traza por fotograma no ayuda a nadie
        _fail("los nombres y la leyenda")


def _redraw() -> None:
    """Pide redibujar las Vistas 3D de todas las ventanas."""
    manager = getattr(bpy.context, "window_manager", None)
    for window in getattr(manager, "windows", ()):
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _chosen_surface() -> str:
    """La superficie elegida en la ventana Restricciones… (``""``: la más reciente)."""
    view = getattr(getattr(bpy.context, "window_manager", None), WINDOW_MANAGER_PROPERTY, None)
    return str(getattr(view, "overlay_surface", "") or "")


def _close_steps() -> None:
    steps, _STATE.steps = _STATE.steps, None
    if steps is not None:
        steps.close()


def rebuild(project: Any = None, version_uid: str | None = None) -> None:
    """Empieza a construir de nuevo lo que dibuja la superposición para la versión activa (o
    ``version_uid``) del proyecto de la sesión (o ``project``), y deja un temporizador que da los
    pasos (:func:`tick`); lo anterior se sigue dibujando hasta que acabe. Lo que se construía a
    mitad se cierra. Sin proyecto, no dibuja nada."""
    project = project or project_session.current()
    _close_steps()
    if project is None:
        _STATE.built = None
        return
    shown = scene_versions.active()
    uid = version_uid if version_uid is not None else (None if shown is None else shown.uid)
    code = "" if shown is None or shown.uid != uid else shown.code
    try:
        sealed = stamp(project, uid)
    except (GeoblenderError, sqlite3.Error, OSError):
        sealed = ("error",)
    request = Request(project, uid, code, _chosen_surface(), language(), sealed)
    _STATE.request = request
    _STATE.steps = build_steps(request)
    if not bpy.app.timers.is_registered(tick):
        bpy.app.timers.register(tick, first_interval=TICK_INTERVAL_S, persistent=True)


def tick() -> float | None:
    """El temporizador: da pasos de la construcción durante :data:`TICK_BUDGET_S` s como mucho;
    devuelve cuándo volver (``None``: acabó o no hay nada que construir). Si falla un paso (un error
    del programa: los pasos tratan los suyos), lo registra, avisa y quita la superposición."""
    steps = _STATE.steps
    if steps is None:
        return None
    started = time.perf_counter()
    try:
        while time.perf_counter() - started < TICK_BUDGET_S:
            next(steps)
    except StopIteration as done:
        if _STATE.steps is steps:
            _STATE.steps = None
            _STATE.built = done.value
            _redraw()
        return None
    except Exception as exc:  # noqa: BLE001 - lo dice el aviso y el registro
        LOGGER.exception("No se pudieron construir las restricciones y los límites")
        project_session.notify(tr("The constraints and limits could not be prepared: {detail}",
                                  detail=str(exc)))
        disable()
        return None
    return TICK_INTERVAL_S


def on_version_changed() -> None:
    """Lo que se apunta en ``bl.scene.versions``: con otra versión activa, la rehace."""
    if not _STATE.enabled:
        return
    shown = scene_versions.active()
    request = _STATE.request
    if request is None or request.version_uid != (None if shown is None else shown.uid):
        rebuild()


def on_project_read(project: Any) -> None:
    """Lo que se apunta en los indicadores de la procedencia (``add_change_listener``): si el
    proyecto cambió en algo que dibuja (:func:`stamp`), la rehace."""
    if not _STATE.enabled or project is not project_session.current():
        return
    request = _STATE.request
    try:
        changed = request is None or stamp(project, request.version_uid) != request.stamp
    except (GeoblenderError, sqlite3.Error, OSError):
        return
    if changed:
        rebuild(project)


def on_project_changed(project: Any) -> None:
    """Lo que se apunta en ``bl.scene.project_session``: cerrar el proyecto o abrir otro la
    quita."""
    request = _STATE.request
    if _STATE.enabled and (project is None or request is None or project is not request.project):
        disable()


def on_surface_changed() -> None:
    """Se eligió otra superficie en la ventana Restricciones…: la rehace."""
    if _STATE.enabled:
        rebuild()


def _listen() -> None:
    """Apunta lo que la rehace o la quita y cómo deshacerlo."""
    from ..ui import provenance, switcher  # al usarlo: bl.ui importa bl.draw

    scene_versions.add_listener(on_version_changed)
    provenance.add_change_listener(on_project_read)
    project_session.add_listener(on_project_changed)
    switcher.add_blender_hook(disable)
    _STATE.undo += [
        lambda: scene_versions.remove_listener(on_version_changed),
        lambda: provenance.remove_change_listener(on_project_read),
        lambda: project_session.remove_listener(on_project_changed),
        lambda: switcher.remove_blender_hook(disable),
    ]


def enable() -> None:
    """Activa la superposición: pone los manejadores de dibujo, apunta lo que la rehace o la quita
    y empieza a construirla (:func:`rebuild`). Ya activa, nada. Sin proyecto abierto,
    ``RuntimeError``."""
    if _STATE.enabled:
        return
    project = project_session.current()
    if project is None:
        raise RuntimeError("no hay un proyecto abierto: no hay restricciones que ver")
    _STATE.failed = False
    _STATE.enabled = True
    try:
        space = bpy.types.SpaceView3D
        _STATE.handles = [space.draw_handler_add(_draw_view, (), "WINDOW", "POST_VIEW"),
                          space.draw_handler_add(_draw_pixels, (), "WINDOW", "POST_PIXEL")]
        _listen()
        rebuild(project)
    except BaseException:
        disable()
        raise


def disable() -> None:
    """Quita la superposición: los manejadores de dibujo, los lotes, lo que se construía y lo
    que la rehacía. Ya quitada, nada."""
    was = _STATE.enabled
    _STATE.enabled = False
    _close_steps()
    if bpy.app.timers.is_registered(tick):
        bpy.app.timers.unregister(tick)
    handles, _STATE.handles = _STATE.handles, []
    for handle in handles:
        bpy.types.SpaceView3D.draw_handler_remove(handle, "WINDOW")
    while _STATE.undo:
        try:
            _STATE.undo.pop()()
        except Exception:  # noqa: BLE001 - se sigue quitando lo demás
            LOGGER.debug("No se pudo quitar una escucha de la superposición", exc_info=True)
    _STATE.built = None
    _STATE.request = None
    if was:
        _redraw()


def register() -> None:
    """Nada que poner: los manejadores solo están mientras la superposición está activa."""
    _STATE.failed = False


def unregister() -> None:
    """Quita la superposición si está activa (principio 8)."""
    disable()

