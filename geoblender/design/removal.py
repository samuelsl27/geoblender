# SPDX-License-Identifier: GPL-3.0-or-later
"""La retirada de un acopio: la transición y el dominio (spec 016, T17; HU-016-2; RF-016-11, RF-016-13; RNF-016-02,
RNF-016-03; plan 016 §5.4 A0 y A6; D-2, D-5; CA-10). Dominio puro: sin proyecto y sin ``bpy``.

Lo que entrega:

- :class:`RemovalJob` (el homólogo de ``platform.PlatformJob`` y ``stockpiles.StockpileJob``): todo lo que el cálculo
  necesita **ya leído** y nada del proyecto —la petición, el código de la entidad (``RMV-001``), la rejilla, la
  superficie de partida, el acopio que se retira (:class:`RemovedStockpile`: las celdas de su huella, su base y la
  superficie con que se detectó), el dominio por defecto de la 012 y los valores resueltos de la retirada— para probarlo
  sin proyecto y reproducirlo (``reproduce.py``).
- :func:`removal_window` (A0): la ventana de trabajo del acopio, la caja de su huella ampliada dos celdas
  (:func:`~.platform.work_window` con alcance 0): es lo que basta **leer** de la superficie y del dominio, y el resultado
  es el mismo, bit a bit, que con la rejilla entera.
- :func:`removal_steps` y :func:`remove_stockpile` (A6): el :class:`RemovalOutcome` con la superficie nueva, lo que se
  retira, lo que no y las cifras de RF-016-13.

**A6** (RF-016-11, RF-016-13; D-2, D-5). Con ``z`` la superficie de partida, ``B`` la base de cada celda del acopio y
``T`` la superficie con que se detectó, la **zona que se retira** ``R`` son las celdas de la huella **con dato** que están
en el **dominio por defecto** de la 012 (``MaskSet.default_domain``: perímetro ∩ límite legal − intocables), aunque su
corte no esté admitido (la excepción a RF-015-06: bajar un acopio a su base no es cortar terreno, D-5). Las **semillas**
son ``z`` en el **anillo de una celda** de ``R`` (Chebyshev: las celdas con dato que no están en ``R`` y tocan una que sí:
la superficie de fuera de la huella y la de dentro donde el dominio no admite la retirada); con ``tan(ángulo de transición)
· factor de malla`` y la métrica de la retirada (la euclídea exacta, por defecto, o el *chamfer* 5×5 de la 013), la
envolvente descendente de esas semillas es ``E = máx_s [z_s − tan · d]`` (:func:`~.edges.seed_envelope_steps`), y en ``R``

    ``z' = mín(z, máx(B, E))``,

que **ni sube ninguna celda ni baja de la base** (CA-10: ``z' ≥ mín(z, B)``) y deja lo que la partida ya bajó donde estaba
(si ``z ≤ B``, ``z' = z`` bit a bit: cuenta 0, D-2). Las demás celdas, ``z`` **bit a bit**. Sin ninguna semilla con dato
la envolvente es −∞ y la zona entera baja a ``mín(z, B)``.

**Las cifras** (RF-016-13; m³ por el área de la celda, sumadas con ``fsum`` por bandas) parten la columna que hay entre
``z`` y la base en la huella: en ``R``, lo que se **quita** ``[z', z]`` se reparte a cada lado de ``T`` —``removed_m3``,
lo del acopio (``máx(mín(z, T) − z', 0)``, entre su base y la superficie con que se detectó) y ``resting_m3``, lo que se
le apoyó después (``máx(z − máx(z', T), 0)``, por encima de ella)— y lo que **queda** sobre la base es ``transition_m3``
(``máx(z' − B, 0)``, que ocupa ``transition_m2``: las celdas con ``z' > B``); fuera de ``R``, lo que la huella tiene sobre
la base donde el dominio no admite la retirada es ``kept_m3`` (``máx(z − B, 0)`` en las celdas con dato). Las cuatro suman
:attr:`RemovalOutcome.above_base_m3` (``Σ máx(z − B, 0)`` en la huella, calculado aparte) a ≤ 10⁻⁹ relativo. Con 0 m³
retirados del acopio, el aviso ``des.removal_nothing`` (RF-016-13: el acopio ya no está en la superficie de partida). Las
celdas de la huella sin dato no cuentan, y una celda del anillo sin dato no es semilla.

**Lo que se apoyaba** (T18; RF-016-14, RF-015-15 y 17; A7; error 59): :func:`resting_on` va **hacia atrás por la cadena de superficies**
(``surface``, el grafo de la 008) desde la de partida hasta la superficie con que se detectó el acopio y atribuye lo que hay sobre él a
**cada operación que lo puso** (:func:`attribute_resting`: ``Σ máx(S_i, T) − máx(S_{i−1}, T)`` en las celdas de la huella donde esa
operación sube **más** del espesor mínimo de la 012, ``T`` la superficie con que se detectó); si la partida **no** llega a esa superficie
(viene de otra versión o del proyecto), lo que tiene por encima de ``T`` va a **esa superficie por su nombre**. La lista (:class:`Resting`,
**una sola**) se da **antes de calcular**, sin escribir nada: :func:`resting_notices` es su aviso (``des.removal_resting``) y
:func:`check_resting_confirmed`, la negativa a retirar sin la confirmación expresa (``des.removal_resting_unconfirmed``). Qué queda en
«apoyo retirado» al crear la retirada lo decide el grafo (P-9: ``design.entities``), no este módulo.

**Lo que no hace** (T19 a T21): medir la pared que queda donde el dominio no admite la retirada (A8; ``wall_max_m`` y la confirmación),
preparar, crear y reproducir la operación, ni «como plataforma» (A9). :attr:`RemovalOutcome.held` son las celdas de la huella con dato
que el dominio no admite, que es donde la T19 busca la pared.

**Leer solo la ventana** (A0; plan 016 §5.4): como ``PlatformJob``, el trabajo puede llevar la superficie y el dominio de
una ventana de la rejilla (``region``): la que da :func:`removal_window`. Las semillas están a una celda de la huella, así
que ninguna envolvente necesita más. Las coordenadas absolutas se pasan a locales respecto a la esquina de la rejilla solo
dentro del cálculo (principio 6, ADR-0005) y ninguna entrada se modifica.
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Generator, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import numpy as np

from ..core.datasets import registry as dataset_registry
from ..core.datasets.model import LIVE_STATUSES
from ..core.project.model import Progress
from ..core.provenance.figures import FigureSpec
from ..core.provenance.graph import DATASET
from ..core.versions import read as versions_read
from ..core.versions.model import Version, VersionError
from ..gis.grid import Grid
from ..gis.masks.compile import STEP_BUDGET_S
from ..gis.messages import GisError
from . import entities
from .edges import seed_envelope_steps
from .envelopes import CELLS_PER_UNIT, SlopeField
from .grids import dilate_square
from .messages import DesignError, render
from .model import Direction, Metric, RemovalRequest
from .params import RemovalParam, check_entity_param, entity_params, entity_params_of
from .platform import Window, _shaped_array, _whole, _window_of, window_part, work_window
from .preview import SUMMARY_ITEMS, Notice
from .provenance import SURFACE_ROLE, removal_figures
from .seeds import pace_progress
from .stockpiles import Stockpile, window_grid
from .store import _min_thickness
from .surfaces import project_frame, read_surface_window

if TYPE_CHECKING:
    from ..gis.store import StoreProject

__all__ = [
    "RemovalJob",
    "RemovalOutcome",
    "RemovedStockpile",
    "Resting",
    "RestingShare",
    "attribute_resting",
    "check_resting_confirmed",
    "remove_stockpile",
    "removal_steps",
    "removal_window",
    "resting_notices",
    "resting_on",
]

_PHASE = "removal"
_NOTHING = "des.removal_nothing"


# --- Lo leído ----------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class RemovedStockpile:
    """El acopio que se retira, ya leído de su detección (plan 016 §5.2.3: su tabla de acopios, su base y la superficie con
    que se detectó, que son datos dispersos): su ``key`` (la de su marca, ``m07``) y su ``name``; las ``cells`` de su
    huella en la rejilla entera (``fila · ncols + columna``, ``int64``, **estrictamente crecientes**: no se repite ninguna,
    como :attr:`~.stockpiles.Stockpile.cells`) y, una por celda y en ese orden, su ``base`` (m, finita: el plano de su
    corona o su base propia) y la ``surface`` con que se detectó (m, finita). ``ValueError`` (errores del programa) si no
    cumple algo de esto o no tiene ninguna celda."""

    key: str
    name: str
    cells: np.ndarray
    base: np.ndarray
    surface: np.ndarray

    def __post_init__(self) -> None:
        for attr in ("key", "name"):
            value = getattr(self, attr)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"«{attr}» del acopio que se retira es un texto con algo, no {value!r}")
        cells = np.asarray(self.cells)
        if cells.ndim != 1 or cells.size == 0:
            raise ValueError("el acopio que se retira lleva sus celdas en un vector con al menos una")
        if cells.dtype.kind not in "iu":
            raise ValueError(f"las celdas del acopio son enteros (fila · columnas + columna), no {cells.dtype}")
        cells = cells.astype(np.int64, copy=False)
        if cells[0] < 0 or (cells.size > 1 and not np.all(cells[1:] > cells[:-1])):
            raise ValueError("las celdas del acopio van en orden creciente, sin repetir ninguna ni salirse de la rejilla")
        object.__setattr__(self, "cells", cells)
        for attr in ("base", "surface"):
            values = np.asarray(getattr(self, attr), dtype=np.float64)
            if values.shape != cells.shape:
                raise ValueError(f"«{attr}» del acopio es de la forma de sus celdas {cells.shape}, no {values.shape}")
            if not np.all(np.isfinite(values)):
                raise ValueError(f"«{attr}» del acopio tiene celdas sin dato: una huella solo tiene celdas con base y "
                                 "con superficie de detección")
            object.__setattr__(self, attr, values)

    @classmethod
    def of(cls, item: Stockpile) -> RemovedStockpile:
        """El acopio detectado ``item`` (:class:`~.stockpiles.Stockpile`) tal como se retira: su clave, su nombre, las celdas
        de su huella, su base y la superficie con que se detectó, sin copiarlas."""
        return cls(item.key, item.name, item.cells, item.base, item.surface)


def removal_window(stockpile: RemovedStockpile, grid: Grid) -> Window:
    """**A0** (plan 016 §5.4): la ventana de trabajo de la retirada de ``stockpile`` en ``grid``: la caja de su huella
    ampliada dos celdas, recortada a la rejilla (:func:`~.platform.work_window` con alcance 0: las semillas están a una
    celda de la huella). Es lo que basta leer de la superficie de partida y del dominio, y el cálculo no toca nada fuera de
    ella. ``ValueError`` si alguna celda del acopio no es de la rejilla."""
    cells = stockpile.cells
    if int(cells[-1]) >= grid.nrows * grid.ncols:
        raise ValueError(f"el acopio «{stockpile.name}» tiene celdas fuera de la rejilla de {grid.nrows} × {grid.ncols}")
    rows, cols = np.divmod(cells, grid.ncols)
    return work_window(slice(int(rows.min()), int(rows.max()) + 1), slice(int(cols.min()), int(cols.max()) + 1), 0.0, grid)


@dataclass(frozen=True, slots=True, eq=False)
class RemovalJob:
    """Lo que necesita calcular una retirada, ya leído y sin proyecto (plan 016 §5.3.1): la ``request`` (su nombre y el
    acopio que se retira), el ``code`` de la entidad (``RMV-001``, para nombrar la clave de un parámetro en un rechazo), la
    rejilla (``grid``), la superficie de partida ``start`` (m, float64; ``NaN``, sin dato), el ``stockpile``
    (:class:`RemovedStockpile`), el dominio por defecto de la versión (``domain``: ``MaskSet.default_domain``, una máscara
    booleana: donde se puede retirar, D-5) y los valores resueltos (``values``: por último segmento de su clave, los de
    :class:`~.params.RemovalParam`: ``transition_deg`` —sin valor por defecto: D-2—, ``mesh_factor`` y ``metric``).

    ``start`` y ``domain`` son de la **rejilla entera** o, con ``region``, de **esa ventana** de la rejilla (A0: la de
    :func:`removal_window` basta); se piden por coordenadas de la rejilla con :meth:`start_in` y :meth:`domain_in`.
    ``ValueError`` (errores del programa) si el código no es el de una retirada, una clave no es de una retirada, un array
    no es de su forma, el acopio no cabe en la rejilla o ``region`` no cubre la ventana de trabajo."""

    request: RemovalRequest
    code: str
    grid: Grid
    start: np.ndarray
    stockpile: RemovedStockpile
    domain: np.ndarray
    values: Mapping[str, object]
    region: Window | None = None

    def __post_init__(self) -> None:
        kind = entity_params_of(self.code).kind
        if kind != "removal":
            raise ValueError(f"el código {self.code!r} no es el de una retirada de acopio (es de {kind})")
        if self.region is not None:
            object.__setattr__(self, "region", _window_of(self.region, self.grid))
        window = self.window
        shape = (window[0].stop - window[0].start, window[1].stop - window[1].start)
        where = "de la rejilla" if self.region is None else "de su ventana"
        object.__setattr__(self, "start", _shaped_array(self.start, shape, np.float64, "la superficie de partida", where))
        object.__setattr__(self, "domain", _shaped_array(self.domain, shape, np.bool_, "el dominio", where))
        known = {param.value for param in RemovalParam}
        unknown = sorted(set(self.values) - known)
        if unknown:
            raise ValueError(f"los valores de una retirada son de {', '.join(sorted(known))}, no «{unknown[0]}»")
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))
        needed = removal_window(self.stockpile, self.grid)
        if self.region is not None:
            window_part(self.start, self.region, needed)  # ValueError: se leyó menos de lo que el cálculo toca

    @property
    def window(self) -> Window:
        """La ventana de la rejilla que cubren ``start`` y ``domain``: ``region`` o, sin ella, la rejilla entera."""
        return _whole(self.grid) if self.region is None else self.region

    def _in(self, array: np.ndarray, window: Window) -> np.ndarray:
        return array[window] if self.region is None else window_part(array, self.region, window)

    def start_in(self, window: Window) -> np.ndarray:
        """La superficie de partida en ``window`` (filas y columnas de la rejilla): una vista; ``ValueError`` si ``window``
        no está dentro de lo leído."""
        return self._in(self.start, window)

    def domain_in(self, window: Window) -> np.ndarray:
        """El dominio en ``window`` (como :meth:`start_in`)."""
        return self._in(self.domain, window)


@dataclass(frozen=True, slots=True)
class _Settings:
    """Lo que lee A6 de los valores de la retirada, ya comprobado."""

    angle_deg: float
    mesh_factor: float
    metric: Metric

    @property
    def tan(self) -> float:
        """La tangente efectiva de la envolvente: ``tan(ángulo de transición) · factor de malla``."""
        return math.tan(math.radians(self.angle_deg)) * self.mesh_factor


def _settings(job: RemovalJob) -> _Settings:
    """El ángulo de transición (obligatorio: D-2), el factor de malla y la métrica de ``job``, comprobados
    (``des.entity_param_missing``, ``_range`` o ``_choice``, nombrando la retirada, la clave y el valor; el factor de malla
    y la métrica toman el valor por defecto de su parámetro si no se dan: 1,0 y la euclídea exacta). La «capa» de los
    mensajes es el acopio que se retira."""
    name, code, found, layer = job.request.name, job.code, job.values, job.request.stockpile
    spec = entity_params("removal")
    angle = check_entity_param(name, code, RemovalParam.TRANSITION, found.get(RemovalParam.TRANSITION.value), layer=layer)
    mesh = found.get(RemovalParam.MESH_FACTOR.value)
    if mesh is None:
        mesh = spec.template(RemovalParam.MESH_FACTOR.value).default
    mesh = check_entity_param(name, code, RemovalParam.MESH_FACTOR, mesh, layer=layer)
    metric = found.get(RemovalParam.METRIC.value)
    if metric is None:
        metric = spec.template(RemovalParam.METRIC.value).default
    metric = check_entity_param(name, code, RemovalParam.METRIC, str(metric), layer=layer)
    assert isinstance(angle, float) and isinstance(mesh, float) and isinstance(metric, str)
    return _Settings(angle, mesh, Metric(metric))


# --- Lo que da ---------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class RemovalOutcome:
    """La retirada de un acopio (A6; RF-016-11, RF-016-13), en su ventana de trabajo (``window``: filas y columnas de la
    rejilla, :func:`removal_window`; todas las rejillas de abajo son de su forma): la ``surface`` nueva (m, float64; ``z``
    bit a bit donde no se retira), la ``footprint`` (la huella del acopio), ``admitted`` (lo que se retira: la huella con dato
    dentro del dominio), ``held`` (la huella con dato que el dominio **no** admite retirar: lo que queda sin retirar, donde
    busca la pared la T19) y ``seeds`` (el anillo de una celda de lo que se retira, donde nace la envolvente).

    Las cifras (m³ salvo ``transition_m2``, m²): ``removed_m3`` (lo del acopio, entre su base y la superficie con que se
    detectó), ``resting_m3`` (lo que se le apoyó, por encima de ella), ``transition_m3`` (lo que la envolvente deja sobre la
    base), ``kept_m3`` (lo no retirado donde el dominio no lo admite) y ``transition_m2``; suman ``above_base_m3`` (lo que
    la huella tenía sobre la base) a ≤ 10⁻⁹ relativo. ``wall_max_m`` es la mayor pared que deja (``None`` mientras no se
    mida: T19). ``transition_deg``, ``mesh_factor`` y ``metric`` son los de la retirada, ``cell_area_m2`` el área de una
    celda y ``notices`` los avisos (``des.removal_nothing`` con 0 m³ retirados)."""

    name: str
    code: str
    stockpile: str
    stockpile_name: str
    window: Window
    surface: np.ndarray
    footprint: np.ndarray
    admitted: np.ndarray
    held: np.ndarray
    seeds: np.ndarray
    removed_m3: float
    resting_m3: float
    transition_m3: float
    kept_m3: float
    above_base_m3: float
    transition_m2: float
    transition_deg: float
    mesh_factor: float
    metric: Metric
    cell_area_m2: float
    wall_max_m: float | None = None
    notices: tuple[Notice, ...] = ()

    @property
    def figures(self) -> tuple[FigureSpec, ...]:
        """Las cifras CALCULADO de la operación (:func:`~.provenance.removal_figures`, con el ámbito de la entidad y en el
        orden de ``REMOVAL_FIGURES``): ``des.rmv_removed_m3``, ``_resting_m3``, ``_transition_m3``, ``_kept_m3``,
        ``_transition_m2`` y, si se midió, ``_wall_max_m``."""
        return removal_figures(self.name, self.code, {
            "des.rmv_removed_m3": self.removed_m3, "des.rmv_resting_m3": self.resting_m3,
            "des.rmv_transition_m3": self.transition_m3, "des.rmv_kept_m3": self.kept_m3,
            "des.rmv_transition_m2": self.transition_m2, "des.rmv_wall_max_m": self.wall_max_m})

    def compose(self, start: np.ndarray) -> np.ndarray:
        """La superficie entera que deja la retirada: una rejilla **nueva** igual a ``start`` (la superficie de partida, de
        la rejilla entera) con la ventana de trabajo sustituida por :attr:`surface`. ``ValueError`` si ``start`` no es una
        rejilla que contenga la ventana."""
        whole = np.array(start, dtype=np.float64, copy=True)
        rows, cols = self.window
        if whole.ndim != 2 or rows.stop > whole.shape[0] or cols.stop > whole.shape[1]:
            raise ValueError(f"la superficie de partida {whole.shape} no contiene la ventana de la retirada "
                             f"({rows}, {cols})")
        whole[self.window] = self.surface
        return whole


# --- A6 ----------------------------------------------------------------------------------------------------------


def _removal_units(job: RemovalJob, settings: _Settings) -> Generator[None, None, RemovalOutcome]:
    """Las unidades de :func:`removal_steps`: la huella y el dominio en la ventana, las semillas, la envolvente
    descendente y, por bandas de filas, la superficie nueva con sus cifras."""
    item, grid = job.stockpile, job.grid
    window = removal_window(item, grid)
    shape = (window[0].stop - window[0].start, window[1].stop - window[1].start)
    z = job.start_in(window)
    allowed = job.domain_in(window)
    rows, cols = np.divmod(item.cells, grid.ncols)
    rows, cols = rows - window[0].start, cols - window[1].start
    footprint = np.zeros(shape, dtype=bool)
    footprint[rows, cols] = True
    base = np.full(shape, np.nan)
    base[rows, cols] = item.base
    detected = np.full(shape, np.nan)
    detected[rows, cols] = item.surface
    del rows, cols
    yield None
    with np.errstate(invalid="ignore"):
        has_data = np.isfinite(z)
    admitted = footprint & allowed & has_data
    held = footprint & ~admitted & has_data
    seeds = dilate_square(admitted, 1) & ~admitted & has_data
    seed = np.where(seeds, z, np.nan)
    sub = window_grid(grid, window)
    yield None
    envelope = yield from seed_envelope_steps(seed, sub, SlopeField(settings.tan), settings.metric, Direction.DOWN,
                                              f"{job.request.name} (retirada del acopio)")
    del seed
    surface = np.array(z, dtype=np.float64, copy=True)
    parts: dict[str, list[float]] = {name: [] for name in ("removed", "resting", "transition", "kept", "above")}
    transition_cells = 0
    step = max(1, CELLS_PER_UNIT // max(shape[1], 1))
    for first in range(0, shape[0], step):
        band = slice(first, first + step)
        level, floor, top, bottom = z[band], base[band], detected[band], envelope[band]
        moves, stays = admitted[band], held[band]
        with np.errstate(invalid="ignore"):
            new = np.where(moves, np.minimum(level, np.maximum(floor, bottom)), level)
            surface[band] = new
            parts["removed"].append(float(np.where(moves, np.maximum(np.minimum(level, top) - new, 0.0), 0.0).sum()))
            parts["resting"].append(float(np.where(moves, np.maximum(level - np.maximum(new, top), 0.0), 0.0).sum()))
            left = np.where(moves, np.maximum(new - floor, 0.0), 0.0)
            parts["transition"].append(float(left.sum()))
            transition_cells += int(np.count_nonzero(left > 0.0))
            parts["kept"].append(float(np.where(stays, np.maximum(level - floor, 0.0), 0.0).sum()))
            parts["above"].append(float(np.where(footprint[band] & has_data[band],
                                                 np.maximum(level - floor, 0.0), 0.0).sum()))
        yield None
    area = grid.cell_area
    removed, resting, transition, kept, above = (math.fsum(parts[name]) * area for name in parts)
    notices = (Notice(_NOTHING, {"stockpile": item.name}),) if removed == 0.0 else ()
    return RemovalOutcome(job.request.name, job.code, item.key, item.name, window, surface, footprint, admitted, held,
                          seeds, removed, resting, transition, kept, above, transition_cells * area,
                          settings.angle_deg, settings.mesh_factor, settings.metric, area, None, notices)


def removal_steps(job: RemovalJob, *, budget_s: float = STEP_BUDGET_S) -> Iterator[Progress]:
    """**A6** (RF-016-11, RF-016-13; plan 016 §5.4): la retirada de ``job`` por pasos de ``budget_s`` como mucho (RNF-016-03:
    ≤ 0,2 s cada llamada): el último ``Progress`` (fase ``removal``) lleva el :class:`RemovalOutcome`.

    Las semillas son ``z`` en el anillo de una celda de lo que se retira (la huella con dato dentro del dominio por
    defecto, D-5); con ``tan(ángulo de transición) · factor de malla`` y la métrica de la retirada, ``E`` es la envolvente
    descendente de esas semillas y, en lo que se retira, ``z' = mín(z, máx(base, E))``: nada sube, nada baja de la base
    (CA-10) y lo que la partida ya bajó cuenta 0 (D-2); lo demás, ``z`` bit a bit. Da el retirado del acopio, lo que se le
    apoyaba, la transición, lo que no se retira donde las máscaras no lo admiten y el área de la transición (RF-016-13).

    Rechazos **al llamar**, nombrando la retirada, la clave del campo y el valor (RF-015-08): sin ángulo de transición
    (``des.entity_param_missing``: D-2, no se elige uno por la persona), fuera de (0; 90)° o con un factor de malla fuera de
    su rango (``des.entity_param_range``) o una métrica que no es de la lista (``des.entity_param_choice``). Ninguna entrada
    se modifica y no se escribe nada; cerrar el generador a mitad no deja nada."""
    settings = _settings(job)
    return pace_progress(_removal_units(job, settings), budget_s, phase=_PHASE,
                         running="Calculando la retirada del acopio…", finished="Retirada del acopio calculada")


def remove_stockpile(job: RemovalJob) -> RemovalOutcome:
    """**A6**: :func:`removal_steps` hasta el final, sin pasos: el :class:`RemovalOutcome` de ``job``. Los mismos
    rechazos."""
    work = _removal_units(job, _settings(job))
    while True:
        try:
            next(work)
        except StopIteration as done:
            return done.value  # type: ignore[no-any-return]


# --- A7: lo que se apoyaba ----------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RestingShare:
    """Lo que atribuye :func:`attribute_resting` a un nivel de la cadena: las ``cells`` de la huella donde sube más del espesor mínimo y
    el volumen (``volume_m3``) que pone en ellas (m³)."""

    cells: int
    volume_m3: float


def attribute_resting(floor: np.ndarray, levels: Sequence[np.ndarray], min_thickness_m: float, cell_area: float
                      ) -> tuple[RestingShare, ...]:
    """**A7** (RF-016-14, RF-015-15; plan 016 §5.4; puro y vectorizado): lo que cada nivel de una cadena de superficies pone **sobre un acopio**.

    ``floor`` es ``T``, la superficie con que se detectó el acopio, y ``levels`` las superficies de la cadena, **de la más antigua a la
    de partida** (cada una, en las celdas de la huella, del mismo tamaño que ``floor``; ``NaN``, sin dato). Con ``S_0`` el primer nivel
    comparado con ``T`` (``S_{−1} = T``), el nivel ``k`` recibe

        ``Σ [máx(S_k, T) − máx(S_{k−1}, T)] · cell_area``  en las celdas donde esa diferencia es **mayor** que ``min_thickness_m``,

    el mismo criterio que ``entities.detect_supports`` (la diferencia es ``S_k − máx(S_{k−1}, T)`` donde sube): una operación que
    **baja** la superficie no recibe nada, una que rellena después de un corte recibe lo que pone por encima de ``T``, y la suma de lo
    atribuido **telescopa** (con cada subida por encima del espesor mínimo, es lo que la partida tiene por encima de ``T``). Una celda
    sin dato en alguna de las superficies no cuenta. Devuelve un :class:`RestingShare` por nivel, en su orden; las sumas, con
    ``math.fsum`` (a ≤ 10⁻⁹ relativo del cálculo a mano). Ninguna entrada se modifica. ``ValueError`` (errores del programa) si un nivel no
    es de la forma de ``floor``, el espesor no es un número finito no negativo o el área no es positiva."""
    thickness = float(min_thickness_m)
    area = float(cell_area)
    if not math.isfinite(thickness) or thickness < 0.0:
        raise ValueError(f"el espesor mínimo es un número finito no negativo, no {min_thickness_m!r}")
    if not math.isfinite(area) or area <= 0.0:
        raise ValueError(f"el área de una celda es un número finito mayor que cero, no {cell_area!r}")
    ground = np.asarray(floor, dtype=np.float64)
    before = ground
    found: list[RestingShare] = []
    for level in levels:
        values = np.asarray(level, dtype=np.float64)
        if values.shape != ground.shape:
            raise ValueError(f"el nivel de la cadena {values.shape} no es de la forma de la superficie del acopio {ground.shape}")
        with np.errstate(invalid="ignore"):
            above = np.maximum(values, ground)
            rise = above - before
            counted = rise > thickness  # NaN no es mayor que nada: la celda sin dato no cuenta
        cells = int(np.count_nonzero(counted))
        found.append(RestingShare(cells, math.fsum(rise[counted].tolist()) * area if cells else 0.0))
        before = above
    return tuple(found)


@dataclass(frozen=True, slots=True)
class Resting:
    """Una fila de la lista de lo que se apoya en el acopio que se retira (RF-016-14, RF-015-17; **una sola lista**): el ``name`` de quien
    lo puso —la entidad o el diseño de la versión— o, si la cadena de la partida no llega a la superficie con que se detectó el acopio, el
    de **la superficie** (``op_type`` ``None``: la de otra versión o del proyecto, por su nombre), el ``volume_m3`` que puso sobre el acopio,
    las ``cells`` de su huella donde lo puso, el nombre del dato de la ``surface`` que dejó y, si es de una operación, su ``operation_uid`` y,
    si es una entidad, su código (``entity``)."""

    name: str
    op_type: str | None
    volume_m3: float
    cells: int
    surface: str
    operation_uid: str | None = None
    entity: str | None = None

    def kind(self, language: str = "es") -> str | None:
        """El tipo de lo que lo puso («Plataforma», «Solo relleno») en ``language``; ``None`` si es una superficie."""
        return None if self.op_type is None else entities.kind_label(self.op_type, language)

    def text(self, language: str = "es") -> str:
        """La fila como una línea de la lista, en ``language``: «Sobre el acopio 4 (Plataforma): 2 590 m³ apoyados» o, de una superficie,
        «des_psf_… (superficie de partida): 2 590 m³ apoyados»."""
        volume = round(self.volume_m3)
        if self.op_type is None:
            return render("des.removal_resting_surface", language=language, name=self.name, volume=volume)
        return render("des.entity_dependent_volume", language=language, name=self.name, kind=self.kind(language), volume=volume)


def resting_notices(stockpile: str, found: Iterable[Resting]) -> tuple[Notice, ...]:
    """El aviso de lo que se apoya en el acopio ``stockpile`` (RF-016-14, RF-015-17), antes de calcular: **una** nota
    ``des.removal_resting`` con el total de m³ y los nombres de lo que lo puso (las :data:`~.preview.SUMMARY_ITEMS` primeras y un «…» si hay
    más); ninguna si no hay nada."""
    rows = tuple(found)
    if not rows:
        return ()
    names = [f"«{row.name}»" for row in rows]
    shown = (*names[:SUMMARY_ITEMS], *(("…",) if len(names) > SUMMARY_ITEMS else ()))
    return (Notice("des.removal_resting", {"stockpile": stockpile, "volume": math.fsum(row.volume_m3 for row in rows),
                                            "items": shown}),)


def check_resting_confirmed(stockpile: str, found: Iterable[Resting], *, confirmed: bool) -> None:
    """**No se retira sin la confirmación expresa** (RF-016-14, RF-015-17; error 59): con algo apoyado en el acopio ``stockpile`` y sin
    ``confirmed``, ``des.removal_resting_unconfirmed`` con el acopio y el total de m³ (``DesignError``); con confirmación, o sin nada
    apoyado, no hace nada. No escribe."""
    rows = tuple(found)
    if rows and not confirmed:
        raise DesignError("des.removal_resting_unconfirmed", obj=f"Retirada del acopio «{stockpile}»", field="confirmación",
                          value=False, stockpile=stockpile, volume=math.fsum(row.volume_m3 for row in rows))


@dataclass(frozen=True, slots=True)
class _Node:
    """Una superficie de la cadena de la partida (de la más reciente a la más antigua): el nombre de su dato (``name``), la versión en la que
    está (``owner``: el uid de la versión o ``''``, del proyecto) y, si la escribió una operación **hecha de esta versión**, su ``operation``,
    su ``op_type``, su ``label`` (el nombre de sus ajustes) y su código de entidad."""

    name: str
    owner: str
    operation: str | None = None
    op_type: str | None = None
    label: str | None = None
    entity: str | None = None


_CHAIN_LIMIT = 256
"""Las superficies que se siguen hacia atrás como mucho (contra un ciclo de datos rotos)."""
_PRODUCER = (
    "SELECT o.op_type, o.settings, o.status, r.version_uid FROM gb_operation AS o "
    "LEFT JOIN gb_revision AS r ON r.uid = o.revision_uid WHERE o.uid = ?")
_START_OF = (
    "SELECT item_uid FROM gb_operation_io WHERE operation_uid = ? AND direction = 'in' AND item_kind = ? AND role = ? "
    "ORDER BY fid LIMIT 1")
_ANY_VERSION = "SELECT uid FROM gb_dataset WHERE name = ? AND status IN ({marks}) ORDER BY version_uid, rowid LIMIT 1"
_OWNER_OF = "SELECT version_uid FROM gb_dataset WHERE uid = ?"


def _live(conn: sqlite3.Connection, name: str, version: Version) -> tuple[Any, str] | None:
    """El dato vivo de la superficie ``name`` y la versión en la que está (``''``: del proyecto): el de ``version`` o, si no lo tiene, el del
    proyecto y, si no, el de **cualquier otra versión** (una superficie de otra versión, por su nombre); ``None`` si no hay ninguno."""
    record = dataset_registry.get(conn, name, version_uid=version.uid)
    if record is None or not record.live:
        record = dataset_registry.get(conn, name)
    if record is None or not record.live:
        marks = ", ".join("?" for _ in LIVE_STATUSES)
        row = conn.execute(_ANY_VERSION.format(marks=marks), (name, *(str(status) for status in LIVE_STATUSES))).fetchone()
        record = None if row is None else dataset_registry.get(conn, str(row[0]))
    if record is None or not record.live:
        return None
    (owner,) = conn.execute(_OWNER_OF, (record.uid,)).fetchone()
    return record, str(owner)


def _node(conn: sqlite3.Connection, record: Any, owner: str, version: Version) -> _Node:
    """La superficie ``record`` de la cadena con lo que la escribió, si fue una operación hecha de ``version``."""
    row = conn.execute(_PRODUCER, (record.operation_uid,)).fetchone()
    if row is None or str(row[2]) != "done" or row[3] is None or str(row[3]) != version.uid:
        return _Node(record.name, owner)
    settings = json.loads(str(row[1])) if row[1] else {}
    name = settings.get("name") if isinstance(settings, dict) else None
    code = settings.get("code") if isinstance(settings, dict) else None
    entity: str | None = None
    if isinstance(code, str):
        try:
            entities.kind_of_code(code)
            entity = code
        except ValueError:  # un código que no es de una entidad (los diseños de la 013 y la 014 no lo llevan)
            entity = None
    label = name if isinstance(name, str) and name else str(row[0])
    return _Node(record.name, owner, str(record.operation_uid), str(row[0]), label, entity)


def _surface_chain(conn: sqlite3.Connection, version: Version, start: str, detected_on: str) -> tuple[_Node, ...]:
    """La cadena de superficies de ``start`` **hacia atrás** (del grafo de la 008, la entrada ``surface`` de la operación que escribió cada
    una), de la más reciente (la de partida) a la más antigua: se detiene en la superficie con que se detectó el acopio (``detected_on``), en
    la que no escribió una operación hecha de ``version`` (la de otra versión o del proyecto, por su nombre) y en la que no tiene superficie de
    partida. ``gis.dataset_unknown`` si ``start`` no existe."""
    chain: list[_Node] = []
    seen: set[str] = set()
    name = start
    while len(chain) < _CHAIN_LIMIT and name not in seen:
        seen.add(name)
        found = _live(conn, name, version)
        if found is None:
            if not chain:
                raise GisError("gis.dataset_unknown", obj="Superficie de partida", field="superficie", value=name)
            break
        record, owner = found
        node = _node(conn, record, owner, version)
        chain.append(node)
        if node.name == detected_on or node.operation is None:
            break
        row = conn.execute(_START_OF, (node.operation, DATASET, SURFACE_ROLE)).fetchone()
        previous = None if row is None else dataset_registry.successor(conn, str(row[0]))
        if previous is None:
            break
        name = previous.name
    return tuple(chain)


def resting_on(project: StoreProject, version: Version | str, stockpile: RemovedStockpile, start: str, *, detected_on: str
               ) -> tuple[Resting, ...]:
    """**A7, lo que se apoyaba** en el acopio ``stockpile`` (RF-016-14, RF-015-15 y 17; plan 016 §5.4; error 59): la lista **antes de calcular**,
    sin escribir nada, de lo que hay sobre él en la superficie de partida ``start`` (el nombre de su dato; la que se retira) de la versión
    ``version`` (uid o código), atribuido a **quien lo puso**.

    Va hacia atrás por la cadena de superficies de ``start`` (:func:`_surface_chain`) hasta la superficie con que se detectó el acopio
    (``detected_on``: la ``surface`` de su detección) y, con las celdas de su huella, ``T`` (``stockpile.surface``) y el espesor mínimo de la
    012 de la versión, cada operación de la versión que dejó una superficie recibe lo que sube sobre el acopio (:func:`attribute_resting`);
    las superficies que no escribió una operación de la versión, al final de la cadena (**una partida de otra versión o del proyecto**: lo que
    tiene por encima de ``T``), reciben lo suyo **por su nombre** (``op_type`` ``None``). Una fila por operación o superficie con algo
    apoyado, de la más antigua a la de partida: lo que puso cada una, no lo que queda (una que baja lo de otra no le resta). Lee solo la
    ventana de la huella de cada superficie de la cadena. Los rechazos de leer una superficie (``gis.dataset_unknown``,
    ``des.surface_mismatch``, ``des.surface_is_tin``…) y ``VersionError`` si la versión no existe; ``ValueError`` si alguna celda del acopio no
    es de la rejilla del proyecto."""
    with project.read() as conn:
        found = versions_read.version(conn, version) if isinstance(version, str) else version
        if found is None:
            raise VersionError("core.version_unknown", field="versión", value=version, version=version)
        thickness = _min_thickness(conn, project, found)
        chain = _surface_chain(conn, found, start, detected_on)
    frame = project_frame(project)
    grid = frame.grid
    cells = stockpile.cells
    if int(cells[-1]) >= grid.nrows * grid.ncols:
        raise ValueError(f"el acopio «{stockpile.name}» tiene celdas fuera de la rejilla de {grid.nrows} × {grid.ncols}")
    rows, cols = np.divmod(cells, grid.ncols)
    window = (slice(int(rows.min()), int(rows.max()) + 1), slice(int(cols.min()), int(cols.max()) + 1))
    inside = (rows - window[0].start, cols - window[1].start)
    oldest_first = tuple(reversed(chain))
    levels = [read_surface_window(project, node.name, window, version_uid=node.owner, expect=frame,
                                  role="superficie de la cadena de la partida").values[inside] for node in oldest_first]
    shares = attribute_resting(stockpile.surface, levels, thickness, grid.cell_area)
    result: list[Resting] = []
    for node, share in zip(oldest_first, shares, strict=True):
        if share.cells == 0 or node.name == detected_on:  # la superficie con que se detectó es el suelo, no lo apoyado
            continue
        if node.operation is None or node.op_type is None:
            result.append(Resting(node.name, None, share.volume_m3, share.cells, node.name))
        else:
            result.append(Resting(node.label or node.op_type, node.op_type, share.volume_m3, share.cells, node.name, node.operation,
                                  node.entity))
    return tuple(result)
