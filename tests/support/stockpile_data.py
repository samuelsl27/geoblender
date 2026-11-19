# SPDX-License-Identifier: GPL-3.0-or-later
"""La cantera de los acopios, el contrafuerte y los cuerpos apoyados (spec 016, T01; plan 016 §7.1 y §7.4;
RF-016-01 a 22; CE-016-01 a 07 y 10; E1 y E5).

Todo es sintético (ningún dato de cliente), en coordenadas **absolutas** float64 (EPSG:25830 + EPSG:5782) desde
la esquina :data:`BASE` de ``tests.support.constraints_fixtures``, sobre la cantera de la 014
(``tests.support.quarry_fixtures``) y su ampliación de la 015 (``tests.support.entity_fixtures``), que no se
tocan. Las coordenadas «locales» son metros desde :data:`BASE` (``x`` al este, ``y`` al norte); en las rejillas,
la fila 0 es el norte. Cada función que da un array da uno **nuevo**. Las cuentas están hechas a mano; las
comprueba ``tests/unit/design/test_stockpile_fixtures.py``.

- **Los planos** (:func:`plane`, :data:`TILTS_DEG`): de 0°, 3° y 8° con el azimut de su máxima pendiente a 30°
  desde el norte. La inclinación máxima de la detección (4°, HIPÓTESIS) queda entre los dos últimos.
- **Los montones** (:class:`Mound`): troncos de **pirámide** (el volumen, a mano y exacto: con la pendiente de
  0,5 o 0,25, las alturas son exactas en binario y el volumen por anillos de celdas es una suma de enteros) y de
  **cono** (el volumen analítico, con las celdas de 1 m a menos del 1 %: D-11). La altura de un montón es
  siempre **sobre el plano**, así que su volumen no depende de la inclinación. :data:`PYRAMID` (pie 20 m, cima
  12 m, 4 m: **4.184 m³**) y :data:`CONE` (pie 20 m, cima 10 m, 5 m: 3.665,19 m³ analíticos).
- **Los montones sobre un plano con celdas atípicas** (:func:`mound_case`; CE-016-02): una ventana de 120 × 120
  m (:func:`window_grid`) con el montón en el centro, la marca (un cuadrado de pie + 4 m de semilado) y ocho celdas
  atípicas de entre 2 y 4 m en la corona (:data:`OUTLIER_SPEC`: cuatro en la de la marca y cuatro en la de la
  huella; solo tres bajan, así que un ajuste sin descartarlas se aparta del plano). Con celdas de 1 m y de 2 m.
- **El levantamiento** (:func:`survey`, :data:`SURVEY_MOUNDS`; CE-016-01, E1): la rejilla de 400 × 400 celdas de 1
  m de la cantera con **5 acopios marcados** (:data:`MARKS`; Acopio 1 y 2 se tocan; el 5 tiene una base propia) y
  **20 montículos sin marca**: 8 que pasan los filtros de los candidatos (:data:`SURVEY_GROUPS` ``pass``), 4
  pequeños, 4 bajos y 4 fuera del perímetro (el de la cantera, de (20, 60) a (360, 340)). Sobre un plano de 3° y
  una terraza de 0,5 m (:data:`TERRACE_BOX`) que el levantamiento anterior (:func:`previous_survey`, la base
  propia del Acopio 5) tiene bajo el pie de ese acopio. **Los cinco marcados también pasarían los filtros**: una
  zona que ya tiene marca no es un candidato (RF-016-08 los llama «sin marca»).
- **Dos acopios que se tocan** (:func:`touching_pair`; E1, RF-016-06): Acopio 1 y 2 en una ventana, con su
  volumen (1.112 m³ cada uno; 2.178 m³ unidos) y su solape (96 celdas) a mano.
- **El acopio de 12 m junto a un relleno** (:func:`tall_stockpile_with_fill`; CE-016-03, error 47): 17.864 m³,
  con un bloque de relleno de 3 m que pisa su pie (360 m³ apoyados) y sale por fuera (3.360 m³).
- **El llano del contrafuerte** (:func:`flat_window`; CE-016-10): un plano a 115 m con una zona de coronación de
  40 × 30 m y la coronación a 125 m (el ancla de ``EXPL_10_60_6``, un banco por encima).
- **Las zonas de coronación** (:data:`CROWN_ZONES`; CE-016-04, CE-016-06): la del contrafuerte del Acopio 3 (sobre
  el levantamiento), una junto al límite legal y a una zona de «solo restauración» (:func:`restoration_constraint`,
  que **no** está en el proyecto) y una junto a la plataforma de carga de la 015, las dos sobre el terreno de la
  cantera.
- **La ladera y los espesores** (:func:`hillside`, :func:`thickness_sections`; CE-016-05, E5): una ladera con
  vaguada y 15 datos de espesor en tres secciones, en puntos, en líneas con el espesor en su Z, en líneas con él
  en su M y en polígonos (:data:`BODIES`: la huella del cuerpo y una sin datos).
- **Las capas del proyecto** (:func:`layers`, :class:`FieldsLayer`): marcas (``nombre``, ``margen``, ``material``,
  ``base``), coronaciones (``nombre``, ``cota``), huellas de cuerpos, espesores en puntos y en polígonos
  (``espesor``). **Las líneas con Z o con M no están en el proyecto**: la capa de entidades de la 006 guarda solo
  X e Y (``gis.vector.features_from_layer``: «la Z no cuenta»; la M la descarta ``core.gpkg.wkb``), así que son
  datos en memoria (hueco anotado en la verificación de la T01 para la T24 y la T25).
- **El proyecto** (:func:`project_template`, :class:`StockpileProjectCase`): el de la cantera de la 015 (con la
  rejilla gruesa de 2 m por defecto) más el levantamiento, el de antes y la ladera como rejillas, y las cinco
  capas. Se crea **una vez por proceso** y paso de rejilla (en ≤ 2 s de CPU: :data:`BUILD_BUDGET_S`, lo que añade a
  la cantera de la 015) y cada clase trabaja en su copia.
- **La escala** (:func:`scale_mounds`, :func:`scale_thickness`, :func:`scale_survey`; plan §7.1, para la T37): la
  rejilla de 1.654 × 1.699 celdas de 1 m (2,81 M), 100 marcas, 2.000 zonas candidatas antes de filtrar y 10.000
  datos de espesor. **Solo bajo demanda**: :func:`scale_survey` (el único que pesa) no se construye en
  ``check.py``.
"""

from __future__ import annotations

import atexit
import math
import shutil
import tempfile
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from tests.support import constraints_data as cdata
from tests.support import constraints_fixtures as cfx
from tests.support import constraints_project as cp
from tests.support import entity_fixtures as efx
from tests.support import quarry_fixtures as qfx
from tests.support.core_fixtures import FakeClock, FakePids, project_tmp
from tests.support.package import import_geoblender
from tests.support.stockpile_scale import (  # noqa: F401  (datos puros, también para Blender: se reexportan)
    SCALE_BUMPS, SCALE_MARKS, SCALE_SEED, SCALE_SOUTH, SCALE_THICKNESS, SCALE_WEST, SHAPES, Mound, mound_heights, scale_mounds,
    scale_survey, scale_thickness)

gis = import_geoblender("gis")

CRS = qfx.CRS
"""El CRS de la cantera (ETRS89 / UTM 30N)."""
VERTICAL = qfx.VERTICAL
"""La referencia vertical de las superficies (Alicante)."""
BASE: tuple[float, float] = qfx.BASE
"""La esquina suroeste de la cantera (m, absoluta)."""
GRID = qfx.GRID
"""La rejilla de la cantera: 400 × 400 celdas de 1 m de (0, 0) a (400, 400) locales."""
STEP_M = qfx.STEP_M
COARSE_STEP_M = qfx.COARSE_STEP_M
"""Los dos pasos de rejilla de los casos: 1 m (cuentas a mano) y 2 m (con proyecto)."""
WINDOW_M = 120.0
"""El lado de la ventana de los casos pequeños (m)."""
WINDOW_PIVOT = (60.0, 60.0)
"""El centro de la ventana (local): donde está el montón y el pivote de su plano."""
WINDOW_Z_M = 115.0
"""La cota del plano de la ventana en su pivote (m)."""


def _check_step(step_m: float) -> None:
    if step_m not in (STEP_M, COARSE_STEP_M):
        raise ValueError(f"el paso de los casos es {STEP_M} o {COARSE_STEP_M} m, no {step_m}")


def window_grid(step_m: float = STEP_M, size_m: float = WINDOW_M) -> Any:
    """La ventana de ``size_m`` m de lado con celdas de ``step_m`` m, de (0, 0) a (``size_m``, ``size_m``)
    locales (120 × 120 celdas con las de 1 m). ``ValueError`` si el paso no divide el lado."""
    cells = round(size_m / step_m)
    if cells < 1 or cells * step_m != size_m:
        raise ValueError(f"el paso de {step_m} m no divide el lado de {size_m} m de la ventana")
    return gis.Grid(BASE[0], BASE[1] + size_m, step_m, step_m, cells, cells)


def local_centers(grid: Any = GRID) -> tuple[np.ndarray, np.ndarray]:
    """Las coordenadas LOCALES (m desde :data:`BASE`) de los centros de celda de ``grid`` (por defecto
    :data:`GRID`; también una de :func:`qfx.grid_of` o :func:`window_grid`), de forma ``grid.shape`` (fila 0 al
    norte). ``ValueError`` si la rejilla no parte de la esquina suroeste de los casos."""
    if grid.west != BASE[0] or grid.north - grid.nrows * grid.dy != BASE[1]:
        raise ValueError("la rejilla no parte de la esquina suroeste de los casos (BASE): no tiene "
                         "coordenadas locales")
    columns = (np.arange(grid.ncols) + 0.5) * grid.dx
    rows = grid.nrows * grid.dy - (np.arange(grid.nrows) + 0.5) * grid.dy
    return np.meshgrid(columns, rows)


def in_box(box: tuple[float, float, float, float], grid: Any = GRID) -> np.ndarray:
    """Las celdas de ``grid`` con el centro dentro de la caja local ``(izquierda, abajo, derecha, arriba)``."""
    x, y = local_centers(grid)
    left, bottom, right, top = box
    return (x > left) & (x < right) & (y > bottom) & (y < top)


# --- Los planos ---------------------------------------------------------------------------------

AZIMUTH_DEG = 30.0
"""El azimut de la máxima pendiente de los planos inclinados (°, desde el norte de cuadrícula en sentido
horario): el plano sube hacia el nornoreste."""
TILTS_DEG: tuple[float, ...] = (0.0, 3.0, 8.0)
"""Las inclinaciones de los planos de los casos (°): llano, por debajo y por encima de los 4° de la detección."""


@dataclass(frozen=True, slots=True)
class Plane:
    """Un plano ``z = z_pivot + b·(x − xp) + c·(y − yp)`` con ``(xp, yp)`` el ``pivot`` (local), ``b = tan(i)·sen(az)``
    la pendiente al este y ``c = tan(i)·cos(az)`` la del norte, de inclinación ``tilt_deg`` (``i``, °) y azimut
    ``azimuth_deg`` (``az``, °)."""

    tilt_deg: float
    azimuth_deg: float
    pivot: tuple[float, float]
    z_pivot: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.tilt_deg < 45.0:
            raise ValueError(f"la inclinación del plano es de 0° a menos de 45°, no {self.tilt_deg}°")

    @property
    def east_slope(self) -> float:
        """La pendiente al este (m/m)."""
        return math.tan(math.radians(self.tilt_deg)) * math.sin(math.radians(self.azimuth_deg))

    @property
    def north_slope(self) -> float:
        """La pendiente al norte (m/m)."""
        return math.tan(math.radians(self.tilt_deg)) * math.cos(math.radians(self.azimuth_deg))

    def at(self, x: Any, y: Any) -> Any:
        """La cota del plano en ``(x, y)`` locales (escalares o arrays)."""
        return (self.z_pivot + self.east_slope * (x - self.pivot[0])
                + self.north_slope * (y - self.pivot[1]))

    def values(self, grid: Any = GRID) -> np.ndarray:
        """La cota del plano en los centros de ``grid`` (m, float64, nueva)."""
        x, y = local_centers(grid)
        return np.asarray(self.at(x, y), dtype=np.float64)


def plane(tilt_deg: float, *, pivot: tuple[float, float] = WINDOW_PIVOT,
          z_pivot: float = WINDOW_Z_M) -> Plane:
    """El plano de ``tilt_deg`` ° (:data:`AZIMUTH_DEG`) que pasa por ``z_pivot`` m en ``pivot``."""
    return Plane(float(tilt_deg), AZIMUTH_DEG, pivot, float(z_pivot))


# --- Los montones -------------------------------------------------------------------------------

# ``Mound`` y ``mound_heights`` están en ``stockpile_scale`` (datos puros: los usa también ``perf_stockpiles.py``, que corre
# dentro de Blender y no puede importar esta ayuda) y se reexportan aquí.

CONE = Mound("Cono de referencia", "cone", 60.0, 60.0, 20.0, 10.0, 5.0)
"""El tronco de cono de CE-016-02: pie de 20 m de radio, cima de 10 m y 5 m de altura (pendiente 0,5); el
analítico, π·5/3·(400 + 200 + 100) = 3.665,19 m³."""
PYRAMID = Mound("Pirámide de referencia", "pyramid", 60.0, 60.0, 20.0, 12.0, 4.0)
"""El tronco de pirámide de CE-016-02 y CE-016-10: pie de 20 m de semilado, cima de 12 m y 4 m de altura
(pendiente 0,5): 4.184 m³ en 1.600 celdas de 1 m, 1.444 sobre el umbral de 0,3 m (4.145 m³)."""

# Las ocho celdas atípicas de la corona (relativas al centro del montón, m; desviación, m): cuatro en la corona de
# la marca (a ≈ 25,5 m del centro por los ejes) y cuatro en la de la huella convergida (a 22,2 m: 21,5 m en un eje y
# 5,5 m en el otro, así que quedan fuera del pie tanto del cono como de la pirámide).
OUTLIER_SPEC: tuple[tuple[float, float, float], ...] = (
    (25.5, 0.5, 3.0), (-25.5, -0.5, 3.0), (-0.5, 25.5, -2.5), (0.5, -25.5, 3.0),
    (21.5, 5.5, 2.5), (-5.5, 21.5, -3.0), (-21.5, -5.5, 4.0), (5.5, -21.5, -2.0))
"""Las celdas atípicas de la corona: ``(dx, dy, desviación)``. Todas a más de 20 m del centro, con la distancia de
Chebyshev y con la euclídea (fuera del pie del montón sea pirámide o cono), de entre 2 y 4 m (más que el residuo
máximo de 1 m) y con suma +8 m."""
MARK_MARGIN_M = 4.0
"""Lo que la marca de un montón de :func:`mound_case` sobresale de su pie (m)."""


@dataclass(frozen=True, slots=True, eq=False)
class MoundCase:
    """Un montón sobre un plano en la ventana de :func:`window_grid`: la ``grid``, el ``plane``, el ``mound``, el
    plano en las celdas (``base``), la altura del montón (``height``), la desviación de las atípicas (``offsets``:
    0 donde no hay), el ``terrain`` (``base + height + offsets``), las celdas atípicas (``outliers``) y la marca
    (``mark_box`` local y ``mark``, su anillo ABSOLUTO, cerrado y antihorario, ``(5, 2)``)."""

    grid: Any
    plane: Plane
    mound: Mound
    base: np.ndarray
    height: np.ndarray
    offsets: np.ndarray
    terrain: np.ndarray
    outliers: np.ndarray
    mark_box: tuple[float, float, float, float]
    mark: np.ndarray


def mound_case(shape: str = "cone", tilt_deg: float = 3.0, *, outliers: bool = True,
               step_m: float = STEP_M) -> MoundCase:
    """El montón de referencia (``cone``: :data:`CONE`; ``pyramid``: :data:`PYRAMID`) sobre el plano de
    ``tilt_deg`` ° (:data:`TILTS_DEG`) con las celdas atípicas de :data:`OUTLIER_SPEC` (si ``outliers``; con celdas
    de 2 m, la más próxima a cada punto). ``ValueError`` si la forma o el paso no son de la lista."""
    _check_step(step_m)
    mounds = {"cone": CONE, "pyramid": PYRAMID}
    if shape not in mounds:
        raise ValueError(f"la forma del caso es una de {', '.join(mounds)}, no {shape!r}")
    mound, grid, found = mounds[shape], window_grid(step_m), plane(tilt_deg)
    x, y = local_centers(grid)
    base = found.values(grid)
    height = mound_heights(grid.shape, grid.dx, (mound,))
    offsets = np.zeros(grid.shape, dtype=np.float64)
    marked = np.zeros(grid.shape, dtype=bool)
    if outliers:
        for dx, dy, offset in OUTLIER_SPEC:
            nearest = (x - (mound.cx + dx)) ** 2 + (y - (mound.cy + dy)) ** 2
            row, col = np.unravel_index(int(np.argmin(nearest)), grid.shape)
            offsets[row, col], marked[row, col] = offset, True
    half = mound.foot + MARK_MARGIN_M
    box = (mound.cx - half, mound.cy - half, mound.cx + half, mound.cy + half)
    return MoundCase(grid, found, mound, base, height, offsets, base + height + offsets, marked, box,
                     cfx.rectangle(*box))


# --- El levantamiento: 5 marcados y 20 montículos sin marca (CE-016-01, E1) -----------------------

SURVEY_TILT_DEG = 3.0
SURVEY_PIVOT = (200.0, 200.0)
SURVEY_Z_M = 110.0
"""El plano del levantamiento: 3° por el centro de la rejilla a 110 m."""
PREVIOUS_LABEL = "levantamiento_previo"
"""El nombre de la superficie anterior (la base propia del Acopio 5, campo ``base`` de la capa de marcas)."""
SURVEY_LABEL = "levantamiento"
HILLSIDE_LABEL = "ladera"
TERRACE_BOX = (240.0, 200.0, 270.0, 240.0)
"""La terraza del levantamiento anterior (local): 30 × 40 = 1.200 celdas, de las que 450 están bajo el pie del
Acopio 5 (de (240, 205) a (255, 235))."""
TERRACE_M = 0.5
"""Lo que la terraza queda por encima del plano (m)."""
MATERIALS: tuple[str, ...] = ("mineral", "estéril")
"""Los materiales de las marcas (campo ``material``): dos, para las dos unidades antrópicas de CE-016-07."""


def _pyramid(name: str, cx: float, cy: float, foot: float, top: float, height: float) -> Mound:
    return Mound(name, "pyramid", cx, cy, foot, top, height)


SURVEY_MOUNDS: tuple[Mound, ...] = (
    # Los cinco marcados (el 4 es un cono; el 1 y el 2 se tocan; el 3, de 5 m, es el del contrafuerte de CE-016-04).
    _pyramid("Acopio 1", 100.0, 100.0, 12.0, 4.0, 4.0),
    _pyramid("Acopio 2", 120.0, 100.0, 12.0, 4.0, 4.0),
    _pyramid("Acopio 3", 240.0, 100.0, 14.0, 4.0, 5.0),
    Mound("Acopio 4", "cone", 130.0, 220.0, 16.0, 8.0, 4.0),
    _pyramid("Acopio 5", 240.0, 220.0, 15.0, 5.0, 5.0),
    # Los ocho que pasan los filtros: pendiente 0,5, de 5 a 6 m, con más de 250 m² sobre los 2 m.
    _pyramid("P1", 180.0, 100.0, 13.0, 3.0, 5.0), _pyramid("P2", 60.0, 160.0, 13.0, 1.0, 6.0),
    _pyramid("P3", 240.0, 160.0, 14.0, 4.0, 5.0), _pyramid("P4", 340.0, 160.0, 14.0, 2.0, 6.0),
    _pyramid("P5", 60.0, 220.0, 15.0, 5.0, 5.0), _pyramid("P6", 340.0, 220.0, 15.0, 3.0, 6.0),
    _pyramid("P7", 120.0, 280.0, 14.0, 4.0, 5.0), _pyramid("P8", 240.0, 280.0, 13.0, 3.0, 5.0),
    # Los cuatro pequeños: menos de 100 m² sobre los 2 m.
    _pyramid("S1", 340.0, 100.0, 9.0, 1.0, 4.0), _pyramid("S2", 180.0, 160.0, 8.0, 1.0, 3.5),
    _pyramid("S3", 180.0, 220.0, 9.0, 2.0, 3.5), _pyramid("S4", 60.0, 280.0, 7.0, 1.0, 3.0),
    # Los cuatro bajos: pendiente 0,25 y como mucho 1,5 m, menos que la altura mínima de 2 m.
    _pyramid("L1", 120.0, 160.0, 14.0, 8.0, 1.5), _pyramid("L2", 300.0, 160.0, 15.0, 9.0, 1.5),
    _pyramid("L3", 300.0, 220.0, 13.0, 7.0, 1.5), _pyramid("L4", 180.0, 280.0, 14.0, 10.0, 1.0),
    # Los cuatro fuera del perímetro de actuación (como los que pasan, pero al sur, al norte y al este).
    _pyramid("O1", 100.0, 30.0, 14.0, 4.0, 5.0), _pyramid("O2", 260.0, 30.0, 13.0, 3.0, 5.0),
    _pyramid("O3", 200.0, 372.0, 15.0, 5.0, 5.0), _pyramid("O4", 382.0, 200.0, 14.0, 2.0, 6.0),
)
"""Los 25 montículos del levantamiento, con los cinco marcados primero. Sus pies caben en la rejilla y están a
10 m o más unos de otros (salvo el Acopio 1 y el 2, que se solapan 4 m)."""
SURVEY_GROUPS: Mapping[str, tuple[str, ...]] = {
    "marked": ("Acopio 1", "Acopio 2", "Acopio 3", "Acopio 4", "Acopio 5"),
    "pass": ("P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"),
    "small": ("S1", "S2", "S3", "S4"),
    "low": ("L1", "L2", "L3", "L4"),
    "outside": ("O1", "O2", "O3", "O4"),
}
"""Los grupos: ``marked`` (5, con marca), ``pass`` (8 sin marca que pasan los filtros), ``small`` (4), ``low`` (4)
y ``outside`` (4, fuera del perímetro): 20 sin marca."""


def survey_mound(name: str) -> Mound:
    """El montículo del levantamiento llamado ``name``; ``KeyError`` si no está."""
    for mound in SURVEY_MOUNDS:
        if mound.name == name:
            return mound
    raise KeyError(name)


@dataclass(frozen=True, slots=True)
class Mark:
    """Una marca de la capa de marcas: su ``name`` (``nombre``), su caja local (un polígono orientativo de 20 × 20
    m), el montículo que marca, el ``margen`` en m (``None``: el de la detección), el ``material`` y la ``base``
    (el nombre de una superficie del proyecto; ``None``: el plano de la corona)."""

    name: str
    box: tuple[float, float, float, float]
    mound: str
    margin_m: float | None = None
    material: str | None = None
    base: str | None = None

    @property
    def ring(self) -> np.ndarray:
        """El anillo ABSOLUTO, cerrado y antihorario, de la marca (``(5, 2)``, nuevo)."""
        return cfx.rectangle(*self.box)

    def moved(self, dx: float, dy: float) -> Mark:
        """La misma marca con la caja trasladada ``(dx, dy)`` m."""
        left, bottom, right, top = self.box
        return replace(self, box=(left + dx, bottom + dy, right + dx, top + dy))


MARKS: tuple[Mark, ...] = (
    Mark("Acopio 1", (90.0, 90.0, 110.0, 110.0), "Acopio 1", None, "mineral"),
    Mark("Acopio 2", (110.0, 90.0, 130.0, 110.0), "Acopio 2", None, "mineral"),
    Mark("Acopio 3", (230.0, 90.0, 250.0, 110.0), "Acopio 3", 6.0, "estéril"),
    Mark("Acopio 4", (120.0, 210.0, 140.0, 230.0), "Acopio 4", None, "estéril"),
    Mark("Acopio 5", (230.0, 210.0, 250.0, 230.0), "Acopio 5", None, "mineral", PREVIOUS_LABEL),
)
"""Las cinco marcas. Las del Acopio 1 y 2 comparten el borde x = 110 y ninguna celda (se tocan, no se
solapan)."""


def survey_plane() -> Plane:
    """El plano del levantamiento: 3° por el centro de la rejilla a 110 m."""
    return plane(SURVEY_TILT_DEG, pivot=SURVEY_PIVOT, z_pivot=SURVEY_Z_M)


def previous_survey(grid: Any = GRID) -> np.ndarray:
    """El levantamiento anterior en los centros de ``grid`` (m, float64, nuevo): el plano de 3° más la terraza de
    0,5 m de :data:`TERRACE_BOX`. Es la base propia del Acopio 5."""
    terrace = in_box(TERRACE_BOX, grid)
    return survey_plane().values(grid) + np.where(terrace, TERRACE_M, 0.0)


def survey(grid: Any = GRID) -> np.ndarray:
    """El levantamiento en los centros de ``grid`` (m, float64, nuevo): el anterior más los 25 montículos
    (:data:`SURVEY_MOUNDS`; donde dos se solapan, el mayor)."""
    return previous_survey(grid) + mound_heights(grid.shape, grid.dx, SURVEY_MOUNDS)


@dataclass(frozen=True, slots=True, eq=False)
class PairCase:
    """Los dos acopios que se tocan en una ventana (:func:`touching_pair`): la ``grid``, el ``plane`` (3°), los dos
    ``mounds`` y ``marks`` (trasladados de los del levantamiento), el anillo absoluto de cada marca
    (``mark_rings``), la altura de la unión (``height``, el mayor de los dos), el plano (``base``) y el
    ``terrain`` (``base + height``)."""

    grid: Any
    plane: Plane
    mounds: tuple[Mound, ...]
    marks: tuple[Mark, ...]
    mark_rings: tuple[np.ndarray, ...]
    height: np.ndarray
    base: np.ndarray
    terrain: np.ndarray


PAIR_SHIFT = (-50.0, -40.0)
"""Lo que se traslada el Acopio 1 y 2 del levantamiento a la ventana de :func:`touching_pair`: quedan en (50, 60) y
(70, 60)."""


def touching_pair(step_m: float = STEP_M) -> PairCase:
    """El Acopio 1 y el 2 (E1, RF-016-06) en una ventana de 120 m sobre un plano de 3°: troncos de pirámide de pie
    12 m, cima 4 m y 4 m de altura, a 20 m uno de otro (los pies se solapan 4 m)."""
    _check_step(step_m)
    grid = window_grid(step_m)
    mounds = tuple(survey_mound(name).moved(*PAIR_SHIFT) for name in ("Acopio 1", "Acopio 2"))
    marks = tuple(mark.moved(*PAIR_SHIFT) for mark in MARKS[:2])
    found = plane(SURVEY_TILT_DEG)
    height = mound_heights(grid.shape, grid.dx, mounds)
    base = found.values(grid)
    return PairCase(grid, found, mounds, marks, tuple(mark.ring for mark in marks), height, base,
                    base + height)


# --- El acopio de 12 m junto a un relleno (CE-016-03; error 47) ---------------------------------------

TALL = Mound("Acopio de 12 m", "pyramid", 50.0, 60.0, 30.0, 6.0, 12.0)
"""El acopio alto: pie de 30 m de semilado, cima de 6 m y 12 m de altura: 17.864 m³."""
FILL_BOX = (72.0, 40.0, 108.0, 80.0)
"""El bloque de relleno (local): 36 × 40 celdas; pisa 8 columnas del pie del acopio."""
FILL_M = 3.0
"""La altura del relleno sobre el plano (m)."""
TALL_MARK_BOX = (25.0, 35.0, 75.0, 85.0)
"""La marca del acopio alto (local): 50 × 50 m; con 10 m de margen cubre el pie de 60 m."""


@dataclass(frozen=True, slots=True, eq=False)
class FillCase:
    """El acopio alto con el relleno (:func:`tall_stockpile_with_fill`): la ``grid``, el ``plane`` (0°, 115 m), el
    ``stockpile``, su altura (``stockpile_height``), el bloque (``fill``, máscara) y su altura (``fill_height``:
    ``fill_m`` dentro, 0 fuera), el plano (``base``), la superficie de partida (``start = base + máx(acopio,
    relleno)``) y la marca (``mark_box`` y ``mark``, su anillo absoluto)."""

    grid: Any
    plane: Plane
    stockpile: Mound
    stockpile_height: np.ndarray
    fill: np.ndarray
    fill_height: np.ndarray
    fill_m: float
    base: np.ndarray
    start: np.ndarray
    mark_box: tuple[float, float, float, float]
    mark: np.ndarray


def tall_stockpile_with_fill(step_m: float = STEP_M) -> FillCase:
    """El acopio de 12 m con un relleno de 3 m que se apoya en su pie y sale por fuera, sobre un plano llano a
    115 m en una ventana de 120 m (véase :data:`TALL`, :data:`FILL_BOX`)."""
    _check_step(step_m)
    grid = window_grid(step_m)
    found = plane(0.0)
    base = found.values(grid)
    stockpile = mound_heights(grid.shape, grid.dx, (TALL,))
    fill = in_box(FILL_BOX, grid)
    fill_height = np.where(fill, FILL_M, 0.0)
    return FillCase(grid, found, TALL, stockpile, fill, fill_height, FILL_M, base,
                    base + np.maximum(stockpile, fill_height), TALL_MARK_BOX,
                    cfx.rectangle(*TALL_MARK_BOX))


# --- El llano del contrafuerte (CE-016-10) -------------------------------------------------------

BUTTRESS_ZONE_LOCAL = (40.0, 45.0, 80.0, 75.0)
"""La zona de coronación del llano (local): 40 × 30 m = 1.200 celdas de 1 m, centrada en la ventana."""
BUTTRESS_CROWN_M = 125.0
"""Su coronación (m): el ancla de ``EXPL_10_60_6``, un banco de 10 m por encima del plano de 115 m."""


@dataclass(frozen=True, slots=True, eq=False)
class FlatCase:
    """Un plano de la ventana de :func:`window_grid` (``grid``, ``plane``, ``terrain``) con el anillo absoluto de
    la zona de coronación de :data:`BUTTRESS_ZONE_LOCAL` (``zone_ring``)."""

    grid: Any
    plane: Plane
    terrain: np.ndarray
    zone_ring: np.ndarray


def flat_window(tilt_deg: float = 0.0, step_m: float = STEP_M) -> FlatCase:
    """El plano de ``tilt_deg`` ° por 115 m en el centro de la ventana, para el contrafuerte de CE-016-10."""
    _check_step(step_m)
    grid = window_grid(step_m)
    found = plane(tilt_deg)
    return FlatCase(grid, found, found.values(grid), cfx.rectangle(*BUTTRESS_ZONE_LOCAL))


# --- Las zonas de coronación y la de solo restauración (CE-016-04, CE-016-06) ----------------------------


@dataclass(frozen=True, slots=True)
class CrownZone:
    """Una zona de coronación de la capa: su ``name``, su caja local, la cota de coronación (``cota``, m) y la
    superficie sobre la que se piensa (``survey``: el levantamiento; ``terrain``: el terreno de la cantera)."""

    name: str
    box: tuple[float, float, float, float]
    level_m: float
    surface: str

    @property
    def ring(self) -> np.ndarray:
        """El anillo ABSOLUTO de la zona (``(5, 2)``, nuevo)."""
        return cfx.rectangle(*self.box)


CROWN_ZONES: tuple[CrownZone, ...] = (
    CrownZone("Contrafuerte del acopio 3", (240.0, 100.0, 262.0, 122.0), 115.0, "survey"),
    CrownZone("Coronación junto al límite", (335.0, 300.0, 355.0, 330.0), 295.0, "terrain"),
    CrownZone("Coronación junto a la plataforma", (200.0, 290.0, 240.0, 310.0), 285.0, "terrain"),
)
"""Las tres zonas: la del contrafuerte que se apoya en el Acopio 3 (22 × 22 m, 196 celdas sobre el pie del acopio;
CE-016-04), la que está junto al límite legal (por el este, en la banda de 5 m hacia dentro, que empieza en x = 355)
y a la zona de solo restauración (por el oeste; 20 × 30 m; CE-016-06) y la que está junto a la plataforma de carga
de la 015 (por el norte de su huella, 40 × 20 m). Cada coronación es el ancla de ``EXPL_10_60_6`` (125 m) más un
número entero de bancos de 10 m y queda a más de 1 m sobre su superficie."""
RESTORATION_LOCAL = (305.0, 296.0, 335.0, 334.0)
"""La zona de solo restauración (local), junto a la zona de coronación del límite: 30 × 38 m."""
RESTORATION_CODE = "solo_restauracion"
"""El código de su restricción."""


def restoration_constraint() -> Any:
    """La restricción «solo restauración» sobre :data:`RESTORATION_LOCAL`, sin resguardo (``fid`` 0: nueva), lista
    para escribir con ``constraints_project.edit_constraints`` (junto a las de la cantera) y recompilar las
    máscaras. **No** está en el proyecto de la cantera ni en el de :func:`project_template`."""
    model = import_geoblender("core.constraints.model")
    store = import_geoblender("core.constraints.store")
    kind = model.GeometryKind.POLYGON
    return model.Constraint(
        uid=f"{RESTORATION_CODE:0<32}"[:32], code=RESTORATION_CODE, name="Solo restauración",
        ctype=model.ConstraintType.RESTORATION_ONLY, kind=kind,
        parts=((cfx.rectangle(*RESTORATION_LOCAL),),), priority=0,
        reason="Restricción sintética de la cantera", decided_by="Samuel (IMGA)",
        decided_on=date(2026, 11, 18), decision_uid=None, intention_uid=None, source_input=None,
        source_fid=None, layer=store.layer_of(kind), fid=0)


# --- La ladera y los espesores (CE-016-05, E5) ---------------------------------------------------------

HILL_Z0 = 150.0


def hillside_at(x: Any, y: Any) -> Any:
    """La cota de la ladera en ``(x, y)`` locales: ``150 + 0,25·y + 0,0625·x + (y − 200)²/256`` (exacta en binario
    en los centros de celda): sube al norte y al este y tiene una vaguada que baja hasta ``y = 168``."""
    return HILL_Z0 + 0.25 * y + 0.0625 * x + (y - 200.0) ** 2 / 256.0


def hillside(grid: Any = GRID) -> np.ndarray:
    """La ladera en los centros de ``grid`` (m, float64, nueva)."""
    x, y = local_centers(grid)
    return np.asarray(hillside_at(x, y), dtype=np.float64)


SECTIONS_Y = (140.5, 200.5, 260.5)
"""Las tres secciones (local, ``y``): líneas de este a oeste en centros de celda de 1 m (y dentro de una celda de
2 m: sin ambigüedad)."""
STATIONS_X = (100.5, 150.5, 200.5, 250.5, 299.5)
"""Las cinco estaciones de cada sección (local, ``x``)."""
THICKNESS_M = ((1.0, 2.0, 2.5, 2.0, 1.0), (1.5, 2.5, 3.0, 2.5, 1.5), (1.0, 2.0, 2.5, 2.0, 1.0))
"""El espesor (m) de cada estación de cada sección: suman 8,5; 11,0 y 8,5 m (28,0 m en total; medias de 1,7, 2,2 y
1,7 m)."""
BAND_Y = (140.0, 200.0, 260.0)
"""El centro de las bandas de los polígonos (local, ``y``): 200 × 20 m cada una."""


@dataclass(frozen=True, slots=True, eq=False)
class ThicknessSections:
    """Los 15 datos de espesor de las tres secciones: ``points`` (``(15, 3)``: X e Y absolutas y el espesor, por
    sección y por estación), ``lines_z`` (por sección, ``(5, 3)``: X, Y y el **espesor en la Z**), ``lines_m`` (por
    sección, ``(xyz, m)``: X, Y y la Z del **terreno** del vértice, y el **espesor en la M**) y ``polygons`` (por
    sección, ``(anillo absoluto, espesor)``: una banda de 200 × 20 m con el espesor medio de su sección)."""

    points: np.ndarray
    lines_z: tuple[np.ndarray, ...]
    lines_m: tuple[tuple[np.ndarray, np.ndarray], ...]
    polygons: tuple[tuple[np.ndarray, float], ...]


def thickness_sections() -> ThicknessSections:
    """Los datos de espesor de la ladera (arrays nuevos): véase :class:`ThicknessSections`."""
    rows = [(BASE[0] + x, BASE[1] + y, t) for y, section in zip(SECTIONS_Y, THICKNESS_M, strict=True)
            for x, t in zip(STATIONS_X, section, strict=True)]
    points = np.array(rows, dtype=np.float64)
    lines_z, lines_m = [], []
    for index, y in enumerate(SECTIONS_Y):
        section = points[index * len(STATIONS_X):(index + 1) * len(STATIONS_X)]
        lines_z.append(section.copy())
        ground = np.array([hillside_at(x, y) for x in STATIONS_X], dtype=np.float64)
        lines_m.append((np.column_stack([section[:, 0], section[:, 1], ground]), section[:, 2].copy()))
    polygons = tuple((cfx.rectangle(100.0, y - 10.0, 300.0, y + 10.0), float(np.mean(section)))
                     for y, section in zip(BAND_Y, THICKNESS_M, strict=True))
    return ThicknessSections(points, tuple(lines_z), tuple(lines_m), polygons)


@dataclass(frozen=True, slots=True)
class Body:
    """La huella de un cuerpo apoyado: su ``name`` y su caja local."""

    name: str
    box: tuple[float, float, float, float]


BODIES: tuple[Body, ...] = (
    Body("Cuerpo de la ladera", (90.0, 130.0, 310.0, 270.0)),
    Body("Cuerpo sin datos", (20.0, 345.0, 60.0, 380.0)),
)
"""Las huellas de cuerpos: la de la ladera (220 × 140 m, con los 15 datos dentro) y una sin ningún dato (RF-016-22)."""


# --- Las capas del proyecto -------------------------------------------------------------------------------

MARKS_LAYER = "gis_fea_acopios_marcas"
CROWN_LAYER = "gis_fea_coronacion"
BODIES_LAYER = "gis_fea_cuerpos"
THICKNESS_POINTS_LAYER = "gis_fea_espesor_puntos"
THICKNESS_POLYGONS_LAYER = "gis_fea_espesor_poligonos"
LAYERS: tuple[str, ...] = (MARKS_LAYER, CROWN_LAYER, BODIES_LAYER, THICKNESS_POINTS_LAYER,
                           THICKNESS_POLYGONS_LAYER)
"""Los nombres de las cinco capas, en el orden en que se escriben."""


@dataclass(frozen=True, slots=True, eq=False)
class FieldsLayer:
    """Una capa de entidades con campos de texto o numéricos: su nombre en el proyecto, su geometría (``polygon``,
    ``line`` o ``point``), sus entidades (por entidad, sus partes y, de cada una, sus anillos, su camino o su punto
    ``(1, 2)``, ABSOLUTOS), el nombre de cada una (campo ``nombre``) y sus campos (campo → valor por entidad,
    ``None`` donde falta). Como :class:`~tests.support.quarry_fixtures.LayerData`, pero con campos de texto."""

    name: str
    kind: str
    entities: tuple[tuple[tuple[np.ndarray, ...], ...], ...]
    names: tuple[str, ...]
    fields: Mapping[str, tuple[Any, ...]]


def _polygon(ring: np.ndarray) -> tuple[tuple[np.ndarray, ...], ...]:
    return ((ring,),)


def layers() -> tuple[FieldsLayer, ...]:
    """Las cinco capas (arrays nuevos), en el orden de :data:`LAYERS`."""
    data = thickness_sections()
    point_names = tuple(f"{section}{number}" for section in "ABC" for number in range(1, 6))
    return (
        FieldsLayer(MARKS_LAYER, "polygon", tuple(_polygon(mark.ring) for mark in MARKS),
                    tuple(mark.name for mark in MARKS),
                    {"margen": tuple(mark.margin_m for mark in MARKS),
                     "material": tuple(mark.material for mark in MARKS),
                     "base": tuple(mark.base for mark in MARKS)}),
        FieldsLayer(CROWN_LAYER, "polygon", tuple(_polygon(zone.ring) for zone in CROWN_ZONES),
                    tuple(zone.name for zone in CROWN_ZONES),
                    {"cota": tuple(zone.level_m for zone in CROWN_ZONES)}),
        FieldsLayer(BODIES_LAYER, "polygon", tuple(_polygon(cfx.rectangle(*body.box)) for body in BODIES),
                    tuple(body.name for body in BODIES), {}),
        FieldsLayer(THICKNESS_POINTS_LAYER, "point",
                    tuple(((point[None, :2].copy(),),) for point in data.points), point_names,
                    {"espesor": tuple(float(value) for value in data.points[:, 2])}),
        FieldsLayer(THICKNESS_POLYGONS_LAYER, "polygon", tuple(_polygon(ring) for ring, _t in data.polygons),
                    ("Banda A", "Banda B", "Banda C"),
                    {"espesor": tuple(thickness for _ring, thickness in data.polygons)}),
    )


def write_layer(project: Any, clock: FakeClock, layer: FieldsLayer) -> None:
    """Escribe ``layer`` como capa de entidades del proyecto, como la importación de la 006 y
    ``quarry_fixtures.write_feature_layer`` (que solo admite campos numéricos): el campo ``nombre`` y sus campos
    (``TEXT`` si alguno es un texto y ``DOUBLE`` si no), un minuto después."""
    from tests.support import design_fixtures as dfx
    from tests.support.provenance_contract import registered

    contract = import_geoblender("core.provenance.contract")
    operations = import_geoblender("core.provenance.operations")
    datasets = import_geoblender("core.datasets")
    builtin = import_geoblender("core.content.builtin")
    gstore = import_geoblender("gis.store")
    vector = import_geoblender("gis.vector")
    srs = int(project.record.crs_epsg)
    kinds = {field: "TEXT" if any(isinstance(item, str) for item in values) else "DOUBLE"
             for field, values in layer.fields.items()}
    columns = (vector.FieldColumn("nombre", "nombre", "TEXT"),
               *(vector.FieldColumn(field, field, kind) for field, kind in kinds.items()))
    values = {"nombre": layer.names, **{field: tuple(found) for field, found in layer.fields.items()}}
    fids = tuple(range(1, len(layer.entities) + 1))
    found = vector.FeatureLayer(layer.kind, fids, layer.entities, columns, values)
    rows = gstore.feature_rows(found, srs)
    names = ", ".join(f'"{column.column}" {column.sql_type}' for column in columns)
    marks = ", ".join("?" for _ in range(len(columns) + 2))
    writer = contract.OperationDef(dfx.LAYERS_TYPE, "1.0", "gis", "Layers of the tests", False)
    with registered(writer):
        clock.advance(minutes=1)
        handle = operations.begin_operation(project, dfx.LAYERS_TYPE, settings={"name": layer.name},
                                            executor="blender")
        with project.write_transaction() as conn:
            conn.execute(f'CREATE TABLE "{layer.name}" (fid INTEGER PRIMARY KEY NOT NULL, '
                         f"geom {found.geometry_type}, {names})")
            conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, description, srs_id) "
                         "VALUES (?, 'features', ?, '', ?)", (layer.name, layer.name, srs))
            conn.execute("INSERT INTO gpkg_geometry_columns (table_name, column_name, geometry_type_name, "
                         "srs_id, z, m) VALUES (?, 'geom', ?, ?, 0, 0)", (layer.name, found.geometry_type, srs))
            conn.executemany(f'INSERT INTO "{layer.name}" VALUES ({marks})', rows)
            handle.complete(conn, outputs=(datasets.DatasetSpec(
                layer.name, "gis", "vector", datasets.Store.GPKG, layer.name,
                reader=builtin.GPKG_LAYER.id, role="features", crs_epsg=srs, input_uid=None,
                immutable=False),), message="Capa de prueba de los acopios")


# --- El proyecto ------------------------------------------------------------------------------------------

BUILD_BUDGET_S = 2.0
"""Lo que añade la plantilla a la cantera de la 015 (copiarla y escribir tres rejillas y cinco capas) se construye
en ≤ 2 s de CPU (tarea T01)."""
SURVEY_DATASET = f"gis_dtm_{SURVEY_LABEL}"
PREVIOUS_DATASET = f"gis_dtm_{PREVIOUS_LABEL}"
HILLSIDE_DATASET = f"gis_dtm_{HILLSIDE_LABEL}"
"""Los datos de las tres rejillas del proyecto."""
_TEMPLATES: dict[float, dict[str, Any]] = {}


def _open(folder: Path, made: Mapping[str, Any], clock: FakeClock) -> Any:
    open_mod = import_geoblender("core.project.open")
    userdata = import_geoblender("core.userdata")
    return open_mod.open_project(folder / "proyectos" / made["name"], cp.SESSION,
                                 userdata.UserData(folder / "u"), clock=clock,
                                 pid_alive=FakePids({cp.SESSION.pid})).project


def _build(folder: Path, base: Mapping[str, Any], step_m: float) -> dict[str, Any]:
    """Copia el proyecto de la 015 ``base`` en ``folder``, le escribe las tres rejillas y las cinco capas y lo
    cierra."""
    from tests.support.res_fixtures import write_grids

    started = time.process_time()
    shutil.copytree(base["folder"] / "proyectos", folder / "proyectos")
    clock = FakeClock(base["now"])
    project = _open(folder, base, clock)
    try:
        grid = qfx.grid_of(step_m)
        clock.advance(minutes=1)
        write_grids(project, [
            (SURVEY_LABEL, gis.Raster(grid, survey(grid), CRS, VERTICAL)),
            (PREVIOUS_LABEL, gis.Raster(grid, previous_survey(grid), CRS, VERTICAL)),
            (HILLSIDE_LABEL, gis.Raster(grid, hillside(grid), CRS, VERTICAL))],
            message="Levantamientos y ladera de los acopios")
        for layer in layers():
            write_layer(project, clock, layer)
        clock.advance(minutes=1)
        return {"folder": folder, "name": base["name"], "now": clock.now(), "versions": base["versions"],
                "build_s": time.process_time() - started}
    finally:
        project.close()


def project_template(step_m: float = COARSE_STEP_M) -> Mapping[str, Any]:
    """El proyecto de la cantera de la 015 con la 016 (véase el módulo) con la rejilla de ``step_m`` m (por defecto
    la gruesa de 2 m), creado y cerrado la primera vez que se pide en el proceso con ese paso, en una carpeta
    temporal que se borra al salir: ``folder``, ``name`` de la carpeta del proyecto, ``now`` del reloj al
    terminar, los uid de ``versions`` (V01 y V02) y ``build_s``, la CPU que gastó **añadir lo de la 016** a la
    cantera de la 015 (s; la de la 014 y la de la 015 tienen la suya). No se modifica."""
    found = _TEMPLATES.get(step_m)
    if found is None:
        base = efx.project_template(step_m)  # antes del registro: construye la suya con el suyo
        folder = Path(tempfile.mkdtemp(prefix="gb-st-"))
        atexit.register(shutil.rmtree, folder, ignore_errors=True)
        with cp.constraints_registered():
            found = _TEMPLATES[step_m] = _build(folder, base, step_m)
    return found


@contextmanager
def open_stockpile_project(prefix: str = "gb-sp-", step_m: float = COARSE_STEP_M
                           ) -> Iterator[tuple[Any, FakeClock]]:
    """Una copia propia del proyecto de :func:`project_template` abierta en escritura: ``(project, clock)``. Al
    salir se cierra y se borra. Hace falta ``constraints_project.constraints_registered()`` activo (lo está en
    una :class:`StockpileProjectCase`)."""
    made = project_template(step_m)
    with project_tmp(prefix) as folder:
        shutil.copytree(made["folder"] / "proyectos", folder / "proyectos")
        clock = FakeClock(made["now"])
        project = _open(folder, made, clock)
        try:
            yield project, clock
        finally:
            project.close()


class StockpileProjectCase(qfx.QuarryProjectCase):
    """Una copia **por clase** del proyecto de :func:`project_template`, abierta en escritura: lo de
    :class:`~tests.support.quarry_fixtures.QuarryProjectCase` (``cls.project``, ``cls.root``, ``cls.clock``,
    ``cls.v1``, ``cls.v2``, ``cls.grid``, ``masks``, ``read_layer``, ``stale_causes``, ``recompute_plan``…), en
    la rejilla gruesa de 2 m salvo que la clase ponga otro ``STEP_M``, con el levantamiento, el de antes y la
    ladera (:data:`SURVEY_DATASET`, :data:`PREVIOUS_DATASET`, :data:`HILLSIDE_DATASET`) y las cinco capas de
    :data:`LAYERS`. Para partir de una instantánea del estado en que la deja una clase, ``entity_fixtures
    .open_copy_of``."""

    STEP_M: ClassVar[float] = COARSE_STEP_M

    @classmethod
    def setUpClass(cls) -> None:
        versions_read = import_geoblender("core.versions.read")
        cls.grid = qfx.grid_of(cls.STEP_M)
        made = project_template(cls.STEP_M)
        cls.enterClassContext(cp.constraints_registered())
        cls.project, cls.clock = cls.enterClassContext(open_stockpile_project("gb-sc-", cls.STEP_M))
        cls.root = Path(cls.project.root)
        with cls.project.read() as conn:
            cls.v1, cls.v2 = (versions_read.version(conn, uid) for uid in made["versions"])


# --- La escala (plan §7.1; T37): bajo demanda -----------------------------------------------------------

def scale_grid() -> Any:
    """La rejilla de escala: 1.654 × 1.699 celdas de 1 m (2,81 M), la de la 013."""
    return gis.Grid(cdata.WEST, cdata.SOUTH + cdata.ROWS * cdata.STEP_M, cdata.STEP_M, cdata.STEP_M,
                    cdata.COLS, cdata.ROWS)
