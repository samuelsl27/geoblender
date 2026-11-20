# SPDX-License-Identifier: GPL-3.0-or-later
"""La retirada de un acopio: la transición, el dominio, lo que se apoyaba y la pared (spec 016, T17 a T19; HU-016-2; RF-016-11,
RF-016-13 a RF-016-15; RNF-016-02, RNF-016-03; plan 016 §5.4 A0, A6, A7 y A8; D-2, D-5, D-6; CA-9, CA-10). Dominio puro: sin proyecto y
sin ``bpy``.

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
retirados del acopio, el aviso ``des.removal_nothing`` (RF-016-13: el acopio ya no está en la superficie de partida) y, con ``kept_m3 > 0``,
``des.removal_kept`` (T48, hallazgo B-2: lo que las máscaras no dejan retirar, con su volumen y el centro de las celdas donde queda). Las
celdas de la huella sin dato no se retiran ni cuentan, y una celda del anillo sin dato no es semilla. **La retirada tolera esas celdas** (la
excepción de la 016 a RF-015-09, spec 0.4: ninguna cifra cambia y no impide crear) **pero las avisa con su lugar** (T53, decisión 8 de «Para
Samuel», 20/11/2026; RF-015-13): ``des.removal_no_data`` con cuántas son, su área y la primera, después de los dos avisos anteriores
(:func:`~.supported_edge.no_data_notice`; solo las de la huella, no las del anillo).

**Lo que se apoyaba** (T18; RF-016-14, RF-015-15 y 17; A7; error 59): :func:`resting_on` va **hacia atrás por la cadena de superficies**
(``surface``, el grafo de la 008) desde la de partida hasta la superficie con que se detectó el acopio y atribuye lo que hay sobre él a
**cada operación que lo puso** (:func:`attribute_resting`: ``Σ máx(S_i, T) − máx(S_{i−1}, T)`` en las celdas de la huella donde esa
operación sube **más** del espesor mínimo de la 012, ``T`` la superficie con que se detectó); si la partida **no** llega a esa superficie
(viene de otra versión o del proyecto), lo que tiene por encima de ``T`` va a **esa superficie por su nombre**. La lista (:class:`Resting`,
**una sola**) se da **antes de calcular**, sin escribir nada: :func:`resting_notices` es su aviso (``des.removal_resting``) y
:func:`check_resting_confirmed`, la negativa a retirar sin la confirmación expresa (``des.removal_resting_unconfirmed``). Qué queda en
«apoyo retirado» al crear la retirada lo decide el grafo (P-9: ``design.entities``), no este módulo; **lo que la retirada anota** de la lista, para que
lo lea (T45; hallazgos S-1 y B-1), lo da :func:`resting_record` (una fila por operación de la versión).

**La pared** (T19; RF-016-15; A8; D-6; CA-9; errores 41 y 47): :func:`measure_wall` (y :func:`wall_steps`, por pasos) mide, sobre el
:class:`RemovalOutcome` de A6, la pared que queda en el borde de lo retirado y la deja en :attr:`RemovalOutcome.wall` (:class:`Wall`) y
en ``wall_max_m`` (la altura de la mayor, 0 m si ninguna). Una **pareja** es de dos celdas vecinas (4 vecinos) con dato, una movida por la
retirada (en lo que se retira, con ``|z' − z|`` mayor que el espesor mínimo de la 012) y la otra no; su **salto creado** es el de la 014
(:mod:`~.edges`, A11: ``|S_a − S_b| − |z_a − z_b|``, de modo que lo que el terreno ya tenía no cuenta) y su **inclinación**,
``atan(|S_a − S_b| / distancia)``. Cuentan las parejas con un salto creado mayor que el **salto admitido** de la 014
(``des.edge.max_created_step_m``) y una inclinación mayor que el **ángulo de transición más la tolerancia de cara** de la 013
(``des.tolerance.face_deg``); sus celdas forman los **tramos** (4-conexos, numerados de norte a sur y de oeste a este). De cada tramo se da la
**altura recorriendo la cara** (la mayor cota de las celdas de sus parejas menos la menor, no el relieve local de una pareja: error 41), la
inclinación de su **peor pareja**, su mayor salto creado y el lugar de esa pareja (:class:`WallStretch`). El aviso (``des.removal_wall``,
:func:`wall_notices`) es del tramo más alto y la retirada **no se crea sin la confirmación expresa** de la persona
(:func:`check_wall_confirmed`: ``des.removal_wall_unconfirmed``); con una pared de **más de** :data:`WALL_REASON_MIN_ANGLE_DEG` y de
:data:`WALL_REASON_MIN_HEIGHT_M` **o más**, tampoco sin un **motivo** que queda registrado (``des.removal_wall_reason``; ``wall_reason`` y su
evento los escribe la orden, T20).

**Los dos umbrales de CA-9 no son parámetros** (decisión de la sesión principal, 18/11/2026, revisable; D-6 y CA-9 de la spec 016, que no los
da como editables): son las constantes :data:`WALL_REASON_MIN_ANGLE_DEG` (45°) y :data:`WALL_REASON_MIN_HEIGHT_M` (3 m), con su procedencia
junto a cada una y su **tipo** (T48; hallazgos B-4 y S-8; principio 2: una cifra sin tipo no se escribe): :data:`WALL_REASON_KIND` (ADOPTADO) y
:data:`WALL_REASON_SOURCE`, que el informe copia junto a los dos valores (:data:`WALL_REASON_NOTE`); :class:`Wall` las lleva
(``reason_min_angle_deg``, ``reason_min_height_m``) para que el informe de la retirada las copie, y ningún otro sitio las escribe.

**La transición de A6 no crea paredes** (con la métrica exacta ninguna pareja creada pasa de ``tan · factor de malla``: una celda movida junto
a una semilla queda a ``≥ z_s − tan · d``, y con el *chamfer*, a ``≥ z_s − tan · 0,98644 · h``): la pared se mide para que cada retirada lo
demuestre (CE-016-03) y para lo que sí la crea (una superficie sin transición, un factor de malla fuera de rango, una métrica nueva).

**Lo que no hace**: preparar, crear y reproducir la operación (la confirmación, su decisor y su fecha, el motivo y su evento: T20, en
``supported_store``). :attr:`RemovalOutcome.held` son las celdas de la huella con dato que el dominio no admite.

**Retirar «como plataforma»** (T21; RF-016-16; A9; P-3): es **una plataforma de la 015 con la huella del acopio como geometría**, no un tipo
más y no otro cálculo del borde. :func:`platform_of_stockpile` da, del acopio (:class:`RemovedStockpile`), lo que la plataforma necesita:
el **plano de su base** (ajustado a la base de cada celda de su huella y comprobado a :data:`PLANE_TOLERANCE_M`: con una base propia que no es
un plano se rechaza, ``des.removal_platform_no_plane``), el contorno de su huella alineado a la rejilla como polígono
(``entities.declared_zone_of_runs``, que la regla de la celda devuelve a las **mismas celdas**), el **eje por su centro en la dirección de
máxima pendiente del plano, de borde a borde de la huella** (de la menor a la mayor proyección de sus esquinas), y la cota inicial y la
pendiente de la rasante, que son las del plano en el principio del eje y su pendiente en %: la rasante de cada celda, ``cota inicial + σ ·
pendiente / 100``, **es el plano en toda la huella**. El resto es de la plataforma (``platform``, ``entity_store``): su borde, sus
comprobaciones, sus restricciones y sus cifras. :func:`platform_removal` (con :func:`with_removal`) añade lo de una retirada: el volumen
retirado del acopio, lo que se le apoyaba y lo que las máscaras no dejan retirar, que suman lo que había sobre la base (``des.rmv_*``).

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
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import numpy as np

from ..core.datasets import registry as dataset_registry
from ..core.datasets.model import LIVE_STATUSES
from ..core.params import ParamKind
from ..core.project.model import Progress
from ..core.provenance.figures import FigureSpec
from ..core.provenance.graph import DATASET
from ..core.versions import read as versions_read
from ..core.versions.model import Version, VersionError
from ..gis.grid import Grid
from ..gis.masks.compile import STEP_BUDGET_S
from ..gis.messages import GisError
from . import entities
from .edges import PAIR_CELLS_PER_UNIT, _band_units, _Found, _midpoint, seed_envelope_steps
from .envelopes import CELLS_PER_UNIT, SlopeField
from .grids import _label_units, dilate_square
from .messages import DesignError, render
from .model import Axis, Direction, Metric, RemovalRequest
from .params import (
    EDGE_MAX_STEP,
    TOLERANCE_FACE,
    VERIFY_MIN_THICKNESS,
    RemovalParam,
    check_entity_param,
    check_quarry_param,
    entity_params,
    entity_params_of,
)
from .platform import (
    PlatformGeometry,
    PlatformJob,
    PlatformOutcome,
    Window,
    _project_number,
    _shaped_array,
    _whole,
    _window_of,
    window_part,
    work_window,
)
from .preview import SUMMARY_ITEMS, Notice
from .provenance import SURFACE_ROLE, removal_figures
from .report import _thickness
from .seeds import pace_progress
from .stockpiles import Stockpile, footprint_runs, window_grid
from .store import _min_thickness
from .supported_edge import no_data_notice
from .surfaces import project_frame, read_surface_window

if TYPE_CHECKING:
    from ..gis.store import StoreProject

__all__ = [
    "PLANE_TOLERANCE_M",
    "WALL_REASON_KIND",
    "WALL_REASON_MIN_ANGLE_DEG",
    "WALL_REASON_MIN_HEIGHT_M",
    "WALL_REASON_NOTE",
    "WALL_REASON_SOURCE",
    "PlatformRemoval",
    "RemovalJob",
    "RemovalOutcome",
    "RemovedStockpile",
    "Resting",
    "RestingShare",
    "StockpilePlatform",
    "Wall",
    "WallStretch",
    "attribute_resting",
    "check_resting_confirmed",
    "check_wall_confirmed",
    "measure_wall",
    "platform_of_stockpile",
    "platform_removal",
    "remove_stockpile",
    "removal_steps",
    "removal_window",
    "resting_notices",
    "resting_on",
    "wall_notices",
    "wall_steps",
    "with_removal",
]

_PHASE = "removal"
_NOTHING = "des.removal_nothing"
_KEPT = "des.removal_kept"
_NO_DATA = "des.removal_no_data"
_WALL_PHASE = "removal_wall"

WALL_REASON_MIN_ANGLE_DEG = 45.0
"""La inclinación (°) **por encima de la cual** una pared de la retirada, además de confirmarse, pide un **motivo** que queda registrado.
Procedencia: CA-9 de la spec 016 (la lección del error 47, donde el acopio de 12 m dejó una cara a más de 45°) y su D-6 (la pared tras
retirar: «aviso con confirmación expresa» y, con una pared de más de 45° y 3 m o más, un motivo registrado); **no es un parámetro** de la
retirada (la spec no lo da como editable): decisión de la sesión principal del 18/11/2026, tras la T03, revisable. Estricta: una pared a
exactamente 45° no lo pide."""
WALL_REASON_MIN_HEIGHT_M = 3.0
"""La altura (m) **desde la cual** una pared de la retirada más empinada que :data:`WALL_REASON_MIN_ANGLE_DEG` pide un motivo: «3 m o más».
Misma procedencia que :data:`WALL_REASON_MIN_ANGLE_DEG` (CA-9 y D-6 de la spec 016; decisión de la sesión principal del 18/11/2026)."""
WALL_REASON_KIND = ParamKind.ADOPTADO.value
"""El **tipo** de los dos umbrales de CA-9 (principio 2 y spec §4: toda cifra lleva su tipo y su procedencia; hallazgos B-4 y S-8 de la
verificación única, T48): ADOPTADO, de la procedencia de :data:`WALL_REASON_SOURCE`. Siguen sin ser parámetros de la persona."""
WALL_REASON_SOURCE = ("Spec 016, CA-9 y D-6 (la lección del error 47): la pared de más de 45° y de 3 m o más pide un motivo; decisión de la "
                      "sesión principal del 18/11/2026, revisable")
"""La procedencia de los dos umbrales de CA-9 tal como la copia el informe de la retirada (:data:`WALL_REASON_NOTE`); es la misma que el
docstring de cada umbral, en una sola línea."""
WALL_REASON_NOTE = f"{WALL_REASON_KIND} · {WALL_REASON_SOURCE}"
"""La nota de las dos filas de los umbrales en el informe de la retirada (``des_prp_``): el tipo y la procedencia, junto al valor y su unidad."""
_ROUNDOFF_DEG = 1e-9
"""Lo que se perdona al comparar una inclinación con el límite (°): el redondeo de ``atan(tan(θ))`` (≈ 10⁻¹⁴ °), para que la transición
construida **exactamente** al ángulo, con la tolerancia a 0, no avise por una milmillonésima. No es una cifra minera."""


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
    la huella tenía sobre la base) a ≤ 10⁻⁹ relativo. ``wall_max_m`` es la altura de la mayor pared que deja (``None`` mientras no
    se mida: :func:`measure_wall`, A8; 0 m si ninguna) y ``wall`` la pared medida (:class:`Wall`: sus tramos y lo que
    pide confirmar; ``None`` mientras no se mida). ``transition_deg``, ``mesh_factor`` y ``metric`` son los de la retirada,
    ``cell_area_m2`` el área de una celda y ``notices`` los avisos (``des.removal_nothing`` con 0 m³ retirados, ``des.removal_kept`` con lo
    no retirado, ``des.removal_no_data`` con las celdas de la huella sin dato —T53— y, medida la pared, ``des.removal_wall``)."""

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
    wall: Wall | None = None

    @property
    def figures(self) -> tuple[FigureSpec, ...]:
        """Las cifras CALCULADO de la operación (:func:`~.provenance.removal_figures`, con el ámbito de la entidad y en el
        orden de ``REMOVAL_FIGURES``): ``des.rmv_removed_m3``, ``_resting_m3``, ``_transition_m3``, ``_kept_m3``,
        ``_transition_m2`` y, si se midió la pared (:func:`measure_wall`), ``_wall_max_m``."""
        return removal_figures(self.name, self.code, {
            "des.rmv_removed_m3": self.removed_m3, "des.rmv_resting_m3": self.resting_m3,
            "des.rmv_transition_m3": self.transition_m3, "des.rmv_kept_m3": self.kept_m3,
            "des.rmv_transition_m2": self.transition_m2, "des.rmv_wall_max_m": self.wall_max_m})

    @property
    def message(self) -> str:
        """El mensaje de la operación (spec 016, T20): lo que dice el resumen de lo calculado, con los m³ retirados del acopio, los
        que se le apoyaban y los de la transición (al metro cúbico)."""
        return (f"Retirada del acopio «{self.stockpile_name}»: {round(self.removed_m3)} m³ retirados, "
                f"{round(self.resting_m3)} m³ apoyados y {round(self.transition_m3)} m³ de transición")

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
    found: list[Notice] = [Notice(_NOTHING, {"stockpile": item.name})] if removed == 0.0 else []
    if kept > 0.0:  # B-2 (T48): lo que las máscaras no dejan retirar se avisa, con su volumen y el centro de las celdas donde queda
        with np.errstate(invalid="ignore"):
            over = held & (z > base)
        rows_over, cols_over = np.nonzero(over)
        found.append(Notice(_KEPT, {"stockpile": item.name, "volume": kept,
                                    "x": float(np.mean(sub.west + (cols_over + 0.5) * sub.dx)),
                                    "y": float(np.mean(sub.north - (rows_over + 0.5) * sub.dy))}))
    # T53 (decisión 8 de «Para Samuel»): las celdas de la huella sin dato se toleran (excepción de la 016 a RF-015-09: no se retiran y no
    # cuentan) pero se avisan con su lugar (RF-015-13); las del anillo, fuera de la huella, no son de la huella
    missing = no_data_notice(_NO_DATA, {"stockpile": item.name}, footprint & ~has_data, grid, window)
    if missing is not None:
        found.append(missing)
    return RemovalOutcome(job.request.name, job.code, item.key, item.name, window, surface, footprint, admitted, held,
                          seeds, removed, resting, transition, kept, above, transition_cells * area,
                          settings.angle_deg, settings.mesh_factor, settings.metric, area, None, tuple(found))


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


def resting_record(found: Iterable[Resting]) -> list[dict[str, Any]]:
    """**Lo que anota la retirada de lo que se le apoyaba** (spec 016, T45; RF-016-14, RF-015-17, P-9; hallazgos S-1 y B-1): de la lista de
    :func:`resting_on` (la misma que se listó antes de calcular y se confirmó), una fila por **operación** de la versión —una entidad o un diseño de
    la 013 y la 014— con su ``operation`` (uid), su ``name``, su código de entidad (``entity``; ``None`` en un diseño), sus ``volume_m3`` y sus
    ``cells``, en el orden de la lista; la fila de una **superficie** (la de otra versión o del proyecto, por su nombre: sin operación) no se anota,
    porque no hay a quién quitarle el apoyo. Es lo que se guarda en los ajustes de la operación (``provenance.REMOVAL_RESTING``: un JSON finito) y lo
    que lee «apoyo retirado» (``entities``) **sin leer ninguna superficie**, de modo que no depende de las cifras que el relleno midió al crearse."""
    return [{"operation": row.operation_uid, "name": row.name, "entity": row.entity, "volume_m3": float(row.volume_m3),
             "cells": int(row.cells)} for row in found if row.operation_uid is not None]


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


# --- A8: la pared -------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WallStretch:
    """Un **tramo** de la pared que deja la retirada (A8; RF-016-15): una componente 4-conexa de las celdas de las parejas que pasan del salto
    admitido y de la inclinación (:func:`measure_wall`), con su número (``stretch``, desde 1, en el orden de su primera celda de norte a sur y
    de oeste a este), sus ``pairs``, su altura **recorriendo la cara** (``height_m``: la mayor cota de las celdas de sus parejas menos la menor,
    m), la inclinación de su peor pareja (``angle_deg``, °), su mayor salto creado (``step_m``, m: el de la 014, RF-014-20) y el lugar de esa
    pareja (``x``, ``y``: el punto medio, absolutos en float64; a igual inclinación, la primera de norte a sur y de oeste a este)."""

    stretch: int
    pairs: int
    height_m: float
    angle_deg: float
    step_m: float
    x: float
    y: float


def _tallest(items: Iterable[WallStretch]) -> WallStretch | None:
    """El tramo más alto de ``items`` (a igual altura, el más empinado y, a igual inclinación, el primero), o ``None`` si no hay ninguno."""
    return max(items, key=lambda item: (item.height_m, item.angle_deg, -item.stretch), default=None)


@dataclass(frozen=True, slots=True)
class Wall:
    """La pared que deja la retirada (A8; RF-016-15): los ``stretches`` (los tramos con una inclinación mayor que el límite; ninguno si la
    retirada no deja pared), el ángulo de transición (``transition_deg``) y la tolerancia de cara de la 013 (``tolerance_deg``) que dan su
    límite (:attr:`limit_deg`), el espesor mínimo de la 012 con que se contaron las celdas movidas (``thickness_m``), el salto admitido de la
    014 (``jump_m``), las parejas del borde de lo retirado (``pairs``) y las que pasan del salto admitido (``over``: más que las de los
    tramos, que además son más empinadas que el límite) y los dos umbrales de CA-9 que decidieron si pide un motivo
    (``reason_min_angle_deg`` y ``reason_min_height_m``: los de :data:`WALL_REASON_MIN_ANGLE_DEG` y :data:`WALL_REASON_MIN_HEIGHT_M`, copiados
    para el informe de la retirada)."""

    stretches: tuple[WallStretch, ...]
    transition_deg: float
    tolerance_deg: float
    thickness_m: float
    jump_m: float
    pairs: int
    over: int
    reason_min_angle_deg: float = WALL_REASON_MIN_ANGLE_DEG
    reason_min_height_m: float = WALL_REASON_MIN_HEIGHT_M

    @property
    def limit_deg(self) -> float:
        """La inclinación que una pared puede tener sin avisar (°): el ángulo de transición más la tolerancia de cara."""
        return self.transition_deg + self.tolerance_deg

    @property
    def height_m(self) -> float:
        """La altura de la mayor pared (m; 0 si no hay ninguna): ``des.rmv_wall_max_m``."""
        return max((item.height_m for item in self.stretches), default=0.0)

    @property
    def worst(self) -> WallStretch | None:
        """El tramo del aviso: el más alto (a igual altura, el más empinado); ``None`` sin pared."""
        return _tallest(self.stretches)

    @property
    def reason_stretch(self) -> WallStretch | None:
        """El tramo más alto que pide un motivo (CA-9: más empinado que :attr:`reason_min_angle_deg` **y** de :attr:`reason_min_height_m` **o
        más**); ``None`` si ninguno."""
        return _tallest(item for item in self.stretches
                        if item.angle_deg > self.reason_min_angle_deg and item.height_m >= self.reason_min_height_m)

    @property
    def needs_confirmation(self) -> bool:
        """Si hay una pared y la retirada no se crea sin la confirmación expresa de la persona (RF-016-15)."""
        return bool(self.stretches)

    @property
    def needs_reason(self) -> bool:
        """Si alguna pared pasa de los umbrales de CA-9 y la retirada no se crea sin un motivo que quede registrado."""
        return self.reason_stretch is not None


@dataclass(frozen=True, slots=True)
class _WallSettings:
    """Lo que lee A8 de los parámetros del proyecto, ya comprobado: la tolerancia de cara de la 013 (°), el espesor mínimo de la 012 (m) y el
    salto admitido de la 014 (m)."""

    tolerance_deg: float
    thickness_m: float
    jump_m: float


def _wall_settings(project: Mapping[str, object]) -> _WallSettings:
    """La tolerancia de cara (``des.tolerance.face_deg``), el espesor mínimo (``res.verify.min_thickness_m``) y el salto admitido
    (``des.edge.max_created_step_m``) de ``project``, comprobados como en el borde de la plataforma: ``ValueError`` (errores del programa:
    quien llama los lee del proyecto, ``provenance.PLATFORM_COMMON_PARAMS``, y ninguno lleva valor por defecto) si falta alguno, no es un
    número finito, la tolerancia o el espesor son negativos; el salto, fuera de su rango, ``des.quarry_param_range``."""
    tolerance = _project_number(project, TOLERANCE_FACE)
    if tolerance < 0.0:
        raise ValueError(f"la tolerancia de cara es un número finito ≥ 0, no {tolerance!r}")
    thickness = _thickness(_project_number(project, VERIFY_MIN_THICKNESS))
    jump = float(check_quarry_param(EDGE_MAX_STEP, _project_number(project, EDGE_MAX_STEP)))
    return _WallSettings(tolerance, thickness, jump)


def _check_wall_inputs(job: RemovalJob, outcome: RemovalOutcome) -> None:
    """``ValueError`` (errores del programa) si ``outcome`` no es de ``job`` (otro código o acopio), su ventana no está dentro de lo que leyó
    el trabajo o alguna de sus rejillas no es de la forma de su ventana."""
    if not isinstance(outcome, RemovalOutcome):
        raise ValueError(f"la pared se mide sobre un RemovalOutcome, no sobre {type(outcome).__name__}")
    if outcome.code != job.code or outcome.stockpile != job.stockpile.key:
        raise ValueError(f"el resultado de {outcome.code} ({outcome.stockpile}) no es de la retirada {job.code} del acopio "
                         f"{job.stockpile.key}")
    rows, cols = outcome.window
    shape = (rows.stop - rows.start, cols.stop - cols.start)
    for name in ("surface", "footprint", "admitted", "held", "seeds"):
        found = getattr(outcome, name).shape
        if found != shape:
            raise ValueError(f"«{name}» del resultado es de la forma {found}, no de la de su ventana {shape}")
    if job.start_in(outcome.window).shape != shape:
        raise ValueError(f"la ventana ({rows}, {cols}) del resultado no está en la rejilla del trabajo")


def _wall_stretches(surface: np.ndarray, grid: Grid, found: _Found, limit_deg: float
                    ) -> Generator[None, None, tuple[WallStretch, ...]]:
    """Los tramos de las parejas de ``found`` (las que pasan del salto admitido, con su clave y su salto creado) que son más empinadas que
    ``limit_deg``: cada pareja se saca de su clave (el punto medio en medias celdas), su inclinación es ``atan(|S_a − S_b| / distancia)``, las
    celdas de las que pasan se etiquetan (4-conexas) y de cada etiqueta se agrupan sus parejas: mayor y menor cota, peor inclinación, mayor
    salto y la clave de la primera pareja con la peor inclinación."""
    keys = np.concatenate(found.keys)
    created = np.concatenate(found.steps)
    key_row, key_col = np.divmod(keys, 2 * grid.ncols + 1)
    vertical = key_row % 2 == 1  # una pareja norte-sur tiene la fila impar; una este-oeste, la columna impar
    row1 = np.where(vertical, (key_row - 1) // 2, key_row // 2)
    col1 = np.where(vertical, key_col // 2, (key_col - 1) // 2)
    row2 = np.where(vertical, row1 + 1, row1)
    col2 = np.where(vertical, col1, col1 + 1)
    first, second = surface[row1, col1], surface[row2, col2]
    angle = np.degrees(np.arctan(np.abs(first - second) / np.where(vertical, grid.dy, grid.dx)))
    steep = angle > limit_deg + _ROUNDOFF_DEG
    yield None
    if not steep.any():
        return ()
    keys, created, angle = keys[steep], created[steep], angle[steep]
    row1, col1, row2, col2 = row1[steep], col1[steep], row2[steep], col2[steep]
    crest, toe = np.maximum(first[steep], second[steep]), np.minimum(first[steep], second[steep])
    cells = np.zeros(surface.shape, dtype=bool)
    cells[row1, col1] = True
    cells[row2, col2] = True
    labels = yield from _label_units(cells)
    tag = labels.grid[row1, col1]
    count = labels.count
    pairs = np.bincount(tag, minlength=count + 1)
    top = np.full(count + 1, -np.inf)
    np.maximum.at(top, tag, crest)
    bottom = np.full(count + 1, np.inf)
    np.minimum.at(bottom, tag, toe)
    step = np.full(count + 1, -np.inf)
    np.maximum.at(step, tag, created)
    worst = np.full(count + 1, -np.inf)
    np.maximum.at(worst, tag, angle)
    place = np.full(count + 1, np.iinfo(np.int64).max, dtype=np.int64)
    at_worst = angle == worst[tag]
    np.minimum.at(place, tag[at_worst], keys[at_worst])
    yield None
    place_row, place_col = np.divmod(place, 2 * grid.ncols + 1)
    stretches = []
    for index in range(1, count + 1):
        x, y = _midpoint(grid, float(place_row[index]), float(place_col[index]))
        stretches.append(WallStretch(index, int(pairs[index]), float(top[index] - bottom[index]), float(worst[index]),
                                     float(step[index]), x, y))
    return tuple(stretches)


def wall_notices(stockpile: str, wall: Wall) -> tuple[Notice, ...]:
    """El aviso de la pared que deja la retirada del acopio ``stockpile`` (RF-016-15): **una** nota ``des.removal_wall`` con la altura, la
    inclinación, el límite (ángulo de transición más tolerancia de cara), el salto creado y el lugar del tramo más alto (al cm y a la
    centésima de grado); ninguna si no hay pared."""
    worst = wall.worst
    if worst is None:
        return ()
    return (Notice("des.removal_wall", {
        "stockpile": stockpile, "height": round(worst.height_m, 2), "angle": round(worst.angle_deg, 2),
        "limit": round(wall.limit_deg, 2), "step": round(worst.step_m, 2), "x": round(worst.x, 2), "y": round(worst.y, 2)}),)


def check_wall_confirmed(stockpile: str, wall: Wall, *, confirmed: bool, reason: str | None = None) -> None:
    """**No se crea la retirada sin la confirmación expresa de la pared** (RF-016-15, D-6; error 47): con una pared y sin ``confirmed``,
    ``des.removal_wall_unconfirmed`` con el acopio ``stockpile``, la altura y la inclinación del tramo más alto (``DesignError``: un motivo no
    hace las veces de la confirmación); y, con la pared confirmada, **sin un motivo** (``reason`` ausente o en blanco) si alguna pasa de
    :data:`WALL_REASON_MIN_ANGLE_DEG` y de :data:`WALL_REASON_MIN_HEIGHT_M` **o más** (CA-9), ``des.removal_wall_reason`` con la altura y la
    inclinación de ese tramo y los dos umbrales. Sin pared no pide nada. No escribe: la confirmación, su decisor y su fecha y el motivo
    (``wall_reason`` y su evento) los registra la orden (T20)."""
    worst = wall.worst
    if worst is None:
        return
    obj = f"Retirada del acopio «{stockpile}»"
    if not confirmed:
        raise DesignError("des.removal_wall_unconfirmed", obj=obj, field="confirmación", value=False, stockpile=stockpile,
                          height=round(worst.height_m, 2), angle=round(worst.angle_deg, 2))
    needing = wall.reason_stretch
    if needing is not None and (reason is None or not reason.strip()):
        raise DesignError("des.removal_wall_reason", obj=obj, field="motivo", value=reason, stockpile=stockpile,
                          height=round(needing.height_m, 2), angle=round(needing.angle_deg, 2),
                          min_angle=wall.reason_min_angle_deg, min_height=wall.reason_min_height_m)


def _wall_units(job: RemovalJob, outcome: RemovalOutcome, settings: _WallSettings) -> Generator[None, None, RemovalOutcome]:
    """Las unidades de :func:`wall_steps`: las parejas del borde de lo retirado por bandas de filas (las de la 014, con el salto creado y el
    salto admitido), su inclinación, los tramos de las más empinadas que el límite y el resultado con la pared."""
    window = outcome.window
    grid = window_grid(job.grid, window)
    start, surface = job.start_in(window), outcome.surface
    found = _Found()
    per_unit = max(1, PAIR_CELLS_PER_UNIT // max(surface.shape[1], 1))
    yield None
    # El dominio de la 014 es lo que se retira: una celda está movida si está ahí y la superficie la mueve más del espesor mínimo.
    yield from _band_units(surface, start, outcome.admitted, grid, settings.thickness_m, settings.jump_m, per_unit,
                           np.zeros(surface.shape, dtype=bool), found)
    over = sum(int(item.size) for item in found.keys)
    stretches: tuple[WallStretch, ...] = ()
    if over:
        stretches = yield from _wall_stretches(surface, grid, found, outcome.transition_deg + settings.tolerance_deg)
    wall = Wall(stretches, outcome.transition_deg, settings.tolerance_deg, settings.thickness_m, settings.jump_m, found.pairs, over)
    return replace(outcome, wall=wall, wall_max_m=wall.height_m,
                   notices=(*outcome.notices, *wall_notices(outcome.stockpile_name, wall)))


def wall_steps(job: RemovalJob, outcome: RemovalOutcome, project: Mapping[str, object], *, budget_s: float = STEP_BUDGET_S
               ) -> Iterator[Progress]:
    """**A8** (RF-016-15; plan 016 §5.4; errores 41 y 47): la pared que deja la retirada ``outcome`` (la de :func:`removal_steps` de ``job``)
    por pasos de ``budget_s`` como mucho (RNF-016-03: ≤ 0,2 s cada llamada): el último ``Progress`` (fase ``removal_wall``) lleva en ``result``
    un :class:`RemovalOutcome` **nuevo**, el mismo con su ``wall`` (:class:`Wall`), ``wall_max_m`` (la altura de la mayor pared, 0 m si ninguna) y
    el aviso ``des.removal_wall`` detrás de los que ya llevaba; ``outcome`` no se modifica.

    Una **pareja** son dos celdas vecinas (4 vecinos) con dato, una movida (en lo que se retira, con ``|z' − z|`` mayor que el espesor
    mínimo de la 012) y la otra no; su salto creado es el de la 014 (``edges``: ``|S_a − S_b| − |z_a − z_b|``: lo que el terreno ya tenía no
    cuenta). Pasan las de salto creado mayor que el salto admitido y de inclinación ``atan(|S_a − S_b| / distancia)`` **mayor** que el ángulo
    de transición más la tolerancia de cara; sus celdas forman los tramos, de cada uno la altura (mayor cota menos menor cota de sus parejas),
    la inclinación de su peor pareja, su mayor salto creado y su lugar (:class:`WallStretch`).

    ``project`` son los parámetros del proyecto que lee la pared, por su clave (``provenance.PLATFORM_COMMON_PARAMS``): la tolerancia de cara
    (``des.tolerance.face_deg``), el espesor mínimo (``res.verify.min_thickness_m``) y el salto admitido (``des.edge.max_created_step_m``);
    ninguno lleva valor por defecto aquí. Rechazos **al llamar** (errores del programa, ``ValueError``): un valor del proyecto que falta, no
    es finito o es negativo (la tolerancia y el espesor), un ``outcome`` que no es de ``job`` o de otra forma que su ventana; un salto
    admitido fuera de su rango, ``des.quarry_param_range``. No escribe nada; cerrar el generador a mitad no deja nada."""
    settings = _wall_settings(project)
    _check_wall_inputs(job, outcome)
    return pace_progress(_wall_units(job, outcome, settings), budget_s, phase=_WALL_PHASE,
                         running="Midiendo la pared que deja la retirada…", finished="Pared de la retirada medida")


def measure_wall(job: RemovalJob, outcome: RemovalOutcome, project: Mapping[str, object]) -> RemovalOutcome:
    """**A8**: :func:`wall_steps` hasta el final, sin pasos: el :class:`RemovalOutcome` de ``outcome`` con su pared. Los mismos rechazos."""
    settings = _wall_settings(project)
    _check_wall_inputs(job, outcome)
    work = _wall_units(job, outcome, settings)
    while True:
        try:
            next(work)
        except StopIteration as done:
            return done.value  # type: ignore[no-any-return]


# --- A9: retirar como plataforma ----------------------------------------------------------------------------------------------

PLANE_TOLERANCE_M = 1e-6
"""Lo que se aparta de un plano (m) la base de un acopio retirado «como plataforma» para seguir siendo «el plano de su base»: el límite del
plano de base de D-11 de la spec 016 (≤ 10⁻⁶ m). Un acopio con **base propia** (RF-016-03: la de una superficie) no lo cumple y se rechaza
(``des.removal_platform_no_plane``). No es una cifra minera: el plano ajustado de la detección lo cumple de sobra (≈ 10⁻¹² m)."""


@dataclass(frozen=True, slots=True, eq=False)
class StockpilePlatform:
    """Lo que sale de un acopio para retirarlo **como plataforma** (:func:`platform_of_stockpile`; A9, RF-016-16): la ``geometry`` de la plataforma
    (el contorno de la huella como polígono, con su eje dado), el ``axis`` (por el centro de la huella, en la dirección de máxima pendiente del
    plano y de borde a borde), la cota inicial de la rasante (``start_level_m``: la del plano en el principio del eje) y su pendiente
    (``gradient_pct``: la del plano, en %, positiva: el eje sube), el centro de la huella (``centre_x``, ``centre_y``, absolutos float64) con la
    cota del plano en él (``centre_level_m``), el azimut de la máxima pendiente (``azimuth_deg``, desde el norte en sentido horario), las
    celdas y el área de la huella y lo que se separa la base del plano ajustado (``residual_m``, m)."""

    key: str
    name: str
    geometry: PlatformGeometry
    axis: Axis
    start_level_m: float
    gradient_pct: float
    centre_x: float
    centre_y: float
    centre_level_m: float
    azimuth_deg: float
    cells: int
    area_m2: float
    residual_m: float


def platform_of_stockpile(item: RemovedStockpile, grid: Grid) -> StockpilePlatform:
    """**A9** (RF-016-16; plan 016 §5.4; puro): la plataforma de la huella del acopio ``item`` en la rejilla ``grid``.

    El plano ``z = z_c + g_x·(x − x_c) + g_y·(y − y_c)`` por mínimos cuadrados de la base de cada celda de la huella (``item.base``) en el centro
    de sus celdas (coordenadas locales desde la esquina noroeste de la rejilla, en float64: el principio 6 de ADR-0005), con ``(x_c, y_c)`` el
    centro de sus celdas; ``g = √(g_x² + g_y²)`` es su pendiente y ``(g_x, g_y)/g`` la dirección de máxima pendiente (sin pendiente, el este:
    como el eje principal de la 015). La base se aparta del plano **como mucho** :data:`PLANE_TOLERANCE_M`; si no (una base propia), ``DesignError``
    ``des.removal_platform_no_plane``. El eje pasa por el centro con esa dirección y va **de la menor a la mayor proyección de las esquinas de las
    celdas de la huella** (de borde a borde: cada celda proyecta dentro de él, así que su abscisa es la de su proyección, sin recortar); su sentido
    es el de **subida** del plano, de modo que la pendiente es positiva y ``cota inicial = z_c + g · t_min``. La geometría es el contorno de la
    huella alineado a la rejilla (:func:`~.entities.declared_zone_of_runs` sin resguardo: la regla de la celda devuelve las mismas celdas) con ese
    eje dado (:attr:`~.platform.PlatformGeometry.given_axis`). Ninguna entrada se modifica. ``ValueError`` (errores del programa) si el acopio no
    cabe en la rejilla."""
    cells = item.cells
    if int(cells[-1]) >= grid.nrows * grid.ncols:
        raise ValueError(f"el acopio «{item.name}» tiene celdas fuera de la rejilla de {grid.nrows} × {grid.ncols}")
    rows, cols = np.divmod(cells, grid.ncols)
    x = (cols + 0.5) * grid.dx
    y = -(rows + 0.5) * grid.dy  # locales desde la esquina noroeste, Y hacia el norte (como axis_of_polygon)
    xc, yc, zc = float(x.mean()), float(y.mean()), float(item.base.mean())
    ex, ey = x - xc, y - yc
    found, *_rest = np.linalg.lstsq(np.column_stack((ex, ey)), item.base - zc, rcond=None)
    gx, gy = float(found[0]), float(found[1])
    residual = float(np.max(np.abs(item.base - (zc + gx * ex + gy * ey))))
    if not residual <= PLANE_TOLERANCE_M:
        raise DesignError("des.removal_platform_no_plane", obj=f"Retirada del acopio «{item.name}»", field="base", value=residual,
                          stockpile=item.name, residual=round(residual, 6))
    slope = math.hypot(gx, gy)
    ux, uy = (gx / slope, gy / slope) if slope > 0.0 else (1.0, 0.0)
    along = ex * ux + ey * uy
    half = 0.5 * (abs(ux) * grid.dx + abs(uy) * grid.dy)
    low, high = float(along.min()) - half, float(along.max()) + half
    start = (grid.west + xc + low * ux, grid.north + yc + low * uy)
    end = (grid.west + xc + high * ux, grid.north + yc + high * uy)
    axis = Axis((start, end))
    zone = entities.declared_zone_of_runs(footprint_runs(cells, grid.ncols), grid, 0.0)
    azimuth = math.degrees(math.atan2(ux, uy)) % 360.0  # desde el norte, en sentido horario
    return StockpilePlatform(
        item.key, item.name, PlatformGeometry("polygon", zone.parts, given_axis=axis), axis, zc + slope * low, 100.0 * slope,
        grid.west + xc, grid.north + yc, zc, azimuth, int(cells.size), int(cells.size) * grid.cell_area, residual)


@dataclass(frozen=True, slots=True)
class PlatformRemoval:
    """Lo que la plataforma que sale de retirar un acopio **como plataforma** hace de **retirada** (A9, RF-016-16, RF-016-13): del acopio
    ``stockpile`` (``name``), ``removed_m3`` (lo del acopio: entre su base y la superficie con que se detectó), ``resting_m3`` (lo que se le
    apoyó, por encima de ella) y ``kept_m3`` (lo que las máscaras no dejan cortar de la huella), que suman ``above_base_m3`` (lo que la huella
    tenía sobre la base) a ≤ 10⁻⁹ relativo; ``transition_m3`` y ``transition_m2`` son 0: toda la huella queda en su plano (la transición con
    el terreno es **el borde** de la plataforma, que mide su corte y su relleno). Las cifras de una retirada (``des.rmv_*``: sin pared, que es
    la del borde de la plataforma, ``des.edge_wall_max_m``) y los avisos de RF-016-13: con 0 m³ retirados, que el acopio ya no está y, con
    lo no retirado, ``des.removal_kept`` (T48) en torno a ``kept_at`` (el centro absoluto de las celdas donde queda)."""

    stockpile: str
    name: str
    removed_m3: float
    resting_m3: float
    transition_m3: float
    kept_m3: float
    above_base_m3: float
    transition_m2: float
    kept_at: tuple[float, float] | None = None

    def figures(self, entity: str, code: str) -> tuple[FigureSpec, ...]:
        """Las cifras CALCULADO de la retirada (``des.rmv_*``, :func:`~.provenance.removal_figures`) de la plataforma ``entity`` de código
        ``code``, con el ámbito de la entidad y sin la pared."""
        return removal_figures(entity, code, {
            "des.rmv_removed_m3": self.removed_m3, "des.rmv_resting_m3": self.resting_m3,
            "des.rmv_transition_m3": self.transition_m3, "des.rmv_kept_m3": self.kept_m3,
            "des.rmv_transition_m2": self.transition_m2, "des.rmv_wall_max_m": None})

    @property
    def notices(self) -> tuple[Notice, ...]:
        """Los avisos de RF-016-13: con 0 m³ retirados, el acopio ya no está en la superficie de partida y, con lo que las máscaras no dejan
        retirar, ``des.removal_kept`` con su volumen y su lugar (T48, B-2)."""
        found: list[Notice] = [Notice(_NOTHING, {"stockpile": self.name})] if self.removed_m3 == 0.0 else []
        if self.kept_m3 > 0.0 and self.kept_at is not None:
            found.append(Notice(_KEPT, {"stockpile": self.name, "volume": self.kept_m3, "x": self.kept_at[0], "y": self.kept_at[1]}))
        return tuple(found)


def platform_removal(item: RemovedStockpile, job: PlatformJob, outcome: PlatformOutcome) -> PlatformRemoval:
    """**A9, lo de una retirada** (RF-016-13, RF-016-16): las cifras de retirar el acopio ``item`` con la plataforma de ``job`` que dio
    ``outcome`` (su huella, lo aplicado y su superficie resultante), con ``z`` la superficie de partida, ``z'`` la resultante, ``B`` la base del
    acopio y ``T`` la superficie con que se detectó, en las celdas de su huella (m³ por el área de la celda, con ``math.fsum``):
    ``removed = Σ máx(mín(z, T) − z', 0)``, ``resting = Σ máx(z − máx(z', T), 0)`` y ``kept = Σ máx(z − B, 0)`` en las celdas que las
    máscaras no dejan cortar (``applied.cut_denied``). Suman ``Σ máx(z − B, 0)`` (``above_base_m3``). ``ValueError`` (error del programa) si la
    huella de la plataforma no son las celdas del acopio."""
    footprint = outcome.footprint
    window, cells = footprint.window, footprint.cells
    grid = job.grid
    rows, cols = np.nonzero(cells)
    flat = (rows + window[0].start).astype(np.int64) * grid.ncols + cols + window[1].start
    if not np.array_equal(flat, item.cells):
        raise ValueError(f"la huella de la plataforma de «{item.name}» no son las celdas del acopio: la plataforma se hizo con otra geometría")
    start = job.start_in(window)[cells]
    final = outcome.result[cells]
    denied = outcome.applied.cut_denied[cells]
    area = grid.cell_area
    with np.errstate(invalid="ignore"):
        above = np.maximum(start - item.base, 0.0)
        removed = np.maximum(np.minimum(start, item.surface) - final, 0.0)
        resting = np.maximum(start - np.maximum(final, item.surface), 0.0)
    with np.errstate(invalid="ignore"):
        held = denied & (above > 0.0)
    kept_at = None
    if held.any():  # el centro de las celdas donde las máscaras no dejan cortar y queda algo (T48, B-2)
        kept_at = (float(np.mean(grid.west + (cols[held] + window[1].start + 0.5) * grid.dx)),
                   float(np.mean(grid.north - (rows[held] + window[0].start + 0.5) * grid.dy)))
    return PlatformRemoval(
        item.key, item.name, math.fsum(removed.tolist()) * area, math.fsum(resting.tolist()) * area, 0.0,
        math.fsum(above[denied].tolist()) * area, math.fsum(above.tolist()) * area, 0.0, kept_at)


def with_removal(outcome: PlatformOutcome, job: PlatformJob, item: RemovedStockpile) -> PlatformOutcome:
    """El ``outcome`` de la plataforma de ``job`` **con lo de una retirada** (:func:`platform_removal`): su ``removal``, las cifras ``des.rmv_*``
    detrás de las de la plataforma y el aviso de RF-016-13 con 0 m³ retirados detrás de los suyos. ``outcome`` no se modifica."""
    found = platform_removal(item, job, outcome)
    return replace(outcome, removal=found, figures=(*outcome.figures, *found.figures(outcome.name, outcome.code)),
                   notices=(*outcome.notices, *found.notices))
