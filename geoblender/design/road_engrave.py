# SPDX-License-Identifier: GPL-3.0-or-later
"""Aplicar la sección de la pista y su borde con dos ángulos (spec 017, T13; HU-017-1; RF-017-21, RF-017-22, RF-017-23 y RF-017-06; RNF-017-04, RNF-017-06 y
RNF-017-07; plan 017 §5.4 A8 y A9, §5.7 P-4 y P-11). Dominio puro: sin proyecto y sin ``bpy``.

Lo que entrega, con las coordenadas absolutas en float64 (regla 4 de AGENTS.md) y todo lo que vuelve de solo lectura:

- :func:`engrave` (y :func:`engrave_steps`, por pasos; :func:`engrave_units`, las unidades para componerlas con otras): el :class:`Engraved` de una pista dados su
  trabajo (:class:`~.road_model.RoadJob`), su sección (:class:`~.road_section.Section`, medida en la ventana de :func:`engrave_window`) y la rasante de cada celda
  de la sección (``levels``: ``Section.levels(axis.stations, z)``).
- :func:`engrave_window`: la **ventana de trabajo** de la pista (A0): la caja del corredor de su sección ampliada por el alcance del borde y dos celdas, recortada a
  la rejilla (``platform.work_window``), que es donde se mide la sección (``section_cells(..., window)``) y se calcula el borde: **toda la pista en una caja** (P-11),
  no por tramos.
- :func:`carriageway_notice`: el aviso de RF-017-22 de un grupo de celdas de la calzada que no queda en su rasante, con lo que lo impide.

**Aplicar** (A8; RF-017-21, RF-017-22, RF-017-06): ``z' = rasante`` en cada celda de la sección **donde el corte (si está por encima) o el relleno (si está por debajo) se
admiten** —``cut_allowed`` y ``fill_allowed`` del trabajo, sin lo intocable ni las exclusiones: ``untouchable``—, **y donde el movimiento no pasa de la altura máxima de
desmonte y terraplén de la ruta** (``RouteParams.max_cut_fill_m``: solo el modo «trazar» la tiene); el resto, como en la partida. Una celda que queda a ≤ 1 mm de su
rasante (:data:`LEVEL_TOLERANCE_M`, la tolerancia de RF-017-22) está **en la rasante** y es una semilla del borde. Las celdas **de la calzada** que no quedan en ella
se agrupan (4-conexas, :class:`OffLevelGroup`) con su área, su diferencia máxima, su lugar y su **causa** (:class:`EngraveCause`: el corte o el relleno que las
máscaras no admiten, o la altura máxima): son el aviso de RF-017-22 **antes de crear** y piden la confirmación expresa (:attr:`Engraved.needs_confirmation`). Qué
restricción o qué entidad es la de «máscaras» lo nombra quien lee las restricciones (T20), con las celdas de cada grupo (:attr:`OffLevelGroup.index`), como en la 015
(``HeldGroup``); :func:`carriageway_notice` arma el aviso con ese nombre.

**El borde** (A9; RF-017-21; **copia** de ``platform._edge_units``, P-4: la plataforma no cambia ni un bit): con ``t↑ = tan(ángulo de desmonte) · factor de malla`` y
``t↓ = tan(ángulo de terraplén) · factor de malla`` del perfil y su métrica (la euclídea exacta o el *chamfer* 5×5), la envolvente ascendente ``ENV↑`` (con ``t↑``) y la
descendente ``ENV↓`` (con ``t↓``) de las semillas (``edges.seed_envelope_steps``) y el alcance como la distancia a la semilla más próxima (``envelopes.reach_steps``)
dan, **fuera de la sección** y hasta el alcance, ``z' = mín(z, ENV↑)`` donde el corte se admite y ``z' = máx(z, ENV↓)`` donde se admite el relleno (si las dos se
cruzan, gana la descendente, como en la plataforma); lo que pasa del alcance, ni un bit, y donde las máscaras no dejan mover (``Engraved.held``), tampoco. El volumen
del borde (corte y relleno por separado) es la suma celda a celda de ``|z − z'|`` por el área de la celda; su **pared** (la mayor altura movida), las celdas movidas
**más empinadas que el ángulo (el de desmonte si bajan, el de terraplén si suben) más la tolerancia de cara de la 013 y que lo que el terreno ya tenía** (solo se admite
en el límite del alcance y junto a lo que las máscaras no dejan mover: :class:`~.platform.WallCause`), lo que llega al borde de la rejilla o a celdas sin dato
(``supported_edge.reaches_outside``), el salto creado de la 014 (``edges.created_steps``) y el orden con la otra superficie de una cantera
(``platform.order_check``, ``supported_edge.order_notice``) son los datos de RF-015-13 y RF-015-14 y sus avisos (:attr:`Engraved.notices`).

**Las cifras** de RF-017-23 que salen del grabado (:meth:`Engraved.figure_values`: las doce claves de ``provenance.ROAD_FIGURES`` que no son del eje ni de la rasante): el
área de la sección, el corte y el relleno **de la sección y del borde por separado** y el neto (corte menos relleno), la pared, las alturas máximas de desmonte y de
terraplén (sección y borde) y la afección de «preferible no afectar» (las celdas de peso mayor que 1 que cambian: su área, su volumen y su volumen por el peso).

**Interpretaciones** (la spec y el plan no las dicen; revisables, anotadas en la verificación de T13): la altura máxima de desmonte y terraplén se mide en **cada celda
de la sección** (``|z − rasante|``), no solo en el eje (la sección tiene hasta ``pendiente transversal · semianchura`` más que el eje); en los modos «sobre un eje» y
«eje 3D», que no tienen ruta, no hay altura máxima; una zona «preferible no afectar» de peso exactamente 1 no se cuenta (``avoid_weight`` no la distingue de lo que no
lo es); la afección cuenta las celdas **que cambian**, no las que la huella pisa sin moverlas.

Los pasos (:func:`engrave_steps`) ceden el hilo cada ≈ 0,05 s (``pace_progress``; RNF-017-06): las envolventes son por unidades, el resto va por bandas de filas. Cerrar el
generador a mitad no deja nada: no escribe nada y no modifica sus entradas (principio 7). **Perezoso** (RNF-001-03): ni ``design.model`` ni nada del arranque lo importan.
"""

from __future__ import annotations

import math
from collections.abc import Generator, Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from ..core.project.model import Progress
from ..gis.grid import Grid
from ..gis.masks.compile import STEP_BUDGET_S
from .edges import EdgeReport, created_steps, edge_notices, seed_envelope_steps, transition_domain
from .envelopes import SlopeField, reach_steps
from .grids import _label_units, dilate_square
from .model import Direction, Metric
from .params import EDGE_MAX_STEP, EDGE_MIN_SHARE, TOLERANCE_FACE, VERIFY_MIN_THICKNESS, check_quarry_param
from .platform import (
    EdgeWall,
    OrderBreach,
    QuarryOrder,
    WallCause,
    _drain,
    _places,
    _project_number,
    _walls,
    _window_grid,
    order_check,
    work_window,
)
from .preview import Notice
from .report import REPORT_CELLS_PER_UNIT, _thickness, max_tangents, padded_rows
from .road_model import RoadJob
from .road_profiles import RoadProfile, derived
from .road_section import Section, SectionClass, section_window
from .seeds import pace_progress
from .supported_edge import order_notice, outside_notice, reaches_outside

__all__ = [
    "LEVEL_TOLERANCE_M",
    "EngraveCause",
    "Engraved",
    "OffLevelGroup",
    "carriageway_notice",
    "engrave",
    "engrave_steps",
    "engrave_units",
    "engrave_window",
]

LEVEL_TOLERANCE_M = 0.001
"""Lo que una celda de la sección puede separarse de su rasante (m) y seguir «en ella» (RF-017-22: tolerancia de 1 mm): la de la calzada que pasa de ahí y no se mueve
es un grupo del aviso de antes de crear; las que quedan dentro son las semillas del borde. Es la tolerancia de la spec, no una cifra minera."""
_TOL_M = 1e-9
"""El ruido de la última cifra de una comparación de cotas (m): un movimiento que pasa de la altura máxima en menos de esto no la pasa."""
_PHASE = "road_engrave"
_BAND_ROWS = 64


class EngraveCause(StrEnum):
    """Por qué una celda de la calzada no queda en su rasante (RF-017-22): ``CUT_DENIED`` (está por encima y las máscaras no dejan cortar), ``FILL_DENIED`` (está por
    debajo y las máscaras no dejan rellenar) o ``MAX_HEIGHT`` (las máscaras lo admiten pero el movimiento pasa de la altura máxima de desmonte y terraplén de la ruta).
    El valor es el nombre de la máscara o de la altura."""

    CUT_DENIED = "cut_allowed"
    FILL_DENIED = "fill_allowed"
    MAX_HEIGHT = "max_height"


@dataclass(frozen=True, slots=True, eq=False)
class OffLevelGroup:
    """Un grupo 4-conexo de celdas de la calzada que no quedan en su rasante (RF-017-22): su número ``group`` (desde 1 en todo el resultado, por causa y, dentro de cada una,
    en el orden de su primera celda recorriendo la ventana fila a fila desde el norte), su ``cause``, sus ``cells`` y su ``area_m2``, su diferencia máxima con la rasante
    ``max_m`` (m, positiva), su centro ``x``, ``y`` (m, absolutos en float64: la media de los centros de sus celdas) y el ``index`` de sus celdas en la ventana (enteros
    ``fila · columnas + columna``, int64 ordenados y de solo lectura: ``divmod(index, ncols)``), con lo que quien lee las restricciones nombra la que lo impide."""

    group: int
    cause: EngraveCause
    cells: int
    area_m2: float
    max_m: float
    x: float
    y: float
    index: np.ndarray


@dataclass(frozen=True, slots=True, eq=False)
class Engraved:
    """El grabado de una pista (A8 y A9; RF-017-21 a RF-017-23), en la ventana de trabajo de su sección (``window``; todas las rejillas de abajo son de su forma y de solo
    lectura): ``surface`` (m, float64, **nueva**: la superficie de partida con la sección y el borde, ``z'``) y ``applied`` (con solo la sección aplicada), ``footprint`` (la
    sección), ``at_level`` (sus celdas a ≤ 1 mm de su rasante: las semillas del borde), ``cut_denied`` y ``fill_denied`` (las celdas de la sección por encima o por debajo
    de su rasante que las máscaras no dejan cortar o rellenar) y ``too_high`` (las que las máscaras admiten pero pasan de la altura máxima ``max_height_m``; ``None`` sin
    ella), y del borde: ``in_reach`` (a ≤ ``reach_m`` de las semillas con la métrica ``metric``), ``changed`` (lo que mueve, fuera de la sección), ``held`` (lo que su
    envolvente movería y las máscaras no admiten), ``steep`` (las movidas más empinadas que su ángulo más la tolerancia de cara ``tolerance_deg`` y que el terreno) y
    ``outside`` (las movidas que llegan al borde de la rejilla o a celdas sin dato).

    ``off_level`` son los grupos de la calzada que no quedan en su rasante (:class:`OffLevelGroup`; con alguno hace falta la confirmación expresa:
    :attr:`needs_confirmation`). El corte y el relleno **de la sección** (``section_cut_m3``, ``section_fill_m3``, m³, y las celdas que bajan y suben) y **del borde**
    (``edge_*``), **por separado**; las alturas máximas de desmonte y de terraplén (``cut_height_max_m``, ``fill_height_max_m``: la mayor ``z − z'`` y ``z' − z`` de la
    sección y del borde); la pared del borde (``wall_max_m``: ``máx(|z − z'|)`` en lo que mueve, con su lugar ``wall_x``, ``wall_y``; ``None`` sin borde), ``walls`` (las
    celdas de ``steep`` por causa), ``created`` (el salto creado de la 014 de la superficie entera) y ``order`` (el incumplimiento de ``final ≤ explotación ≤ terreno``
    frente a la otra superficie de una cantera; ``None`` si se cumple o no se pidió). La afección de «preferible no afectar»: ``avoid_cells``, ``avoid_m2``, ``avoid_m3`` y
    ``avoid_weighted_m3``. ``notices`` son los avisos ya armados, en este orden: la pared del borde (``des.road_edge_steep``), lo que llega al borde de la rejilla o a celdas
    sin dato (``des.entity_edge_outside``), el salto creado y sus tramos (``des.edge_surface_step`` y ``des.edge_stretch``), el orden con la cantera
    (``des.entity_quarry_order``) y la afección (``des.road_avoid_affected``). Los de la calzada que no queda en su rasante son de :func:`carriageway_notice`."""

    window: tuple[slice, slice]
    surface: np.ndarray
    applied: np.ndarray
    footprint: np.ndarray
    at_level: np.ndarray
    cut_denied: np.ndarray
    fill_denied: np.ndarray
    too_high: np.ndarray
    in_reach: np.ndarray
    changed: np.ndarray
    held: np.ndarray
    steep: np.ndarray
    outside: np.ndarray
    off_level: tuple[OffLevelGroup, ...]
    metric: Metric
    cut_angle_deg: float
    fill_angle_deg: float
    mesh_factor: float
    reach_m: float
    tolerance_deg: float
    max_height_m: float | None
    footprint_cells: int
    section_cut_cells: int
    section_fill_cells: int
    section_cut_m3: float
    section_fill_m3: float
    edge_cut_cells: int
    edge_fill_cells: int
    edge_cut_m3: float
    edge_fill_m3: float
    cut_height_max_m: float
    fill_height_max_m: float
    wall_max_m: float
    wall_x: float | None
    wall_y: float | None
    walls: tuple[EdgeWall, ...]
    created: EdgeReport
    order: OrderBreach | None
    avoid_cells: int
    avoid_m2: float
    avoid_m3: float
    avoid_weighted_m3: float
    cell_area_m2: float
    notices: tuple[Notice, ...]

    @property
    def needs_confirmation(self) -> bool:
        """Si alguna celda de la calzada no queda en su rasante: la pista **no se crea sin la confirmación expresa** de la persona (RF-017-22)."""
        return bool(self.off_level)

    @property
    def area_m2(self) -> float:
        """El área de la sección (m²): sus celdas por el área de una (el área grabada de RF-017-23)."""
        return self.footprint_cells * self.cell_area_m2

    @property
    def cut_m3(self) -> float:
        """El corte total (m³): el de la sección más el del borde."""
        return self.section_cut_m3 + self.edge_cut_m3

    @property
    def fill_m3(self) -> float:
        """El relleno total (m³): el de la sección más el del borde."""
        return self.section_fill_m3 + self.edge_fill_m3

    @property
    def net_m3(self) -> float:
        """El volumen neto (m³): corte menos relleno, de la sección y del borde juntos (puede ser negativo)."""
        return self.cut_m3 - self.fill_m3

    @property
    def held_cells(self) -> int:
        """Las celdas del borde que las máscaras no dejan mover."""
        return int(np.count_nonzero(self.held))

    @property
    def steep_cells(self) -> int:
        """Las celdas del borde más empinadas que su ángulo más la tolerancia de cara."""
        return int(np.count_nonzero(self.steep))

    @property
    def outside_cells(self) -> int:
        """Las celdas que el borde mueve y llegan al borde de la rejilla o a celdas sin dato."""
        return int(np.count_nonzero(self.outside))

    def figure_values(self) -> dict[str, float | None]:
        """Las doce cifras de RF-017-23 que salen del grabado, por su clave de :data:`~.provenance.ROAD_FIGURES`: el área grabada, el corte y el relleno de la sección y del
        borde por separado, el neto, la pared del borde (``None`` sin borde: no se registra), las alturas máximas de desmonte y de terraplén y la afección de «preferible no
        afectar» (m², m³ y m³ por su peso). Quien calcula la pista las junta con las del eje y la rasante para ``provenance.road_figures``."""
        return {
            "des.road_area_m2": self.area_m2,
            "des.road_cut_m3": self.section_cut_m3,
            "des.road_fill_m3": self.section_fill_m3,
            "des.road_edge_cut_m3": self.edge_cut_m3,
            "des.road_edge_fill_m3": self.edge_fill_m3,
            "des.road_net_m3": self.net_m3,
            "des.road_wall_max_m": None if self.wall_x is None else self.wall_max_m,
            "des.road_cut_height_max_m": self.cut_height_max_m,
            "des.road_fill_height_max_m": self.fill_height_max_m,
            "des.road_avoid_m2": self.avoid_m2,
            "des.road_avoid_m3": self.avoid_m3,
            "des.road_avoid_weighted_m3": self.avoid_weighted_m3,
        }


# --- La ventana de trabajo -----------------------------------------------------------------------------------------------


def engrave_window(axis: object, profile: RoadProfile, grid: Grid) -> tuple[slice, slice]:
    """**A0** (plan 017 §5.4; P-11): la ventana de trabajo de la pista de eje ``axis`` (un :class:`~.road_axis.Axis`) con el perfil ``profile``: la caja del corredor de su sección
    (:func:`~.road_section.section_window`) ampliada por el alcance del borde con la métrica del perfil y dos celdas (:func:`~.platform.work_window`), recortada a ``grid``.
    Es donde se mide la sección (``section_cells(..., window)``) y se calcula el borde: **contiene siempre lo que el alcance puede tocar**. ``TypeError`` si el perfil no es un
    :class:`~.road_profiles.RoadProfile`."""
    if not isinstance(profile, RoadProfile):
        raise TypeError(f"el perfil de una pista es RoadProfile, no {profile!r}")
    box = section_window(axis, derived(profile).carriageway_m, profile.shoulder_m, profile.berm_m, grid)  # type: ignore[arg-type]
    return work_window(box[0], box[1], profile.reach_m, grid, profile.metric)


# --- Lo que lee el borde ----------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Settings:
    """Lo que lee el grabado, ya comprobado: los ángulos de desmonte y de terraplén con el factor de malla, el alcance y la métrica del perfil, la altura máxima de la ruta
    (``None``: sin ruta) y los parámetros del proyecto (la tolerancia de cara, el espesor mínimo, el salto creado admitido y su porcentaje)."""

    cut_angle_deg: float
    fill_angle_deg: float
    mesh_factor: float
    reach_m: float
    metric: Metric
    max_height_m: float | None
    tolerance_deg: float
    thickness_m: float
    threshold_m: float
    share_pct: float

    @property
    def tan_cut(self) -> float:
        """La tangente efectiva de la envolvente ascendente: ``tan(ángulo de desmonte) · factor de malla``."""
        return math.tan(math.radians(self.cut_angle_deg)) * self.mesh_factor

    @property
    def tan_fill(self) -> float:
        """La tangente efectiva de la descendente: ``tan(ángulo de terraplén) · factor de malla``."""
        return math.tan(math.radians(self.fill_angle_deg)) * self.mesh_factor


def _settings(job: RoadJob, project: Mapping[str, object]) -> _Settings:
    """Los valores del grabado de ``job`` y los parámetros del proyecto, comprobados (``ValueError``: errores del programa: ningún parámetro del proyecto tiene valor por
    defecto aquí; ``des.quarry_param_*`` si el salto o el porcentaje salen de rango)."""
    if not isinstance(job, RoadJob):
        raise TypeError(f"el trabajo de una pista es RoadJob, no {job!r}")
    profile = job.profile
    tolerance = _project_number(project, TOLERANCE_FACE)
    if tolerance < 0.0:
        raise ValueError(f"la tolerancia de cara es un número finito ≥ 0, no {tolerance!r}")
    thickness = _thickness(_project_number(project, VERIFY_MIN_THICKNESS))
    threshold = float(check_quarry_param(EDGE_MAX_STEP, _project_number(project, EDGE_MAX_STEP)))
    share = float(check_quarry_param(EDGE_MIN_SHARE, _project_number(project, EDGE_MIN_SHARE)))
    height = None if job.route is None else float(job.route.max_cut_fill_m)
    return _Settings(profile.cut_angle_deg, profile.fill_angle_deg, profile.mesh_factor, profile.reach_m, Metric(profile.metric), height, tolerance, thickness, threshold, share)


def _check(job: RoadJob, section: Section, levels: np.ndarray, settings: _Settings, quarry: QuarryOrder | None) -> np.ndarray:
    """``levels`` como float64 y ``ValueError`` (errores del programa) si la sección o la rasante no son de la ventana de ``job``, la sección no tiene ninguna celda, las celdas
    no son cuadradas o la ventana no cubre lo que el alcance puede tocar con la métrica del perfil (A0: el cálculo no sale de ella; ``engrave_window`` la da)."""
    if not isinstance(section, Section):
        raise TypeError(f"la sección de una pista es road_section.Section, no {section!r}")
    if quarry is not None and not isinstance(quarry, QuarryOrder):
        raise TypeError(f"la otra superficie de la cantera es platform.QuarryOrder, no {quarry!r}")
    grid = job.grid
    rows, cols = section.window
    if not (0 <= rows.start < rows.stop <= grid.nrows and 0 <= cols.start < cols.stop <= grid.ncols and rows.step in (None, 1) and cols.step in (None, 1)):
        raise ValueError(f"la ventana de la sección ({rows}, {cols}) no cabe en la rejilla de {grid.nrows} filas y {grid.ncols} columnas")
    shape = (rows.stop - rows.start, cols.stop - cols.start)
    if section.cells.shape != shape:
        raise ValueError(f"las celdas de la sección son de la forma {section.cells.shape}, no de la de su ventana {shape}")
    found = np.asarray(levels, dtype=np.float64)
    if found.shape != shape:
        raise ValueError(f"la rasante por celda es de la forma {found.shape}, no de la de la ventana de la sección {shape}")
    if grid.dx != grid.dy:
        raise ValueError(f"las envolventes se calculan en una rejilla de celdas cuadradas (ADR-0014), no de {grid.dx} × {grid.dy} m")
    where_rows, where_cols = np.nonzero(section.cells)
    if not where_rows.size:
        raise ValueError("la sección no tiene ninguna celda")
    needed = work_window(slice(int(where_rows.min()) + rows.start, int(where_rows.max()) + 1 + rows.start),
                         slice(int(where_cols.min()) + cols.start, int(where_cols.max()) + 1 + cols.start), settings.reach_m, grid, settings.metric)
    if not (rows.start <= needed[0].start and needed[0].stop <= rows.stop and cols.start <= needed[1].start and needed[1].stop <= cols.stop):
        raise ValueError(
            f"la ventana de la sección ({rows}, {cols}) no cubre lo que un alcance de {settings.reach_m} m puede tocar con la métrica {settings.metric.value} "
            f"({needed[0]}, {needed[1]}): mida la sección en la ventana de engrave_window")
    return found


# --- Los grupos de la calzada que no queda en su rasante ------------------------------------------------------------------------


def _frozen[T: np.ndarray](array: T) -> T:
    """``array`` (propio de quien lo crea) de solo lectura."""
    array.flags.writeable = False
    return array


def _group_units(chosen: np.ndarray, rows: np.ndarray, cols: np.ndarray, depth: np.ndarray, cause: EngraveCause, first: int, grid: Grid, window: tuple[slice, slice],
                 box: tuple[slice, slice], width: int) -> Generator[None, None, tuple[OffLevelGroup, ...]]:
    """Los grupos 4-conexos (:class:`OffLevelGroup`) de las celdas de la sección ``chosen`` (de las celdas de la sección, en su orden): ``rows`` y ``cols`` son su posición
    en la ventana, ``depth`` su diferencia con la rasante, ``box`` la caja de la sección en la ventana (el etiquetado solo recorre esa caja) y ``width`` las columnas de la
    ventana. El primer grupo lleva el número ``first``. Las unidades del etiquetado son las de ``grids._label_units``."""
    if not chosen.any():
        return ()
    picked = np.flatnonzero(chosen)
    picked_rows, picked_cols = rows[picked], cols[picked]
    mask = np.zeros((box[0].stop - box[0].start, box[1].stop - box[1].start), dtype=bool)
    mask[picked_rows - box[0].start, picked_cols - box[1].start] = True
    labels = yield from _label_units(mask)
    tags = labels.grid[picked_rows - box[0].start, picked_cols - box[1].start]
    count = labels.count
    row_sum = np.bincount(tags, weights=picked_rows + window[0].start, minlength=count + 1)
    col_sum = np.bincount(tags, weights=picked_cols + window[1].start, minlength=count + 1)
    top = np.zeros(count + 1)
    np.maximum.at(top, tags, depth[picked])
    order = np.argsort(tags, kind="stable")
    bounds = np.searchsorted(tags[order], np.arange(1, count + 2))
    flat = picked_rows * width + picked_cols
    found: list[OffLevelGroup] = []
    for index in range(1, count + 1):
        cells = int(labels.sizes[index - 1])
        members = np.sort(flat[order[bounds[index - 1]:bounds[index]]])
        found.append(OffLevelGroup(
            first + index - 1, cause, cells, cells * grid.cell_area, float(top[index]),
            float(grid.west + (col_sum[index] / cells + 0.5) * grid.dx), float(grid.north - (row_sum[index] / cells + 0.5) * grid.dy), _frozen(members)))
    return tuple(found)


def carriageway_notice(group: OffLevelGroup, entity: str, *, blocker: str | None = None, other_entity: str | None = None, height_m: float | None = None) -> Notice:
    """El aviso de RF-017-22 del grupo ``group`` de celdas de la calzada de la pista ``entity`` que no quedan en su rasante, antes de crear y con la confirmación expresa:
    ``des.road_carriageway_masks`` (con lo que lo impide, ``blocker``: la restricción de las máscaras), ``des.road_carriageway_entity`` (``other_entity``: la entidad cuya
    restricción no deja mover el terreno) o ``des.road_carriageway_height`` (``height_m``: la altura máxima de desmonte y terraplén que pasa el eje). Lleva el área (m²), la
    diferencia máxima (m, al mm) y el lugar (m, al cm). ``ValueError`` (error del programa) si falta el dato que pide la causa del grupo: ``blocker`` o ``other_entity`` en
    las de las máscaras y ``height_m`` en la de la altura."""
    base = {"entity": entity, "area": group.area_m2, "difference": round(group.max_m, 3), "x": round(group.x, 2), "y": round(group.y, 2)}
    if group.cause is EngraveCause.MAX_HEIGHT:
        if height_m is None:
            raise ValueError("el aviso de una calzada que pasa de la altura máxima de desmonte y terraplén dice esa altura (height_m)")
        return Notice("des.road_carriageway_height", {**base, "height": height_m})
    if other_entity is not None:
        return Notice("des.road_carriageway_entity", {**base, "blocker": other_entity})
    if blocker is None:
        raise ValueError("el aviso de una calzada que las máscaras no dejan mover dice la restricción (blocker) o la entidad (other_entity) que lo impide")
    return Notice("des.road_carriageway_masks", {**base, "blocker": blocker})


# --- Los avisos del borde --------------------------------------------------------------------------------------------------------


def _edge_notices(name: str, settings: _Settings, walls: tuple[EdgeWall, ...], outside: np.ndarray, created: EdgeReport, grid: Grid, window: tuple[slice, slice]
                  ) -> tuple[Notice, ...]:
    """Los avisos del borde, en este orden: la pared (una nota con las celdas de cada causa y la peor), lo que llega al borde de la rejilla o a celdas sin dato con su lugar y
    el salto creado con sus tramos, con el nombre de la pista."""
    found: list[Notice] = []
    if walls:
        by_cause = {wall.cause: wall.cells for wall in walls}
        worst = walls[0]
        for wall in walls[1:]:
            if wall.max_deg > worst.max_deg:
                worst = wall
        found.append(Notice("des.road_edge_steep", {
            "entity": name, "cells": sum(by_cause.values()), "cut_angle": settings.cut_angle_deg, "fill_angle": settings.fill_angle_deg, "tolerance": settings.tolerance_deg,
            "max": worst.max_deg, "x": worst.x, "y": worst.y, "at_reach": by_cause.get(WallCause.REACH, 0), "reach": settings.reach_m, "at_masks": by_cause.get(WallCause.MASKS, 0),
            "other": by_cause.get(WallCause.OTHER, 0)}))
    reached = outside_notice(name, outside, grid, window)
    if reached is not None:
        found.append(reached)
    found.extend(edge_notices(created, surface=name))
    return tuple(found)


# --- Las unidades ---------------------------------------------------------------------------------------------------------------


def _units(job: RoadJob, section: Section, levels: np.ndarray, settings: _Settings, quarry: QuarryOrder | None, budget_s: float) -> Generator[None, None, Engraved]:
    """Las unidades de :func:`engrave_steps`: la sección aplicada y sus grupos (sin bucle por celda, sobre las de la sección y no sobre la ventana), las envolventes y el
    alcance del borde, la superficie con él, sus volúmenes y su pared, las celdas empinadas por bandas de filas, lo que llega al borde de la rejilla, el salto creado y la
    afección."""
    window, fp, grid = section.window, section.cells, job.grid
    shape = fp.shape
    area = grid.cell_area
    name = job.request.name
    z = job.start[window]
    free = ~job.untouchable[window]
    cut_ok = job.cut_allowed[window] & free
    fill_ok = job.fill_allowed[window] & free
    del free
    rows, cols = np.nonzero(fp)
    ground = z[rows, cols]
    wanted = levels[rows, cols]
    missing = int(np.count_nonzero(~np.isfinite(ground)))
    if missing or not np.isfinite(wanted).all():
        raise ValueError(f"la pista «{name}» ({job.code}) tiene {missing} celdas sin dato en su sección (o una rasante sin cota): la preparación lo rechaza antes de calcular "
                         "(RF-015-09)")
    yield None
    # --- A8: aplicar la sección ---
    can_cut, can_fill = cut_ok[rows, cols], fill_ok[rows, cols]
    gap = ground - wanted
    if settings.max_height_m is None:
        high = np.zeros(gap.shape, dtype=bool)
    else:
        high = np.abs(gap) > settings.max_height_m + _TOL_M
    moves = ((gap > 0.0) & can_cut | (gap < 0.0) & can_fill) & ~high
    new = np.where(moves, wanted, ground)
    left = new - wanted
    over, under = left > LEVEL_TOLERANCE_M, left < -LEVEL_TOLERANCE_M
    near = ~(over | under)
    cut_denied_cells, fill_denied_cells = over & ~can_cut, under & ~can_fill
    high_cells = (over | under) & ~cut_denied_cells & ~fill_denied_cells
    drop = ground - new
    section_cut = float(np.sum(np.maximum(drop, 0.0))) * area
    section_fill = float(np.sum(np.maximum(-drop, 0.0))) * area
    yield None
    applied = np.array(z, dtype=np.float64, copy=True)
    applied[rows, cols] = new
    at_level = np.zeros(shape, dtype=bool)
    at_level[rows, cols] = near
    cut_denied = np.zeros(shape, dtype=bool)
    cut_denied[rows, cols] = cut_denied_cells
    fill_denied = np.zeros(shape, dtype=bool)
    fill_denied[rows, cols] = fill_denied_cells
    too_high = np.zeros(shape, dtype=bool)
    too_high[rows, cols] = high_cells
    yield None
    box = (slice(int(rows.min()), int(rows.max()) + 1), slice(int(cols.min()), int(cols.max()) + 1))
    carriageway = section.kind[rows, cols] == int(SectionClass.CARRIAGEWAY)
    depth = np.abs(left)
    groups: list[OffLevelGroup] = []
    for cause, cells in ((EngraveCause.CUT_DENIED, cut_denied_cells), (EngraveCause.FILL_DENIED, fill_denied_cells), (EngraveCause.MAX_HEIGHT, high_cells)):
        found = yield from _group_units(cells & carriageway, rows, cols, depth, cause, len(groups) + 1, grid, window, box, shape[1])
        groups.extend(found)
    # --- A9: el borde con dos ángulos (copia de platform._edge_units) ---
    sub = _window_grid(grid, window)
    label = f"{name} (borde de la pista)"
    seeds = at_level & fp
    in_reach = np.zeros(shape, dtype=bool)
    held = np.zeros(shape, dtype=bool)
    changed = np.zeros(shape, dtype=bool)
    final = z
    yield None
    if seeds.any():
        origin = np.where(seeds, 0.0, np.nan)
        distance = yield from _drain(reach_steps(origin, sub, settings.reach_m, settings.metric, name=label, budget_s=budget_s))
        in_reach = np.isfinite(distance)
        del distance, origin
        seed_z = np.where(seeds, applied, np.nan)
        with np.errstate(invalid="ignore"):
            reachable = in_reach & ~fp & np.isfinite(z)
        up = yield from seed_envelope_steps(seed_z, sub, SlopeField(settings.tan_cut), settings.metric, Direction.UP, label)
        final = np.array(z, dtype=np.float64, copy=True)
        with np.errstate(invalid="ignore"):
            want_cut = reachable & (z > up)
        changed = want_cut & cut_ok
        held = want_cut & ~cut_ok
        final[changed] = up[changed]
        del up, want_cut
        yield None
        down = yield from seed_envelope_steps(seed_z, sub, SlopeField(settings.tan_fill), settings.metric, Direction.DOWN, label)
        with np.errstate(invalid="ignore"):
            want_fill = reachable & (z < down)
        filled = want_fill & fill_ok
        held |= want_fill & ~fill_ok
        final[filled] = down[filled]
        changed = changed | filled
        del down, want_fill, filled, seed_z, reachable
        yield None
    surface = np.where(changed, final, applied)
    moved = z[changed] - surface[changed]
    edge_cut = float(np.sum(np.maximum(moved, 0.0))) * area
    edge_fill = float(np.sum(np.maximum(-moved, 0.0))) * area
    wall_max, wall_x, wall_y = 0.0, None, None
    if moved.size:
        size = np.abs(moved)
        where_rows, where_cols = np.nonzero(changed)
        top = int(np.argmax(size))
        wall_max = float(size[top])
        found_x, found_y = _places(grid, window, where_rows[top:top + 1], where_cols[top:top + 1])
        wall_x, wall_y = float(found_x[0]), float(found_y[0])
    cut_height = max(float(np.max(np.maximum(drop, 0.0), initial=0.0)), float(np.max(np.maximum(moved, 0.0), initial=0.0)))
    fill_height = max(float(np.max(np.maximum(-drop, 0.0), initial=0.0)), float(np.max(np.maximum(-moved, 0.0), initial=0.0)))
    yield None
    limit_cut = settings.cut_angle_deg + settings.tolerance_deg
    limit_fill = settings.fill_angle_deg + settings.tolerance_deg
    picked_rows: list[np.ndarray] = []
    picked_cols: list[np.ndarray] = []
    picked_deg: list[np.ndarray] = []
    per_unit = max(1, REPORT_CELLS_PER_UNIT // max(shape[1], 1))
    for first in range(0, shape[0], per_unit):
        last = min(shape[0], first + per_unit)
        band = changed[first:last]
        if band.any():
            low, high_row = max(first - 1, 0), min(last + 1, shape[0])
            start = 1 + first - low
            rows_of = slice(start, start + (last - first))
            tangents = max_tangents(padded_rows(surface, low, high_row), grid.dx, grid.dy)[rows_of, 1:shape[1] + 1]
            own = max_tangents(padded_rows(z, low, high_row), grid.dx, grid.dy)[rows_of, 1:shape[1] + 1]
            with np.errstate(invalid="ignore"):
                limit = np.where(z[first:last] > surface[first:last], limit_cut, limit_fill)
                degrees = np.degrees(np.arctan(tangents))
                over_wall = band & (degrees > limit) & (tangents > own)
            found_rows, found_cols = np.nonzero(over_wall)
            if found_rows.size:
                picked_rows.append(found_rows + first)
                picked_cols.append(found_cols)
                picked_deg.append(degrees[over_wall])
        yield None
    steep = np.zeros(shape, dtype=bool)
    walls: tuple[EdgeWall, ...] = ()
    if picked_rows:
        rows_f, cols_f = np.concatenate(picked_rows), np.concatenate(picked_cols)
        steep[rows_f, cols_f] = True
        far = ~in_reach & ~fp & np.isfinite(z)
        blocked = cut_denied | fill_denied | held
        walls = _walls(grid, window, rows_f, cols_f, np.concatenate(picked_deg), far, blocked, area)
    yield None
    outside = reaches_outside(changed, ~np.isfinite(z) & ~fp, window, grid)
    domain = transition_domain(surface, z, settings.thickness_m, cut_ok | fill_ok)
    created: EdgeReport = yield from _drain(created_steps(surface, z, domain, sub, settings.thickness_m, settings.threshold_m, settings.share_pct, budget_s=budget_s))
    order = None if quarry is None else order_check(surface, quarry.other, quarry.side, grid, window)
    # --- la afección de «preferible no afectar» (RF-017-06) ---
    avoid_cells, avoid_m2, avoid_m3, avoid_weighted = 0, 0.0, 0.0, 0.0
    if job.avoid_weight is not None:
        weight = job.avoid_weight[window]
        section_weight = weight[rows, cols]
        hit = (section_weight > 1.0) & (drop != 0.0)
        edge_weight = weight[changed]
        edge_hit = edge_weight > 1.0
        avoid_cells = int(np.count_nonzero(hit)) + int(np.count_nonzero(edge_hit))
        moved_here, moved_there = np.abs(drop[hit]), np.abs(moved[edge_hit])
        avoid_m2 = avoid_cells * area
        avoid_m3 = (float(np.sum(moved_here)) + float(np.sum(moved_there))) * area
        avoid_weighted = (float(np.sum(moved_here * section_weight[hit])) + float(np.sum(moved_there * edge_weight[edge_hit]))) * area
    notices = [*_edge_notices(name, settings, walls, outside, created, grid, window)]
    if order is not None and quarry is not None:
        notices.append(order_notice(name, quarry, order))
    if avoid_cells:
        notices.append(Notice("des.road_avoid_affected", {"entity": name, "area": avoid_m2, "volume": avoid_m3, "weighted": avoid_weighted}))
    return Engraved(
        window=window, surface=_frozen(surface), applied=_frozen(applied), footprint=fp, at_level=_frozen(at_level), cut_denied=_frozen(cut_denied),
        fill_denied=_frozen(fill_denied), too_high=_frozen(too_high), in_reach=_frozen(in_reach), changed=_frozen(changed), held=_frozen(held), steep=_frozen(steep),
        outside=_frozen(outside), off_level=tuple(groups), metric=settings.metric, cut_angle_deg=settings.cut_angle_deg, fill_angle_deg=settings.fill_angle_deg,
        mesh_factor=settings.mesh_factor, reach_m=settings.reach_m, tolerance_deg=settings.tolerance_deg, max_height_m=settings.max_height_m,
        footprint_cells=int(rows.size), section_cut_cells=int(np.count_nonzero(drop > 0.0)), section_fill_cells=int(np.count_nonzero(drop < 0.0)),
        section_cut_m3=section_cut, section_fill_m3=section_fill, edge_cut_cells=int(np.count_nonzero(moved > 0.0)), edge_fill_cells=int(np.count_nonzero(moved < 0.0)),
        edge_cut_m3=edge_cut, edge_fill_m3=edge_fill, cut_height_max_m=cut_height, fill_height_max_m=fill_height, wall_max_m=wall_max, wall_x=wall_x, wall_y=wall_y,
        walls=walls, created=created, order=order, avoid_cells=avoid_cells, avoid_m2=avoid_m2, avoid_m3=avoid_m3, avoid_weighted_m3=avoid_weighted, cell_area_m2=area,
        notices=tuple(notices))


def engrave_units(job: RoadJob, section: Section, levels: np.ndarray, project: Mapping[str, object], *, quarry: QuarryOrder | None = None,
                  budget_s: float = STEP_BUDGET_S) -> Generator[None, None, Engraved]:
    """Las unidades de :func:`engrave_steps` (cada ``yield``, una; el :class:`Engraved` es el valor de ``StopIteration``): para componerlas con otras unidades del cálculo de
    una pista con ``yield from``. Los mismos rechazos al llamar que :func:`engrave_steps`."""
    settings = _settings(job, project)
    found = _check(job, section, levels, settings, quarry)
    return _units(job, section, found, settings, quarry, budget_s)


def engrave_steps(job: RoadJob, section: Section, levels: np.ndarray, project: Mapping[str, object], *, budget_s: float = STEP_BUDGET_S, quarry: QuarryOrder | None = None
                  ) -> Iterator[Progress]:
    """**A8 y A9** (RF-017-21, RF-017-22, RF-017-23, RF-017-06; plan 017 §5.4): el grabado de la pista de ``job`` con su ``section`` (medida en la ventana de
    :func:`engrave_window`) y la rasante de cada celda de ella (``levels``: ``Section.levels(axis.stations, z)``, m, de la forma de la ventana), por pasos de ``budget_s`` como
    mucho: el último ``Progress`` (fase ``road_engrave``) lleva el :class:`Engraved`.

    ``project`` son los parámetros del proyecto que lee el borde, por su clave: la tolerancia de cara (``des.tolerance.face_deg``), el espesor mínimo
    (``res.verify.min_thickness_m``) y el salto creado admitido y su porcentaje (``des.edge.max_created_step_m``, ``des.edge.min_share``): ninguno lleva valor por defecto aquí.
    ``quarry`` es la otra superficie de la cantera de la 014 si la pista parte de una de las dos (RF-015-14).

    Rechazos al llamar, todos ``ValueError`` (errores del programa: la preparación rechazó antes lo de la persona, con su capa, su pista, su campo y su valor): una rasante o
    una sección que no son de la ventana, una sección sin celdas, una ventana que no cubre lo que el alcance puede tocar y un parámetro del proyecto que falta; al avanzar, una
    celda de la sección sin dato (RF-015-09). Ninguna entrada se modifica y no se escribe nada; cerrar el generador a mitad no deja nada."""
    work = engrave_units(job, section, levels, project, quarry=quarry, budget_s=budget_s)
    return pace_progress(work, budget_s, phase=_PHASE, running="Grabando la pista…", finished="Pista grabada")


def engrave(job: RoadJob, section: Section, levels: np.ndarray, project: Mapping[str, object], *, quarry: QuarryOrder | None = None) -> Engraved:
    """**A8 y A9**: :func:`engrave_steps` hasta el final, sin pasos: el :class:`Engraved` de la pista de ``job``. Los mismos rechazos."""
    work = engrave_units(job, section, levels, project, quarry=quarry)
    while True:
        try:
            next(work)
        except StopIteration as done:
            result: Engraved = done.value
            return result
