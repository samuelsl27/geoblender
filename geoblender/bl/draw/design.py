# SPDX-License-Identifier: GPL-3.0-or-later
"""La vista previa de semillas, dominios y restricciones en la Vista 3D (spec 013, T25; HU-013-1;
RF-013-03; RNF-013-05; plan 013 §5.5, D-29; comprobación manual M1).

Con la vista previa activa (``geoblender.des_toggle_preview``, ``WindowManager.geoblender_design_preview``),
la Vista 3D muestra, encima de la escena y **sin escribir nada en el proyecto** (ni objetos en la
escena: D-29), lo que va a usar un cálculo antes de lanzarlo:

- **las semillas**, un punto de :data:`SEED_PX` px por celda de semilla en su cota, **coloreadas por
  cota** (:func:`elevation_colors`: azul a rojo entre la más baja y la más alta); si pasan de
  :data:`MAX_SEED_POINTS` se aclaran (se dibuja una de cada ``stride``, y la leyenda lo dice);
- **el dominio de trabajo**, en trama (las rayas de ``bl.draw.constraints``: ``mask_hatch_steps``);
- **los sectores**, su borde en azul claro y **en ámbar si su búsqueda de intocables está pendiente**
  (lo que impide calcular, RF-013-05), con su nombre y su estado;
- **las zonas de las restricciones**, sus contornos, sus nombres y su leyenda: los de la superposición
  de la 012 (``bl.draw.constraints.build_steps``), con las máscaras y la superficie ya leídas;
- **el resumen** (``design.preview``: celdas y área de las semillas y del dominio, cotas, porcentaje
  del dominio con semilla, semillas fuera del dominio en ámbar, sectores que toca con su estado y
  estado de las máscaras) en la esquina de arriba a la izquierda, y también en la vista
  (``WindowManager.geoblender_design.preview``, :func:`bl.ui.des_panels.show_preview`).

Aquí **no se calcula nada de minería**: el resumen, las semillas, el dominio y los sectores son los de
``design.steps.preview_steps`` y de ``design.seeds``; este módulo los dibuja. Lo que se dibuja se
construye sin ``gpu`` y se prueba en sus lotes (:class:`Built`, :class:`Points`; ``docs/trampas.md``
§3: sin GPU en ``blender -b``).

**Con un diseño de la cantera con dos superficies** (spec 014, T23; RF-014-04; plan 014 §5.5; la
activa el botón «Vista previa» del diálogo de «Cantera con dos superficies…», T44): lo que
se previsualiza es un :class:`QuarryPlan` (la ``design.model.QuarryRequest`` y el ancho del anillo de
coronación: el pedido o el del parámetro ``des.quarry.crown_ring_cells`` de la versión,
:func:`crown_ring_cells`) y la vista previa enseña, sobre la superficie de partida y con las
restricciones y los sectores de siempre, lo que dice ``design.preview.quarry_summarize_steps``:

- **el recinto excavable**, su borde (:data:`AREA`, el trazo más grueso);
- **la coronación**, un punto por celda del anillo en su cota y **en el color de las semillas**
  (:func:`crown_points_steps`: la misma rampa por cota y el mismo aclarado);
- **las zonas a sostener** (intocables y sin corte), su borde (:data:`HOLD`);
- **los fondos**, el borde de cada uno y su nombre con su cota (:data:`FLOORS`);
- **las zonas a conservar** que siembran los techos de conservación, su borde, su trama y su nombre
  (:data:`CEILINGS`; el techo mismo es una envolvente y no se calcula en la vista previa);
- **los corredores**, el borde de cada uno y su nombre con sus cotas (:data:`CORRIDORS`);
- y **su leyenda**: una fila por pieza presente, antes de las de los sectores y de la 012.

Los bordes son los lados de celda entre celdas de valor distinto (:func:`edges_steps`), unidos en
tramos rectos y ajustados a la superficie como los contornos de la 012.

**Construcción por pasos** (:func:`build_steps`; RNF-013-05): nada se lee ni se calcula de una vez.
Un temporizador (:func:`tick`) avanza los pasos, de :data:`STEP_BUDGET_S` s como mucho cada uno; activar
la vista previa ocupa lo que cabe en el siguiente ciclo y no el hilo de Blender. Se **rehace**
(:func:`rebuild`) al cambiar la versión activa o lo que lee (:func:`stamp`, el de la 012), y se
**quita** (:func:`disable`) al pulsar el control otra vez, al cerrar o cambiar de proyecto, al
conmutar a la interfaz de Blender (``bl.ui.switcher.add_blender_hook``) y al desactivar Geoblender
(:func:`unregister`, principio 8). Un error al dibujar se registra una vez y deja de dibujar: nunca
una traza por fotograma. Las posiciones son locales respecto al GeoOrigin (float64 hasta el último
paso, ADR-0005).
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable, Generator, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

import blf
import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix

from ...core.errors import GeoblenderError
from ...core.georef import world_to_local
from ...core.i18n import format_number, language, tr
from ...core.params import PROJECT_SCOPE, VERSION_SCOPE, ParameterStore, definition
from ...design import messages as design_messages
from ...design import preview as design_preview
from ...design import steps as design_steps
from ...design.model import QuarryRequest, SeedKind, SeedSource, WorkDomain
from ...design.params import CROWN_RING, check_quarry_param
from ...gis.grid import Grid
from ...gis.masks import store as mask_store
from ...gis.masks.zones import Runs
from ..scene import project_session
from ..scene import versions as scene_versions
from . import constraints, dh_overlay
from .constraints import Batch, Label
from .dh_overlay import Box, LegendRow, Text

__all__ = [
    "AREA", "AREA_COLOR", "CEILINGS", "CEILING_COLOR", "CORRIDORS", "CORRIDOR_COLOR",
    "EDGE_ROWS_PER_STEP", "FLOORS", "FLOOR_COLOR", "HOLD", "HOLD_COLOR", "MAX_SEED_POINTS",
    "PENDING_COLOR", "RAMP", "SECTOR", "SECTOR_COLOR", "SECTOR_PENDING", "SEED_PX",
    "Built", "Plan", "Points", "QuarryPlan", "Request", "build_steps", "building", "built",
    "crown_points_steps", "crown_ring_cells", "default_plan", "disable", "draw_points", "drawing",
    "edges_steps", "elevation_colors", "enable", "enabled", "on_project_changed", "on_project_read",
    "on_version_changed", "plan", "rebuild", "register", "screen_items", "seed_points_steps", "stamp",
    "summary_items", "summary_lines", "tick", "toolbar_covered_px", "unregister", "wrap_text",
]

LOGGER = logging.getLogger("geoblender.bl.draw")

SECTOR = "sector"
"""El papel (y la clave) del lote del borde de los sectores con su búsqueda vigente."""
SECTOR_PENDING = "sector_pending"
"""El papel (y la clave) del lote del borde de los sectores con su búsqueda pendiente."""

STEP_BUDGET_S = constraints.STEP_BUDGET_S
"""Lo que dura como mucho cada paso de la construcción (ninguna llamada de más de 0,2 s)."""
TICK_BUDGET_S = constraints.TICK_BUDGET_S
TICK_INTERVAL_S = constraints.TICK_INTERVAL_S
"""Lo que avanza como mucho cada llamada del temporizador y la espera entre dos."""
MAX_SEED_POINTS = 150_000
"""Los puntos de semilla que se dibujan como mucho (RNF-013-05 mide 100.000); con más, se aclaran."""
SEED_PX = 4.0
"""El tamaño (px) de cada punto de semilla (plan 013 D-29)."""
SEED_ROWS_PER_STEP = 128
"""Las filas de la rejilla de semillas que se leen en cada unidad."""
SECTOR_PX = 2.5
SECTOR_PENDING_PX = 3.5
"""El trazo (px) del borde de un sector con la búsqueda vigente y con ella pendiente."""
SECTOR_COLOR = (0.40, 0.80, 1.0, 1.0)
PENDING_COLOR = dh_overlay.STALE_COLOR
"""El color del borde de un sector con la búsqueda vigente (azul claro) y pendiente (ámbar)."""
ALERT_COLOR = dh_overlay.STALE_COLOR
TEXT_COLOR = (1.0, 1.0, 1.0, 1.0)
"""El color de las líneas del resumen: las de aviso, en ámbar."""
RAMP: tuple[tuple[float, tuple[float, float, float]], ...] = (
    (0.00, (0.15, 0.25, 0.85)),
    (0.25, (0.10, 0.70, 0.90)),
    (0.50, (0.20, 0.80, 0.30)),
    (0.75, (0.95, 0.85, 0.15)),
    (1.00, (0.90, 0.20, 0.15)),
)
"""La rampa de color de las semillas: la parada (0 a 1, de la cota más baja a la más alta) y su RGB."""
POINT_SHADER = "POINT_FLAT_COLOR"
"""El *shader* de los puntos de semilla: posición y color por vértice, con el tamaño del estado."""
SUMMARY_TOP_PX = 72.0
"""Lo que queda de espacio por arriba para los textos propios de Blender en la Vista 3D."""
SUMMARY_WIDTH_FRACTION = 0.6
"""Lo que ocupa como mucho el resumen del ancho de la región."""

# La cantera con dos superficies (spec 014, T23; RF-014-04).
AREA = "excavation_area"
HOLD = "hold"
FLOORS = "floors"
CEILINGS = "ceilings"
CORRIDORS = "corridors"
"""Las claves de los lotes de la cantera: el recinto excavable, las zonas a sostener, los fondos, las
zonas a conservar que siembran los techos y los corredores. Su borde lleva el papel
``constraints.OUTLINE``; la trama de las zonas a conservar, ``constraints.ZONE``."""
AREA_COLOR = (1.0, 1.0, 1.0, 1.0)
HOLD_COLOR = (1.0, 0.40, 0.80, 1.0)
FLOOR_COLOR = (0.20, 1.00, 0.60, 1.0)
CEILING_COLOR = (0.75, 0.55, 1.0, 1.0)
CORRIDOR_COLOR = (1.0, 1.0, 0.30, 1.0)
"""El color del borde (y del nombre) del recinto (blanco), de las zonas a sostener (rosa), de los
fondos (verde menta), de las zonas a conservar (lila) y de los corredores (amarillo)."""
AREA_PX = 3.5
PIECE_PX = 2.5
"""El trazo (px) del borde del recinto y del de las demás piezas de la cantera."""
CEILING_LINES = constraints.ZONE_LINES
"""Las rayas de la trama de las zonas a conservar, a lo largo de toda la rejilla."""
EDGE_ROWS_PER_STEP = 256
"""Las filas de una rejilla cuyo borde se busca en cada unidad (:func:`edges_steps`)."""

type Color = tuple[float, float, float, float]


# --- Los datos de lo que se dibuja ---------------------------------------------------------------


@dataclass(frozen=True)
class Plan:
    """Lo que se previsualiza: las semillas y el acotado del dominio de trabajo (como las pide el
    cálculo, ``design.model``); cumple ``design.seeds.SeedPlan``."""

    seeds: SeedSource
    domain: WorkDomain = field(default_factory=WorkDomain)


@dataclass(frozen=True)
class QuarryPlan:
    """Lo que se previsualiza de un diseño de la cantera con dos superficies (spec 014, RF-014-04):
    su ``request`` (``design.model.QuarryRequest``: la superficie de partida y las capas de los
    fondos, las zonas a conservar y los corredores) y el ancho del anillo de coronación en celdas
    (``ring_cells``; ``None``: el del parámetro ``des.quarry.crown_ring_cells`` de la versión
    activa, como lo leerá la operación, :func:`crown_ring_cells`)."""

    request: QuarryRequest
    ring_cells: int | None = None


@dataclass(frozen=True, eq=False)
class Points:
    """Un lote de puntos: ``positions`` (float32 ``(n, 3)``, locales respecto al GeoOrigin) y su
    ``colors`` (float32 ``(n, 4)``, por cota), de ``size_px`` px; ``total`` son las semillas del
    conjunto y ``stride``, 1 si se dibujan todas o de cuántas en cuántas si se aclararon. El lote de
    ``gpu`` se crea al dibujarlo la primera vez."""

    positions: np.ndarray = field(repr=False)
    colors: np.ndarray = field(repr=False)
    size_px: float
    total: int
    stride: int
    low: float
    high: float
    _gpu: list[Any] = field(default_factory=list, repr=False)

    @property
    def count(self) -> int:
        """Cuántos puntos se dibujan."""
        return int(len(self.positions))

    def gpu_batch(self, shader: Any) -> Any:
        """El lote de ``gpu`` de sus puntos (se crea la primera vez y se guarda)."""
        if not self._gpu:
            self._gpu.append(batch_for_shader(
                shader, "POINTS", {"pos": self.positions, "color": self.colors}))
        return self._gpu[0]


@dataclass(frozen=True, eq=False)
class Built:
    """Lo construido para una versión: ``lines`` (los lotes de segmentos, los nombres y la leyenda,
    como los de la 012: ``bl.draw.constraints.Built``), las semillas en ``seeds`` (``None`` sin
    ellas), los ``sectors`` dibujados (nombre y si su búsqueda está pendiente) y el ``summary``
    (cada línea ya traducida y si va en alerta)."""

    lines: constraints.Built
    seeds: Points | None
    sectors: tuple[tuple[str, bool], ...]
    summary: tuple[tuple[str, bool], ...]

    @property
    def stamp(self) -> tuple[Any, ...]:
        """El sello con que se construyó (:func:`stamp`)."""
        return self.lines.stamp


@dataclass(frozen=True, eq=False)
class Request:
    """Lo que se construye: el proyecto, la versión (``None``: ninguna) y su código, lo que se
    previsualiza (las semillas de la 013 o un diseño de la cantera de la 014), el idioma de los
    textos y el sello de lo que se lee."""

    project: Any
    version_uid: str | None
    version_code: str
    plan: Plan | QuarryPlan
    language: str
    stamp: tuple[Any, ...]


# --- Funciones puras (sin gpu) -------------------------------------------------------------------


def elevation_colors(values: np.ndarray | Sequence[float], low: float, high: float) -> np.ndarray:
    """El color RGBA (float32 ``(n, 4)``, opaco) de cada cota de ``values`` en la rampa :data:`RAMP`
    entre ``low`` (el primer color) y ``high`` (el último); fuera de ellas, el del extremo. Con
    ``low`` igual a ``high``, todas del color del medio."""
    found = np.asarray(values, dtype=np.float64).reshape(-1)
    span = float(high) - float(low)
    if span > 0.0:
        fraction = np.clip((found - float(low)) / span, 0.0, 1.0)
    else:
        fraction = np.full(found.shape, 0.5)
    stops = np.array([stop for stop, _color in RAMP], dtype=np.float64)
    rgb = np.array([color for _stop, color in RAMP], dtype=np.float64)
    colors = np.empty((len(found), 4), dtype=np.float32)
    for channel in range(3):
        colors[:, channel] = np.interp(fraction, stops, rgb[:, channel])
    colors[:, 3] = 1.0
    return colors


def _hex(color: Sequence[float]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(round(float(part) * 255.0) for part in color[:3]))


def wrap_text(text: str, measure: Callable[[str], float], width_px: float) -> list[str]:
    """``text`` partido por palabras en líneas de ``width_px`` px como mucho (``measure`` da el
    ancho de un texto); una palabra más ancha que la línea queda sola en la suya."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = word if not current else f"{current} {word}"
        if current and float(measure(candidate)) > width_px:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current or not lines:
        lines.append(current)
    return lines


def summary_lines(summary: Any, shown: str) -> tuple[tuple[str, bool], ...]:
    """Lo que dice la vista previa (``design.preview.PreviewSummary``) en el idioma ``shown``, línea
    a línea con si va en alerta (los avisos); el texto es el de ``design``."""
    return tuple((notice.text(shown), notice.severity == "warning") for notice in summary.notices)


def _ring_segments(rings: Sequence[np.ndarray]) -> np.ndarray:
    """Los lados ``(k, 2, 2)`` absolutos de unos anillos (cerrados si no lo estaban)."""
    pieces: list[np.ndarray] = []
    for ring in rings:
        points = np.asarray(ring, dtype=np.float64).reshape(-1, 2)
        if len(points) < 2:
            continue
        if not np.array_equal(points[0], points[-1]):
            points = np.vstack([points, points[:1]])
        pieces.append(np.stack([points[:-1], points[1:]], axis=1))
    return np.concatenate(pieces) if pieces else np.empty((0, 2, 2), dtype=np.float64)


def _ring_center(rings: Sequence[np.ndarray]) -> tuple[float, float] | None:
    """El centro de la caja del primer anillo (absoluto), o ``None`` sin anillos."""
    for ring in rings:
        points = np.asarray(ring, dtype=np.float64).reshape(-1, 2)
        if len(points):
            low, high = points.min(axis=0), points.max(axis=0)
            return (float((low[0] + high[0]) / 2.0), float((low[1] + high[1]) / 2.0))
    return None


def _chosen_surface(source: SeedSource) -> str:
    """La superficie sobre la que se dibuja: la de las semillas (o su rejilla de cotas); sin ella
    (una cota fija), la más reciente del proyecto (``""``)."""
    kind = SeedKind(source.kind)
    if kind is SeedKind.SURFACE:
        return str(source.surface or "")
    if kind is SeedKind.GRID:
        return str(source.grid or "")
    return ""


# --- Construir -----------------------------------------------------------------------------------


def seed_points_steps(seeds: Any, origin: Any, *, budget_s: float = STEP_BUDGET_S
                      ) -> Generator[None, None, Points | None]:
    """Los puntos de las semillas de ``seeds`` (``design.seeds.SeedSet``): uno por celda con cota
    finita, en su cota y coloreado por ella entre la mínima y la máxima de las semillas; con más de
    :data:`MAX_SEED_POINTS`, uno de cada ``stride`` en el orden de la rejilla. Se lee por trozos de
    :data:`SEED_ROWS_PER_STEP` filas; sin semillas, ``None``. El resultado es el
    ``StopIteration.value``."""
    total = int(seeds.cells)
    if total == 0 or seeds.min_m is None or seeds.max_m is None:
        return None
    return (yield from _points_steps(seeds.grid, seeds.geometry, total, float(seeds.min_m),
                                     float(seeds.max_m), origin, budget_s))


def crown_points_steps(start: np.ndarray, crown: np.ndarray, grid: Grid, origin: Any, *,
                       budget_s: float = STEP_BUDGET_S) -> Generator[None, None, Points | None]:
    """Los puntos de la coronación de la cantera (spec 014, RF-014-04; plan 014 §5.5: «en el color
    de las semillas»): uno por celda de ``crown`` (booleana, de la rejilla ``grid``) en su cota de la
    superficie de partida ``start`` (m, float64) y coloreado por ella entre la mínima y la máxima de
    la coronación, como :func:`seed_points_steps` (con el mismo aclarado). Sin coronación o sin cota
    en ella, ``None``. El resultado es el ``StopIteration.value``."""
    chosen = np.asarray(crown, dtype=bool) & np.isfinite(start)
    total = int(np.count_nonzero(chosen))
    if total == 0:
        return None
    heights = start[chosen]
    values = np.where(chosen, start, np.nan)
    yield
    return (yield from _points_steps(values, grid, total, float(heights.min()),
                                     float(heights.max()), origin, budget_s))


def _points_steps(values: np.ndarray, grid: Grid, total: int, low: float, high: float,
                  origin: Any, budget_s: float) -> Generator[None, None, Points | None]:
    """Los puntos de las ``total`` celdas con cota finita de ``values`` (de la rejilla ``grid``) en
    su cota, coloreados entre ``low`` y ``high``; con más de :data:`MAX_SEED_POINTS`, uno de cada
    ``stride`` en el orden de la rejilla, leídos por trozos de :data:`SEED_ROWS_PER_STEP` filas."""
    stride = max(1, -(-total // max(1, MAX_SEED_POINTS)))
    pace = constraints.Pace(budget_s)
    places: list[np.ndarray] = []
    heights: list[np.ndarray] = []
    seen = 0
    for top in range(0, grid.nrows, SEED_ROWS_PER_STEP):
        band = values[top:top + SEED_ROWS_PER_STEP]
        row, col = np.nonzero(np.isfinite(band))
        if len(row):
            keep = (seen + np.arange(len(row))) % stride == 0
            seen += len(row)
            row, col = row[keep] + top, col[keep]
            z = values[row, col]
            xyz = np.empty((len(row), 3), dtype=np.float64)
            xyz[:, 0] = grid.west + (col + 0.5) * grid.dx
            xyz[:, 1] = grid.north - (row + 0.5) * grid.dy
            xyz[:, 2] = z
            places.append(world_to_local(xyz, origin).astype(np.float32))
            heights.append(z)
        if pace.due():
            yield
    if not places:
        return None
    positions = np.concatenate(places)
    colors = elevation_colors(np.concatenate(heights), low, high)
    return Points(positions, colors, SEED_PX, total, stride, float(low), float(high))


def _sector_steps(project: Any, masks: Any, ground: Any, origin: Any, *, budget_s: float
                  ) -> Generator[None, None, tuple[tuple[Batch, ...], tuple[Label, ...],
                                                   tuple[tuple[str, bool], ...]]]:
    """El borde de los sectores de búsqueda de la versión de ``masks`` (los declarados o el
    perímetro de actuación): un lote para los de búsqueda vigente y otro, ámbar, para los pendientes
    (``masks.pending_sectors``), y el nombre de cada uno junto a su centro con su estado."""
    with project.read() as conn:
        found = tuple(sector for sector, _source in
                      mask_store.search_sectors(conn, project, masks.version_uid))
    yield
    plain: list[np.ndarray] = []
    late: list[np.ndarray] = []
    named: list[tuple[str, bool, tuple[float, float]]] = []
    for sector in found:
        pending = sector.code in masks.pending_sectors
        (late if pending else plain).append(_ring_segments(sector.rings))
        center = _ring_center(sector.rings)
        if center is not None:
            named.append((sector.name, pending, center))
    batches: list[Batch] = []
    for role, pieces, color, width in ((SECTOR, plain, SECTOR_COLOR, SECTOR_PX),
                                       (SECTOR_PENDING, late, PENDING_COLOR, SECTOR_PENDING_PX)):
        drawn = [piece for piece in pieces if len(piece)]
        if drawn:
            positions = yield from constraints.drape_segments_steps(
                np.concatenate(drawn), ground, origin, budget_s=budget_s)
            batches.append(Batch(role, role, color, width, positions))
    places = np.array([center for _name, _pending, center in named],
                      dtype=np.float64).reshape(-1, 2)
    spots = yield from constraints.drape_points_steps(places, ground, origin, budget_s=budget_s)
    labels = tuple(
        Label(tr("{name} · {state}", name=name,
                 state=tr("Search pending") if pending else tr("Search in force")),
              (float(x), float(y), float(z)), PENDING_COLOR if pending else SECTOR_COLOR)
        for (name, pending, _center), (x, y, z) in zip(named, spots.tolist(), strict=True))
    return tuple(batches), labels, tuple((name, pending) for name, pending, _center in named)


def _legend(request: Request, base: constraints.Built, points: Points | None, has_domain: bool,
            sectors: Sequence[tuple[str, bool]]) -> tuple[LegendRow, ...]:
    """La leyenda: el título con la versión, las cotas de las semillas con su color, el dominio de
    trabajo, los sectores (vigente y pendiente) y lo de la 012 (tipos presentes y notas) sin su
    título ni su dominio por defecto y su franja, que aquí son el dominio de trabajo. Las semillas
    llevan una fila por cota, la baja con el primer color de la rampa y la alta con el último; con
    todas a la misma cota, una sola con el color con que :func:`elevation_colors` las pinta."""
    rows = [LegendRow(tr("Preview · {version}", version=request.version_code or tr("No version")))]
    if points is not None:
        if points.high - points.low > 0.0:  # la misma condición que la rampa de elevation_colors
            heights = ((points.low, RAMP[0][1]), (points.high, RAMP[-1][1]))
        else:
            heights = ((points.low, elevation_colors([points.low], points.low, points.high)[0]),)
        for value, color in heights:
            rows.append(LegendRow(tr("Seeds at {value} m", value=format_number(value, 1)),
                                  _hex(color)))
        if points.stride > 1:
            rows.append(LegendRow(tr("Seeds thinned: 1 of every {stride} is drawn",
                                     stride=points.stride)))
    if has_domain:
        rows.append(LegendRow(tr("Work domain"), _hex(constraints.DOMAIN_COLOR)))
    rows.extend(_sector_rows(sectors))
    rows.extend(_base_rows(base))
    return tuple(rows)


def _sector_rows(sectors: Sequence[tuple[str, bool]]) -> list[LegendRow]:
    """Las filas de la leyenda de los sectores dibujados: con la búsqueda vigente y pendiente."""
    rows = []
    if any(not pending for _name, pending in sectors):
        rows.append(LegendRow(tr("Sector with its search in force"), _hex(SECTOR_COLOR)))
    if any(pending for _name, pending in sectors):
        rows.append(LegendRow(tr("Sector with its search pending"), _hex(PENDING_COLOR)))
    return rows


def _base_rows(base: constraints.Built) -> list[LegendRow]:
    """Las filas de la leyenda de la 012 (tipos presentes y notas) sin su título ni su dominio por
    defecto y su franja, que la vista previa no dibuja."""
    skipped = {tr("Default domain"), tr("Fill-only strip")}
    return [row for row in base.legend[1:] if row.text not in skipped]


# --- La cantera con dos superficies (spec 014, T23; RF-014-04) -----------------------------------


def edges_steps(values: np.ndarray, grid: Grid, *, budget_s: float = STEP_BUDGET_S
                ) -> Generator[None, None, np.ndarray]:
    """El borde de las celdas de ``values`` (de la forma de ``grid``; booleana o de enteros, con
    ``False`` o 0 en las celdas de nada): los lados de celda entre dos celdas de valor distinto, o
    entre una con valor y el borde de la rejilla, como segmentos ``(k, 2, 2)`` absolutos unidos en
    tramos rectos por fila y por columna dentro de cada banda de :data:`EDGE_ROWS_PER_STEP` filas.
    Así, el borde de una máscara es su contorno y el de una rejilla de dueños (los fondos o los
    corredores, numerados de 1 a n), el de cada uno, también entre dos vecinos. Sin celdas, ninguno.
    Se busca por bandas; el resultado es el ``StopIteration.value``."""
    found = np.asarray(values)
    if found.shape != grid.shape:
        raise ValueError(f"los valores son de forma {found.shape}, no de la rejilla {grid.shape}")
    pace = constraints.Pace(budget_s)
    nrows, ncols = found.shape
    blank = np.zeros((1, ncols), dtype=found.dtype)
    parts: list[np.ndarray] = []
    for top in range(0, nrows, max(1, int(EDGE_ROWS_PER_STEP))):
        band = found[top:top + max(1, int(EDGE_ROWS_PER_STEP))]
        last = top + len(band) == nrows
        stacked = np.concatenate([found[top - 1:top] if top else blank, band,
                                  *((blank,) if last else ())])
        across = Runs.from_mask(stacked[:-1] != stacked[1:])  # el lado de arriba de la fila top + i
        if len(across):
            pieces = np.empty((len(across), 2, 2), dtype=np.float64)
            pieces[:, 0, 0] = grid.west + across.col0 * grid.dx
            pieces[:, 1, 0] = grid.west + across.col1 * grid.dx
            pieces[:, :, 1] = (grid.north - (top + across.row) * grid.dy)[:, None]
            parts.append(pieces)
        padded = np.zeros((len(band), ncols + 2), dtype=found.dtype)
        padded[:, 1:-1] = band
        down = Runs.from_mask((padded[:, :-1] != padded[:, 1:]).T)  # el lado izquierdo de cada columna
        if len(down):
            pieces = np.empty((len(down), 2, 2), dtype=np.float64)
            pieces[:, :, 0] = (grid.west + down.row * grid.dx)[:, None]
            pieces[:, 0, 1] = grid.north - (top + down.col0) * grid.dy
            pieces[:, 1, 1] = grid.north - (top + down.col1) * grid.dy
            parts.append(pieces)
        if pace.due():
            yield
    return np.concatenate(parts) if parts else np.empty((0, 2, 2), dtype=np.float64)


@dataclass(frozen=True, eq=False)
class _Owned:
    """Lo de cada dueño de una rejilla de dueños (1 a n): sus celdas, el centro de ellas
    (absoluto; ``NaN`` sin celdas) y la cota mínima y máxima de sus celdas (``NaN`` sin cotas)."""

    cells: np.ndarray
    centers: np.ndarray
    low: np.ndarray
    high: np.ndarray


def _owned_steps(owner: np.ndarray, count: int, grid: Grid, levels: np.ndarray | None,
                 pace: Any) -> Generator[None, None, _Owned]:
    """Las celdas, el centro (la media de los centros de celda) y, con ``levels``, la cota mínima y
    máxima de cada dueño ``1 … count`` de ``owner`` (0: nadie), por bandas de filas."""
    cells = np.zeros(count + 1, dtype=np.int64)
    rows = np.zeros(count + 1, dtype=np.float64)
    cols = np.zeros(count + 1, dtype=np.float64)
    low = np.full(count + 1, np.inf)
    high = np.full(count + 1, -np.inf)
    step = max(1, int(EDGE_ROWS_PER_STEP))
    for top in range(0, owner.shape[0], step):
        band = owner[top:top + step]
        row, col = np.nonzero(band)
        ids = band[row, col].astype(np.int64)
        cells += np.bincount(ids, minlength=count + 1)[:count + 1]
        rows += np.bincount(ids, weights=(row + top).astype(np.float64),
                            minlength=count + 1)[:count + 1]
        cols += np.bincount(ids, weights=col.astype(np.float64), minlength=count + 1)[:count + 1]
        if levels is not None and len(ids):
            heights = levels[top:top + step][row, col]
            np.minimum.at(low, ids, heights)
            np.maximum.at(high, ids, heights)
        if pace.due():
            yield
    with np.errstate(invalid="ignore", divide="ignore"):
        centers = np.column_stack([grid.west + (cols / cells + 0.5) * grid.dx,
                                   grid.north - (rows / cells + 0.5) * grid.dy])
    low[~np.isfinite(low)] = np.nan
    high[~np.isfinite(high)] = np.nan
    return _Owned(cells[1:], centers[1:], low[1:], high[1:])


def crown_ring_cells(project: Any, version_uid: str) -> int:
    """El ancho del anillo de coronación (``des.quarry.crown_ring_cells``) en la versión
    ``version_uid``, como lo leerá la cantera: el de la versión, el del proyecto o, sin fila, el de
    su definición; fuera de su rango o sin valor, ``DesignError`` (``check_quarry_param``). Solo
    lee."""
    with project.read() as conn:
        found = ParameterStore(project).resolve_many(
            conn, (CROWN_RING,), (VERSION_SCOPE, PROJECT_SCOPE), version=version_uid)
    resolved = found.get(CROWN_RING)
    if resolved is not None:
        value = resolved.value
    else:
        declared = definition(CROWN_RING)
        value = None if declared is None else declared.default
    return int(check_quarry_param(CROWN_RING, value))  # type: ignore[arg-type]


def _number_text(value: float) -> str:
    """Una cota de un fondo o de un corredor para su nombre: con dos decimales."""
    return format_number(float(value), 2)


def _outline_steps(key: str, values: np.ndarray, grid: Grid, color: Color, width: float,
                   ground: Any, origin: Any, budget_s: float
                   ) -> Generator[None, None, Batch | None]:
    """El lote del borde (``constraints.OUTLINE``) de las celdas de ``values`` sobre ``ground``;
    ``None`` si no tiene ninguna."""
    segments = yield from edges_steps(values, grid, budget_s=budget_s)
    if not len(segments):
        return None
    positions = yield from constraints.drape_segments_steps(segments, ground, origin,
                                                           budget_s=budget_s)
    return Batch(key, constraints.OUTLINE, color, width, positions)


@dataclass(frozen=True, eq=False)
class _Pieces:
    """Lo construido de las piezas de la cantera: los lotes (los de debajo primero), los nombres
    (absolutos, aún sin cota), las filas de su leyenda y los puntos de la coronación."""

    batches: tuple[Batch, ...]
    named: tuple[tuple[str, tuple[float, float], Color], ...]
    rows: tuple[LegendRow, ...]
    crown: Points | None


def _quarry_pieces_steps(found: Any, ground: Any, origin: Any, *, budget_s: float
                         ) -> Generator[None, None, _Pieces]:
    """Los lotes, los nombres y la leyenda de las piezas de ``found``
    (``design.preview.QuarryPreview`` con las máscaras al día): el borde del recinto, el de las
    zonas a sostener, el de cada fondo con su cota, el de las zonas a conservar con su trama y su
    nombre, el de cada corredor con sus cotas y los puntos de la coronación."""
    grid = found.masks.grid
    pace = constraints.Pace(budget_s)
    batches: list[Batch] = []
    named: list[tuple[str, tuple[float, float], Color]] = []
    rows: list[LegendRow] = []
    crown = yield from crown_points_steps(found.start, found.crown, grid, origin, budget_s=budget_s)
    if crown is not None:
        if crown.high - crown.low > 0.0:  # como las semillas: una fila por cota extrema
            heights = ((crown.low, RAMP[0][1]), (crown.high, RAMP[-1][1]))
        else:
            heights = ((crown.low, elevation_colors([crown.low], crown.low, crown.high)[0]),)
        for value, color in heights:
            rows.append(LegendRow(tr("Crown at {value} m", value=format_number(value, 1)),
                                  _hex(color)))
    if found.conserve:
        union = np.zeros(grid.shape, dtype=bool)
        for zone in found.conserve:
            union |= zone.mask
        segments = yield from constraints.mask_hatch_steps(union, grid, CEILING_LINES,
                                                           budget_s=budget_s)
        if len(segments):
            positions = yield from constraints.drape_segments_steps(segments, ground, origin,
                                                                   budget_s=budget_s)
            batches.append(Batch(CEILINGS, constraints.ZONE, (*CEILING_COLOR[:3],
                                                              constraints.HATCH_ALPHA),
                                 constraints.HATCH_PX, positions))
    hold = yield from _outline_steps(HOLD, found.hold, grid, HOLD_COLOR, PIECE_PX, ground, origin,
                                     budget_s)
    area = yield from _outline_steps(AREA, found.area, grid, AREA_COLOR, AREA_PX, ground, origin,
                                     budget_s)
    rows.append(LegendRow(tr("Excavation boundary"), _hex(AREA_COLOR)))
    if hold is not None:
        batches.append(hold)
        rows.append(LegendRow(tr("Zones to hold"), _hex(HOLD_COLOR)))
    floors = found.floors
    if floors is not None and floors.fids:
        batch = yield from _outline_steps(FLOORS, floors.owner, grid, FLOOR_COLOR, PIECE_PX, ground,
                                          origin, budget_s)
        owned = yield from _owned_steps(floors.owner, len(floors.fids), grid, None, pace)
        if batch is not None:
            batches.append(batch)
        named.extend((tr("Floor at {level} m", level=_number_text(level)), (float(x), float(y)),
                      FLOOR_COLOR)
                     for level, cells, (x, y) in zip(floors.levels, owned.cells.tolist(),
                                                     owned.centers.tolist(), strict=True) if cells)
        rows.append(LegendRow(tr("Floors of «{layer}» ({count})", layer=floors.layer,
                                 count=len(floors.fids)), _hex(FLOOR_COLOR)))
    if found.conserve:
        pieces = []
        for zone in found.conserve:
            segments = yield from edges_steps(zone.mask, grid, budget_s=budget_s)
            pieces.append(segments)
            owned = yield from _owned_steps(zone.mask.astype(np.int8), 1, grid, None, pace)
            if owned.cells[0]:
                x, y = owned.centers[0].tolist()
                named.append((tr("Zone to conserve «{name}»", name=zone.name), (x, y),
                              CEILING_COLOR))
        segments = np.concatenate(pieces)
        if len(segments):
            positions = yield from constraints.drape_segments_steps(segments, ground, origin,
                                                                   budget_s=budget_s)
            batches.append(Batch(CEILINGS, constraints.OUTLINE, CEILING_COLOR, PIECE_PX, positions))
        rows.append(LegendRow(tr("Zones to conserve: conservation ceilings ({count})",
                                 count=len(found.conserve)), _hex(CEILING_COLOR)))
    corridors = None if found.corridors is None else found.corridors.floors
    if corridors is not None and corridors.fids:
        batch = yield from _outline_steps(CORRIDORS, corridors.owner, grid, CORRIDOR_COLOR, PIECE_PX,
                                          ground, origin, budget_s)
        owned = yield from _owned_steps(corridors.owner, len(corridors.fids), grid, corridors.grid,
                                        pace)
        if batch is not None:
            batches.append(batch)
        for fid, cells, (x, y), low, high in zip(corridors.fids, owned.cells.tolist(),
                                                 owned.centers.tolist(), owned.low.tolist(),
                                                 owned.high.tolist(), strict=True):
            if not cells:
                continue
            if _number_text(low) == _number_text(high):
                text = tr("Corridor {corridor} at {level} m", corridor=fid,
                          level=_number_text(low))
            else:
                text = tr("Corridor {corridor}: {low} to {high} m", corridor=fid,
                          low=_number_text(low), high=_number_text(high))
            named.append((text, (float(x), float(y)), CORRIDOR_COLOR))
        rows.append(LegendRow(tr("Corridors of «{layer}» ({count})", layer=corridors.layer,
                                 count=len(corridors.fids)), _hex(CORRIDOR_COLOR)))
    if area is not None:
        batches.append(area)
    if crown is not None and crown.stride > 1:
        rows.append(LegendRow(tr("Seeds thinned: 1 of every {stride} is drawn",
                                 stride=crown.stride)))
    return _Pieces(tuple(batches), tuple(named), tuple(rows), crown)


def _quarry_build_steps(request: Request, plan_: QuarryPlan, *, budget_s: float
                        ) -> Generator[None, None, Built]:
    """Los pasos de :func:`build_steps` con un diseño de la cantera (``plan_``): el resumen y las
    piezas (``design.preview.quarry_summarize_steps``: solo lee y no compila las máscaras), la
    superficie de partida, las restricciones con su leyenda (``bl.draw.constraints``, con las
    máscaras ya leídas), las piezas con sus nombres y su leyenda y el borde de los sectores. Sin
    versión activa o sin las máscaras al día, solo las restricciones (y el resumen lo dice)."""
    project, version_uid, shown = request.project, request.version_uid, request.language
    origin = project.origin
    found = None
    if version_uid:
        ring = (plan_.ring_cells if plan_.ring_cells is not None
                else crown_ring_cells(project, version_uid))
        yield
        steps = design_preview.quarry_summarize_steps(project, plan_.request, version_uid,
                                                      ring_cells=ring, budget_s=budget_s)
        try:
            for step in steps:
                if step.result is not None:
                    found = step.result
                yield
        finally:
            close = getattr(steps, "close", None)
            if close is not None:
                close()
    masks = None if found is None else found.masks
    chosen = plan_.request.start
    ground = yield from constraints.ground_steps(project, chosen, version_uid, budget_s=budget_s)
    base = yield from constraints.build_steps(
        constraints.Request(project, version_uid, request.version_code, chosen, shown,
                            request.stamp),
        budget_s=budget_s, loaded=masks, ground=ground)
    batches = [batch for batch in base.batches
               if batch.role not in (constraints.DOMAIN, constraints.STRIP)]
    labels: list[Label] = []
    rows = [LegendRow(tr("Preview · {version}", version=request.version_code or tr("No version")))]
    crown = None
    sectors: tuple[tuple[str, bool], ...] = ()
    if masks is not None and found.area is not None:
        pieces = yield from _quarry_pieces_steps(found, ground, origin, budget_s=budget_s)
        batches.extend(pieces.batches)
        places = np.array([place for _text, place, _color in pieces.named],
                          dtype=np.float64).reshape(-1, 2)
        spots = yield from constraints.drape_points_steps(places, ground, origin,
                                                          budget_s=budget_s)
        labels.extend(Label(text, (float(x), float(y), float(z)), color)
                      for (text, _place, color), (x, y, z) in zip(pieces.named, spots.tolist(),
                                                                  strict=True))
        rows.extend(pieces.rows)
        crown = pieces.crown
        sector_batches, sector_labels, sectors = yield from _sector_steps(
            project, masks, ground, origin, budget_s=budget_s)
        batches.extend(sector_batches)
        labels.extend(sector_labels)
    rows.extend(_sector_rows(sectors))
    rows.extend(_base_rows(base))
    lines = replace(base, batches=tuple(batches), labels=(*base.labels, *labels),
                    legend=tuple(rows), stamp=request.stamp)
    return Built(lines, crown, sectors, () if found is None else summary_lines(found, shown))


def build_steps(request: Request, *, budget_s: float = STEP_BUDGET_S
                ) -> Generator[None, None, Built]:
    """Los pasos que construyen lo que dibuja la vista previa para ``request`` (véase el módulo):
    el resumen y las semillas con su dominio (``design.steps.preview_steps``: solo lee y no
    compila las máscaras), la superficie, las restricciones con su leyenda (``bl.draw.constraints``,
    con las máscaras ya leídas), el dominio de trabajo en trama, el borde de los sectores y los
    puntos de las semillas. Cada paso dura como mucho ``budget_s`` s (salvo una lectura, nunca de
    más de 0,2 s); el resultado es el ``StopIteration.value``. Los rechazos del cálculo (una
    superficie que no está, una zona desconocida…) salen al avanzar. Cerrarlo a mitad no deja nada.
    Sin versión activa no hay semillas ni dominio: solo las restricciones. Con un diseño de la
    cantera (:class:`QuarryPlan`), sus piezas en lugar de las semillas y el dominio (véase el
    módulo; spec 014, RF-014-04)."""
    if isinstance(request.plan, QuarryPlan):
        return (yield from _quarry_build_steps(request, request.plan, budget_s=budget_s))
    project, version_uid, shown = request.project, request.version_uid, request.language
    origin = project.origin
    found = None
    if version_uid:
        steps = design_steps.preview_steps(project, request.plan, version_uid, budget_s=budget_s)
        try:
            for step in steps:
                if step.result is not None:
                    found = step.result
                yield
        finally:
            close = getattr(steps, "close", None)
            if close is not None:
                close()
    masks = None if found is None else found.masks
    seeds = None if found is None else found.seeds
    chosen = _chosen_surface(request.plan.seeds)
    ground = yield from constraints.ground_steps(project, chosen, version_uid, budget_s=budget_s)
    base = yield from constraints.build_steps(
        constraints.Request(project, version_uid, request.version_code, chosen, shown,
                            request.stamp),
        budget_s=budget_s, loaded=masks, ground=ground)
    batches: list[Batch] = []
    has_domain = False
    if seeds is not None and seeds.domain.cells:
        segments = yield from constraints.mask_hatch_steps(
            seeds.domain.mask, seeds.geometry, constraints.DOMAIN_LINES, budget_s=budget_s)
        if len(segments):
            positions = yield from constraints.drape_segments_steps(segments, ground, origin,
                                                                   budget_s=budget_s)
            batches.append(Batch(constraints.DOMAIN, constraints.DOMAIN,
                                 constraints.DOMAIN_COLOR, constraints.HATCH_PX, positions))
            has_domain = True
    batches.extend(batch for batch in base.batches
                   if batch.role not in (constraints.DOMAIN, constraints.STRIP))
    sector_batches: tuple[Batch, ...] = ()
    sector_labels: tuple[Label, ...] = ()
    sectors: tuple[tuple[str, bool], ...] = ()
    if masks is not None:
        sector_batches, sector_labels, sectors = yield from _sector_steps(
            project, masks, ground, origin, budget_s=budget_s)
    batches.extend(sector_batches)
    points = None
    if seeds is not None:
        points = yield from seed_points_steps(seeds, origin, budget_s=budget_s)
    lines = replace(base, batches=tuple(batches), labels=(*base.labels, *sector_labels),
                    legend=_legend(request, base, points, has_domain, sectors),
                    stamp=request.stamp)
    return Built(lines, points, sectors, () if found is None else summary_lines(found, shown))


# --- Qué cambió ----------------------------------------------------------------------------------


def stamp(project: Any, version_uid: str | None) -> tuple[Any, ...]:
    """El sello de lo que lee la vista previa para ``version_uid`` (``None``: ninguna): el mismo de la
    superposición de la 012 (``bl.draw.constraints.stamp``: la versión, el estado de sus máscaras y
    de las búsquedas, las operaciones, los datos y los parámetros). Solo lee."""
    return constraints.stamp(project, version_uid)


# --- Lo que se dibuja en píxeles -----------------------------------------------------------------


def toolbar_covered_px(space: Any, area: Any, overlap: bool) -> float:
    """Lo que tapa por la izquierda la barra de herramientas de la Vista 3D (``area``, con su
    ``space``) a lo que se dibuja en la región: su anchura (px) si se superpone a la región
    (``overlap``: la preferencia «Region Overlap»), está a la vista (``show_region_toolbar``; una
    región oculta mide 1 o 0 px) y está a la izquierda; 0 si no. Solo lee."""
    if not overlap or not space.show_region_toolbar:
        return 0.0
    for region in area.regions:
        if region.type == "TOOLS":
            if region.alignment != "LEFT" or region.width <= 1:
                return 0.0
            return float(region.width)
    return 0.0


def summary_items(summary: Sequence[tuple[str, bool]], measure: Callable[[str], float],
                  scale: float, size: tuple[float, float], covered_px: float = 0.0) -> list[Any]:
    """El resumen arriba a la izquierda de la región (``size``): su fondo y cada línea partida al
    ancho (:data:`SUMMARY_WIDTH_FRACTION` de lo que queda a la derecha de ``covered_px`` como mucho),
    los avisos en ámbar. ``covered_px`` es la anchura (px) de lo que tapa la región por la izquierda
    (:func:`toolbar_covered_px`): el resumen empieza donde acaba, con su margen; con 0, en el borde."""
    if not summary:
        return []
    row, margin, pad = (dh_overlay.ROW_PX * scale, dh_overlay.MARGIN_PX * scale,
                        dh_overlay.PAD_PX * scale)
    covered = max(0.0, float(covered_px))
    left = covered + margin
    limit = max(60.0 * scale, (size[0] - covered) * SUMMARY_WIDTH_FRACTION - 2.0 * margin)
    lines = [(part, alert) for text, alert in summary
             for part in wrap_text(text, measure, limit)]
    width = max(float(measure(part)) for part, _alert in lines)
    top = size[1] - margin - SUMMARY_TOP_PX * scale
    height = len(lines) * row
    items: list[Any] = [Box(left - pad, top - height - pad, left + width + pad, top + pad,
                            dh_overlay.PANEL)]
    baseline = (row - dh_overlay.FONT_PX * scale) / 2.0 + 2.0 * scale
    for index, (part, alert) in enumerate(lines):
        bottom = top - (index + 1) * row
        items.append(Text(left, bottom + baseline, part, ALERT_COLOR if alert else TEXT_COLOR))
    return items


def screen_items(built_view: Built, matrix: Any, size: tuple[float, float], *,
                 measure: Callable[[str], float], scale: float = 1.0,
                 covered_px: float = 0.0) -> list[Any]:
    """Lo que la vista previa dibuja en píxeles de la región (``size``) con la matriz de la vista
    ``matrix``: los nombres que caben y la leyenda (los de la 012) y el resumen
    (``bl.draw.dh_overlay.Text`` y ``Box``). ``measure`` da el ancho en px de un texto; ``scale``,
    la escala de la interfaz; ``covered_px``, lo que la barra de herramientas tapa por la izquierda
    (el resumen empieza a su derecha)."""
    items = constraints.screen_items(built_view.lines, matrix, size, measure=measure, scale=scale)
    items.extend(summary_items(built_view.summary, measure, scale, size, covered_px))
    return items


def draw_points(built_view: Built, *, view_matrix: Matrix, projection_matrix: Matrix,
                perspective: bool, view_distance: float, pixel_size: float) -> int:
    """Dibuja en el *framebuffer* activo los puntos de las semillas (un solo lote de ``gpu`` con su
    color por vértice, creado la primera vez) con las matrices dadas (la de vista, acercada a la
    cámara) y la prueba de profundidad ``LESS_EQUAL`` sin escribir profundidad. Deja el estado de
    ``gpu`` como estaba. Devuelve cuántos puntos dibujó."""
    seeds = built_view.seeds
    if seeds is None or not seeds.count:
        return 0
    shader = gpu.shader.from_builtin(POINT_SHADER)
    view = constraints.pulled(view_matrix, perspective, view_distance)
    state = (gpu.state.depth_test_get(), gpu.state.depth_mask_get(), gpu.state.blend_get())
    with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
        gpu.matrix.load_projection_matrix(projection_matrix)
        gpu.matrix.load_matrix(view)
        gpu.state.depth_test_set("LESS_EQUAL")
        gpu.state.depth_mask_set(False)
        gpu.state.blend_set("ALPHA")
        gpu.state.point_size_set(seeds.size_px * float(pixel_size))
        try:
            seeds.gpu_batch(shader).draw(shader)
        finally:
            gpu.state.point_size_set(1.0)
            gpu.state.depth_test_set(state[0])
            gpu.state.depth_mask_set(state[1])
            gpu.state.blend_set(state[2])
    return seeds.count


# --- Activar y quitar ----------------------------------------------------------------------------


class _State:
    """Lo de la sesión (no se guarda en el ``.blend``)."""

    def __init__(self) -> None:
        self.enabled = False
        self.handles: list[Any] = []
        self.built: Built | None = None
        self.steps: Generator[None, None, Built] | None = None
        self.request: Request | None = None
        self.plan: Plan | QuarryPlan | None = None
        self.undo: list[Callable[[], object]] = []
        self.failed = False


_STATE = _State()


def enabled() -> bool:
    """Si la vista previa está activa."""
    return _STATE.enabled


def drawing() -> bool:
    """Si los manejadores de dibujo están puestos."""
    return bool(_STATE.handles)


def building() -> bool:
    """Si quedan pasos por dar para construirla."""
    return _STATE.steps is not None


def built() -> Built | None:
    """Lo último construido (se dibuja mientras se rehace); ``None`` si no hay."""
    return _STATE.built


def plan() -> Plan | QuarryPlan | None:
    """Lo que se previsualiza ahora (las semillas de la 013 o un diseño de la cantera); ``None`` si
    no está activa."""
    return _STATE.plan


def _measure(text: str) -> float:
    return float(blf.dimensions(dh_overlay.FONT_ID, text)[0])


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
    LOGGER.exception("No se pueden dibujar %s de la vista previa del diseño: se apaga", what)


def _draw_view() -> None:
    """El manejador ``POST_VIEW`` de cada Vista 3D: los lotes de líneas y los puntos."""
    if _STATE.failed or _STATE.built is None:
        return
    try:
        ready = _region_ready()
        if ready is None:
            return
        _space, region, rv3d = ready
        pixel_size = float(bpy.context.preferences.system.pixel_size)
        view, projection = gpu.matrix.get_model_view_matrix(), gpu.matrix.get_projection_matrix()
        if _STATE.built.lines.batches:
            constraints.draw_lines(_STATE.built.lines, view_matrix=view,
                                   projection_matrix=projection,
                                   perspective=bool(rv3d.is_perspective),
                                   view_distance=float(rv3d.view_distance),
                                   viewport_size=(float(region.width), float(region.height)),
                                   pixel_size=pixel_size)
        draw_points(_STATE.built, view_matrix=view, projection_matrix=projection,
                    perspective=bool(rv3d.is_perspective),
                    view_distance=float(rv3d.view_distance), pixel_size=pixel_size)
    except Exception:  # una traza por fotograma no ayuda a nadie
        _fail("las semillas y las líneas")


def _draw_pixels() -> None:
    """El manejador ``POST_PIXEL`` de cada Vista 3D: los nombres, la leyenda y el resumen."""
    if _STATE.failed or _STATE.built is None:
        return
    try:
        ready = _region_ready()
        if ready is None:
            return
        space, region, rv3d = ready
        context = bpy.context
        scale = float(context.preferences.system.ui_scale)
        size = (float(region.width), float(region.height))
        covered = toolbar_covered_px(space, context.area,
                                     bool(context.preferences.system.use_region_overlap))
        blf.size(dh_overlay.FONT_ID, dh_overlay.FONT_PX * scale)
        items = screen_items(_STATE.built, np.array(rv3d.perspective_matrix), size,
                             measure=_measure, scale=scale, covered_px=covered)
        if items:
            dh_overlay.paint(items, size, scale=scale)
    except Exception:  # una traza por fotograma no ayuda a nadie
        _fail("el resumen y la leyenda")


def _redraw() -> None:
    """Pide redibujar las Vistas 3D de todas las ventanas."""
    manager = getattr(bpy.context, "window_manager", None)
    for window in getattr(manager, "windows", ()):
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _close_steps() -> None:
    steps, _STATE.steps = _STATE.steps, None
    if steps is not None:
        steps.close()


def _publish(lines: Sequence[tuple[str, bool]]) -> None:
    """Deja el resumen en la vista de las ventanas del diseño (``bl.ui.des_panels.show_preview``)."""
    from ..ui import des_panels  # al usarlo: bl.ui importa bl.draw

    try:
        des_panels.show_preview(lines)
    except (ReferenceError, AttributeError, RuntimeError):
        LOGGER.debug("No se pudo dejar el resumen de la vista previa en la vista", exc_info=True)


def _error_text(exc: BaseException) -> str:
    """El texto de un error para la persona, en el idioma de Geoblender."""
    if isinstance(exc, design_messages.DesignError):
        return design_messages.render(exc.code, language=language(), **exc.values)
    if isinstance(exc, GeoblenderError):
        return exc.message
    return str(exc) or type(exc).__name__


def rebuild(project: Any = None, version_uid: str | None = None) -> None:
    """Empieza a construir de nuevo lo que dibuja la vista previa para la versión activa (o
    ``version_uid``) del proyecto de la sesión (o ``project``), y deja un temporizador que da los
    pasos (:func:`tick`); lo anterior se sigue dibujando hasta que acabe. Lo que se construía a mitad
    se cierra. Sin proyecto o sin nada que previsualizar, no dibuja nada."""
    project = project or project_session.current()
    _close_steps()
    if project is None or _STATE.plan is None:
        _STATE.built = None
        return
    shown = scene_versions.active()
    uid = version_uid if version_uid is not None else (None if shown is None else shown.uid)
    code = "" if shown is None or shown.uid != uid else shown.code
    try:
        sealed = stamp(project, uid)
    except (GeoblenderError, sqlite3.Error, OSError):
        sealed = ("error",)
    request = Request(project, uid, code, _STATE.plan, language(), sealed)
    _STATE.request = request
    _STATE.steps = build_steps(request)
    if not bpy.app.timers.is_registered(tick):
        bpy.app.timers.register(tick, first_interval=TICK_INTERVAL_S, persistent=True)


def tick() -> float | None:
    """El temporizador: da pasos de la construcción durante :data:`TICK_BUDGET_S` s como mucho;
    devuelve cuándo volver (``None``: acabó o no hay nada que construir). Al acabar deja el
    resumen en la vista. Si falla un paso (el cálculo rechaza lo previsualizado, una superficie que
    ya no está…), avisa con el motivo y quita la vista previa."""
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
            _publish(done.value.summary)
            _redraw()
        return None
    except Exception as exc:  # noqa: BLE001 - lo dice el aviso y el registro
        LOGGER.warning("No se pudo preparar la vista previa del diseño", exc_info=True)
        project_session.notify(tr(
            "The preview of seeds, domains and constraints could not be prepared: {detail}",
            detail=_error_text(exc)))
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
    """Lo que se apunta en los indicadores de la procedencia (``add_change_listener``): si el proyecto
    cambió en algo que lee la vista previa (:func:`stamp`), la rehace."""
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
    """Lo que se apunta en ``bl.scene.project_session``: cerrar el proyecto o abrir otro la quita."""
    request = _STATE.request
    if _STATE.enabled and (project is None or request is None or project is not request.project):
        disable()


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


def default_plan() -> Plan:
    """Lo que se previsualiza si nadie lo pide: las semillas de la primera superficie o rejilla de
    cotas que ofrece el proyecto (la versión activa y el proyecto), en toda ella, y todo el dominio.
    Sin proyecto o sin ninguna rejilla, ``RuntimeError``."""
    from ..ui import des_panels  # al usarlo: bl.ui importa bl.draw

    project = project_session.current()
    if project is None:
        raise RuntimeError("no hay un proyecto abierto: no hay semillas que ver")
    des_panels.refresh_choices(project)
    if not des_panels.has_surfaces():
        raise RuntimeError("no hay ninguna rejilla en el proyecto ni en la versión activa: no hay "
                           "semillas que ver")
    return Plan(SeedSource(SeedKind.SURFACE, surface=des_panels.surface_items(None, None)[0][0]))


def enable(wanted: Plan | QuarryPlan | None = None) -> None:
    """Activa la vista previa de ``wanted`` (unas semillas de la 013, :class:`Plan`, o un diseño de la
    cantera de la 014, :class:`QuarryPlan`; sin él, :func:`default_plan`): pone los manejadores de
    dibujo, apunta lo que la rehace o la quita y empieza a construirla (:func:`rebuild`). Ya activa,
    nada. Sin proyecto abierto o sin rejillas que previsualizar, ``RuntimeError``."""
    if _STATE.enabled:
        return
    project = project_session.current()
    if project is None:
        raise RuntimeError("no hay un proyecto abierto: no hay semillas que ver")
    chosen = wanted if wanted is not None else default_plan()
    _STATE.failed = False
    _STATE.enabled = True
    _STATE.plan = chosen
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
    """Quita la vista previa: los manejadores de dibujo, los lotes, lo que se construía, lo que la
    rehacía y su resumen de la vista. Ya quitada, nada."""
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
            LOGGER.debug("No se pudo quitar una escucha de la vista previa", exc_info=True)
    _STATE.built = None
    _STATE.request = None
    _STATE.plan = None
    if was:
        _publish(())
        _redraw()


def register() -> None:
    """Nada que poner: los manejadores solo están mientras la vista previa está activa."""
    _STATE.failed = False


def unregister() -> None:
    """Quita la vista previa si está activa (principio 8)."""
    disable()
