# SPDX-License-Identifier: GPL-3.0-or-later
"""La cantera de pruebas de las pistas y rampas (spec 017, T01; plan 017 §5.1, §7.1, §7.3 y §7.4; RF-017-02, 04, 08 a
18, 20, 24 y 25; CE-017-01 a 09; E1 a E5).

Todo es sintético (ningún dato de cliente), en coordenadas **absolutas** float64 (EPSG:25830 + EPSG:5782) desde la
esquina :data:`BASE` de ``tests.support.constraints_fixtures``, sobre la cantera de la 014 (``quarry_fixtures``), su
ampliación de la 015 (``entity_fixtures``) y las ayudas de la 016 (``stockpile_data``), que no se tocan. Las
coordenadas «locales» son metros desde la esquina suroeste de la rejilla (``x`` al este, ``y`` al norte); en las
rejillas, la fila 0 es el norte. Cada función que da un array da uno **nuevo**. Las cuentas de la docstring de cada
constante están hechas a mano; las comprueba ``tests/unit/design/test_road_fixtures.py``. **Todos los terrenos son
de la rejilla de la cantera** (400 × 400 m: de 1 m con las cifras a mano y de 2 m con proyecto, ≤ 200 × 200), así que
caben todos en el mismo proyecto como rejillas distintas y comparten las capas.

- **El perfil y los parámetros** (:data:`PROFILE`, :data:`ROUTE`, :data:`ACCESS`): los valores de referencia de IMGA de
  ``spec.md`` §11 (vehículo de 3,5 m, factor 3, arcén 0 m, caballón 1 m, pd 10 %, desmonte a 60° y terraplén a 35°, R
  20 m, Rmín 12 m; malla de 4 m, paso de cota de 0,28 m, λ = 2 1/m y 14 m de altura; hasta el 16 % y 300 m²), **solo para
  pruebas**, y los que la referencia no da (giro, holgura, simplificación y llegada de la ruta, el ancho mínimo
  transitable, el paso de las estaciones, pm y el alcance) como HIPÓTESIS sencillas y marcadas (decisión de la sesión
  principal T01-a: ninguna es valor por defecto del producto).
- **Los 16 rumbos** (:data:`ORACLE_HEADINGS`): una copia independiente de la lista de D-8 y D-23, para comparar con la
  de ``road_net``; y la ruta a ≤ 2,8 % de la recta (D-22).
- **La rampa del 4 %** (:func:`ramp_terrain`; CE-017-01): un plano de pendiente 4 % hacia el este (un rumbo de la
  rejilla), con y sin una pendiente transversal del 20 %; de (100, 200) a (300, 200): 200 m y 8 m de desnivel; el
  corte y el relleno de su calzada a mano (:func:`ramp_calzada_by_hand`: 500 m³ con celdas de 1 m).
- **El escalón** (:func:`step_terrain`; CE-017-03): 0 m hasta x = 200 y 6 m después, un eje de 200 m centrado en él; su
  rasante analítica (:func:`step_grade_by_hand`: rampa del 5 % de −60 a +60 m, 180 m·m), el eje corto de 100 m con
  los extremos a 0 y a 20 m («necesaria 200 m») y dos ejes 3D (uno irregular, con 2 tramos que pasan de pd).
- **Las esquinas** (:data:`CORNER_LONG`, :data:`CORNER_SHORT`; CE-017-02): dos tramos perpendiculares de 40 y de 15 m.
- **La ladera del 38 %** (:func:`hillside_terrain`; CE-017-04): con la curva de nivel a 22,5° del eje x; con 16 rumbos
  la menor pendiente de paso es del 2,7 % y con 8, del 14,5 %.
- **La franja de un nodo** (:func:`strip_allowed`; CE-017-04): una fila de 26 bloques de la malla de 4 m (el perímetro
  que solo la deja pasar), 100 m entre los centros de su primer y último nodo, un desnivel de 30 m (300 m
  necesarios) y, con un intocable, un nodo cerrado.
- **El barranco** (:func:`ravine_terrain`; plan §7.3): 14 m a medio camino de una ruta (de 320 m aquí y de 1,5 km a
  escala), perpendicular a ella.
- **El tajo** (:func:`pit_exploitation`, :func:`pit_final`, :func:`pit_after_fill`; CE-017-05, E2): terreno llano a
  141 m, un fondo de 80 × 80 m a 125 m con paredes 1:1, un corredor del 8 % que sube hasta el terreno; la final
  restaurada con el fondo relleno hasta 140 m (el corredor casi entero se rellena) y el «solo relleno» posterior.
- **La cantera con bancos** (:func:`bank_surface`; CE-017-07, E4): una entrada a 140 m, cuatro bermas de 8.000 m² a 135,
  125, 115 y 105 m separadas por caras de ≥ 83 %, tres rampas del 12,5 % que comunican las tres superiores (no la de
  105 m), una plataforma y dos zonas «requiere acceso» (una comunicada y otra no).
- **Las capas del proyecto** (:func:`layers`, :func:`breaklines`): puntos, ejes (con defectos), zonas de una cota,
  plataformas y puntos de entrada; y las líneas con Z (la tabla de líneas de rotura, la única que guarda la Z:
  ``docs/trampas.md`` §6).
- **Los oráculos propios** (:func:`oracle_slope_pct`, :func:`oracle_reachable`, :func:`erode`, :func:`opening`): la
  pendiente local, el alcance 4-conexo y la apertura de ancho, hechos aquí para comprobar los datos (y las tareas que los usan), no con el
  código de ``road_access``.
- **El proyecto** (:func:`project_template`, :class:`RoadProjectCase`): el de la cantera de la 015 con los terrenos
  como rejillas (:data:`RASTERS`) y las capas. Se crea **una vez por proceso** y paso de rejilla (en ≤ 2 s de CPU:
  :data:`BUILD_BUDGET_S`, lo que añade a la cantera de la 015) y cada clase trabaja en su copia. Las zonas «requiere
  acceso» **no** están en el proyecto (:func:`bank_zone_constraints` da las restricciones).
- **La escala** (:func:`scale_grid`, :func:`scale_ravine_terrain`, :func:`scale_axis_2km`, :func:`scale_axis_5km`,
  :func:`scale_preview_lines`, :func:`scale_berm_boxes`…; plan §7.3, para la T34): la rejilla de 1.654 × 1.699 celdas
  (2,81 M), una ruta de 1,5 km, un eje de 2 km con 61 curvas y otro de 5 km con 163 vértices, 20 pistas de 5.000
  vértices, 250 tramos de berma, 5 plataformas y 20 zonas. **Solo bajo demanda**: el terreno de la rejilla de 2,81 M
  celdas (:func:`scale_ravine_terrain`) no se construye en ``check.py``.
"""

from __future__ import annotations

import atexit
import math
import shutil
import tempfile
import time
from collections import deque
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import constraints_project as cp
from tests.support import entity_fixtures as efx
from tests.support import quarry_fixtures as qfx
from tests.support import stockpile_data as sdata
from tests.support.core_fixtures import FakeClock, FakePids, project_tmp
from tests.support.package import import_geoblender

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
SIDE_M = 400.0
"""El lado de la rejilla de los casos (m)."""


def grid_of(step_m: float = STEP_M) -> Any:
    """La rejilla de la cantera con celdas de ``step_m`` m (:data:`GRID` o la gruesa); ``ValueError`` si el paso no
    divide los 400 m del lado."""
    return qfx.grid_of(step_m)


def origin_of(grid: Any) -> tuple[float, float]:
    """La esquina suroeste (absoluta, float64) de ``grid``: el origen de sus coordenadas locales. La de la cantera
    es :data:`BASE`; la de la rejilla de escala, otra."""
    return float(grid.west), float(grid.north - grid.nrows * grid.dy)


def local_centers(grid: Any = GRID) -> tuple[np.ndarray, np.ndarray]:
    """Las coordenadas LOCALES (m desde la esquina suroeste de ``grid``) de sus centros de celda, de forma
    ``grid.shape`` (fila 0 al norte)."""
    columns = (np.arange(grid.ncols) + 0.5) * grid.dx
    rows = grid.nrows * grid.dy - (np.arange(grid.nrows) + 0.5) * grid.dy
    return np.meshgrid(columns, rows)


def in_box(box: tuple[float, float, float, float], grid: Any = GRID) -> np.ndarray:
    """Las celdas de ``grid`` con el centro estrictamente dentro de la caja local ``(izquierda, abajo, derecha,
    arriba)``."""
    x, y = local_centers(grid)
    left, bottom, right, top = box
    return (x > left) & (x < right) & (y > bottom) & (y < top)


def absolute(points: Sequence[Sequence[float]], grid: Any = GRID) -> np.ndarray:
    """Los puntos locales ``(x, y)`` en coordenadas absolutas, float64 ``(k, 2)``."""
    return np.asarray(points, dtype=np.float64).reshape(-1, 2) + np.asarray(origin_of(grid))


def raster_of(values: np.ndarray, grid: Any = GRID) -> Any:
    """``values`` como ``gis.Raster`` de ``grid``."""
    return gis.Raster(grid, values, CRS, VERTICAL)


def cell_of(point: tuple[float, float], grid: Any = GRID) -> tuple[int, int]:
    """La celda ``(fila, columna)`` de ``grid`` que contiene el punto local ``point`` (un punto en el borde de dos celdas
    va a la del este y a la del sur)."""
    return (int((grid.nrows * grid.dy - point[1]) // grid.dy), int(point[0] // grid.dx))


def bearing_point(origin: tuple[float, float], azimuth_deg: float, distance_m: float) -> tuple[float, float]:
    """El punto a ``distance_m`` m de ``origin`` con el azimut dado (desde el norte, sentido horario)."""
    angle = math.radians(azimuth_deg)
    return origin[0] + distance_m * math.sin(angle), origin[1] + distance_m * math.cos(angle)


def needed_length_m(drop_m: float, grade_pct: float) -> float:
    """La longitud mínima que pide un desnivel ``drop_m`` con la pendiente ``grade_pct`` %: ``|H| / pd`` (RF-017-08)."""
    return abs(drop_m) / (grade_pct / 100.0)


# --- El perfil de pista y los parámetros de la referencia ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProfileData:
    """Un perfil de pista como lo piden las pruebas (los nombres son los de ``RoadProfileParam`` del plan §5.2.2): el
    vehículo A, el factor f de carriles, el arcén y el caballón, pd, la estación ``w``, pm, R y Rmín, los dos
    ángulos del borde, el alcance, la clase (texto), el factor de malla y la métrica."""

    name: str
    vehicle_width_m: float
    lane_factor: float
    shoulder_m: float
    berm_m: float
    max_grade_pct: float
    station_step_m: float
    max_mean_grade_pct: float
    curve_radius_m: float
    min_radius_m: float
    cut_angle_deg: float
    fill_angle_deg: float
    reach_m: float
    class_name: str
    mesh_factor: float = 1.0
    metric: str = "exact"

    @property
    def carriageway_m(self) -> float:
        """La calzada: ``f·A``."""
        return self.lane_factor * self.vehicle_width_m

    @property
    def section_m(self) -> float:
        """La anchura de la sección: la calzada más el arcén y el caballón."""
        return self.carriageway_m + self.shoulder_m + self.berm_m

    @property
    def half_section_m(self) -> float:
        """La semianchura de la sección (el radio mínimo no puede ser menor: RF-017-04)."""
        return self.section_m / 2.0


PROFILE = ProfileData("Pista de referencia", 3.5, 3.0, 0.0, 1.0, 10.0, 1.0, 10.0, 20.0, 12.0, 60.0, 35.0, 60.0,
                      "Pista de acceso")
"""El perfil de referencia de IMGA (``spec.md`` §11, **solo para pruebas**; fuente 00 §3.9, 01 §2.11 y 03 §3.9):
vehículo de 3,5 m, factor 3 (calzada 10,5 m), arcén 0 m, caballón 1 m (sección 11,5 m, semianchura 5,75 m), pd 10 %,
R 20 m, Rmín 12 m, desmonte a 60° y terraplén a 35°, métrica exacta y factor de malla 1,0 (ADOPTADOS «sin
confirmar»). **HIPÓTESIS de la prueba** (la referencia no los da): estación ``w`` de 1 m (la de RNF-017-03 y 04), pm
10 % (ITC-07.1.03-1.5.2: la media ≤ 10 %) y alcance 60 m (el de §7.3 del plan)."""


def profile_with(**changes: Any) -> ProfileData:
    """:data:`PROFILE` con los campos pedidos cambiados (``TypeError`` si alguno no existe)."""
    return replace(PROFILE, **changes)


@dataclass(frozen=True, slots=True)
class RouteData:
    """Los parámetros de la ruta (``RouteParams`` del plan §5.2.2): la malla, el paso de cota, la altura máxima de
    desmonte y terraplén, λ, la penalización de giro, la holgura del pasillo, la tolerancia de simplificación, la de
    llegada y el presupuesto de estados."""

    mesh_m: float
    level_step_m: float
    max_cut_fill_m: float
    lambda_per_m: float
    turn_m: float
    margin_m: float
    simplify_m: float
    arrival_tol_m: float
    search_budget: int


ROUTE = RouteData(4.0, 0.28, 14.0, 2.0, 4.0, 60.0, 4.0, 0.28, 5_000_000)
"""Los parámetros de la ruta de referencia: malla de 4 m, paso de cota de 0,28 m (el 7 % de un paso recto), 14 m de
altura (``s115``) y λ = 2 1/m (``spec.md`` §11); el presupuesto de 5 M estados (P-3, ADOPTADO «sin confirmar»). Los
cuatro de :data:`ROUTE_HYPOTHESES` son **HIPÓTESIS sencillas de la prueba** (T01-a): un paso de giro (4 m), la holgura
de 60 m de RNF-017-02, un nodo de simplificación (4 m) y un paso de cota de llegada (0,28 m); ninguno es valor por
defecto del producto."""
ROUTE_HYPOTHESES: tuple[str, ...] = ("turn_m", "margin_m", "simplify_m", "arrival_tol_m")
"""Los campos de :data:`ROUTE` que no son de la referencia de IMGA."""


def route_with(**changes: Any) -> RouteData:
    """:data:`ROUTE` con los campos pedidos cambiados."""
    return replace(ROUTE, **changes)


@dataclass(frozen=True, slots=True)
class AccessData:
    """Los parámetros de la accesibilidad (plan §5.2.2): pendiente transitable (%), ancho mínimo (m) y área mínima de
    berma (m²)."""

    walk_slope_pct: float
    walk_width_m: float
    min_berm_area_m2: float


ACCESS = AccessData(16.0, 4.0, 300.0)
"""Los de la referencia (hasta el 16 % y 300 m², ``spec.md`` §11) y el ancho mínimo, que no da: 4 m, HIPÓTESIS de la
prueba (D-17)."""

# --- Los 16 rumbos --------------------------------------------------------------------------------------------

ORACLE_HEADINGS: tuple[tuple[int, int], ...] = (
    (0, 1), (1, 2), (1, 1), (2, 1), (1, 0), (2, -1), (1, -1), (1, -2),
    (0, -1), (-1, -2), (-1, -1), (-2, -1), (-1, 0), (-2, 1), (-1, 1), (-1, 2))
"""Los 16 pasos ``(dx, dy)`` en sentido horario desde el norte (D-8, D-23): una copia **independiente** de la lista de
``road_net`` (las pruebas de esta la comparan con esta)."""
DETOUR_BOUND_PCT = 2.8
"""Lo que la ruta puede pasar de la distancia recta en un plano sin restricciones (D-22, CE-017-01): con 16 rumbos el
mayor hueco entre dos es de 26,565° y 1/cos(13,28°) − 1 = 2,75 %."""


def heading_azimuth_deg(step: tuple[int, int]) -> float:
    """El azimut (°, desde el norte en sentido horario, de 0 a 360) del paso ``(dx, dy)``."""
    return math.degrees(math.atan2(step[0], step[1])) % 360.0


# --- La rampa del 4 % (CE-017-01) -----------------------------------------------------------------------------

RAMP_Z0_M = 100.0
"""La cota del plano de la rampa en x = 0 (m)."""
RAMP_SLOPE_PCT = 4.0
"""La pendiente del plano hacia el este (%): un rumbo de la rejilla."""
RAMP_CROSS_PCT = 20.0
"""La pendiente transversal (hacia el norte) de la variante con ella (%)."""
RAMP_AXIS_Y_M = 200.0
"""La y del eje y la de la pendiente transversal nula (un borde de celda en 1 y en 2 m)."""
RAMP_ORIGIN: tuple[float, float] = (100.0, 200.0)
RAMP_DESTINATION: tuple[float, float] = (300.0, 200.0)
"""El origen y el destino de la rampa (locales): 200,000 m hacia el este."""
RAMP_LENGTH_M = 200.0
"""Su longitud (m)."""
RAMP_DROP_M = 8.0
"""Su desnivel (m): 0,04 · 200; las cotas del terreno van de 104 a 112 m."""


def ramp_terrain(grid: Any = GRID, *, cross_pct: float = 0.0) -> np.ndarray:
    """El plano de la rampa en los centros de ``grid`` (m, float64): ``100 + 0,04·x + (cross_pct/100)·(y − 200)``."""
    x, y = local_centers(grid)
    return RAMP_Z0_M + RAMP_SLOPE_PCT / 100.0 * x + cross_pct / 100.0 * (y - RAMP_AXIS_Y_M)


@dataclass(frozen=True, slots=True)
class CalzadaByHand:
    """El corte y el relleno de la calzada de la rampa con la pendiente transversal, a mano: las filas por lado de
    celdas de la calzada, las columnas a lo largo del eje y los m³."""

    rows_per_side: int
    columns: int
    cut_m3: float
    fill_m3: float


def ramp_calzada_by_hand(step_m: float = STEP_M, cross_pct: float = RAMP_CROSS_PCT,
                         carriageway_m: float | None = None, length_m: float = RAMP_LENGTH_M) -> CalzadaByHand:
    """La calzada (|y − 200| ≤ calzada/2) de la rampa con la rasante en el terreno del eje: cada celda a ``(k + ½)·h``
    del eje se aparta ``cross·(k + ½)·h`` m; con ``n`` filas por lado, Σ = ``cross·h·n²/2`` m por columna y, por
    ``h²`` de área y ``L/h`` columnas, ``cross·n²·h²·L/2`` m³ de corte (al norte) y los mismos de relleno (al sur)."""
    width = PROFILE.carriageway_m if carriageway_m is None else carriageway_m
    rows = math.floor(width / (2.0 * step_m) - 0.5) + 1
    volume = cross_pct / 100.0 * rows * rows * step_m * step_m * length_m / 2.0
    return CalzadaByHand(rows, round(length_m / step_m), volume, volume)


# --- El escalón (CE-017-03) ---------------------------------------------------------------------------------

STEP_X_M = 200.0
"""La x del escalón (la abscisa 0 del eje de 200 m centrado en él)."""
STEP_LOW_M = 0.0
STEP_HIGH_M = 6.0
"""Las cotas del terreno antes (0 m) y después (6 m) del escalón."""
STEP_AXIS: tuple[tuple[float, float], tuple[float, float]] = ((100.0, 200.0), (300.0, 200.0))
"""El eje del escalón (local): 200 m de oeste a este, de la abscisa −100 a la +100."""
STEP_RAMP_PCT = 5.0
STEP_RAMP_FROM_M = -60.0
STEP_RAMP_TO_M = 60.0
"""Con pd = 10 % la rasante es una rampa del 5 % (pd/2) entre las abscisas −60 y +60 m."""
STEP_DIFF_MM = 180.0
"""La diferencia con el terreno suma 180 m·m (con pd = 10 %: ``18/pd``)."""
STEP_MEAN_PCT = 3.0
"""La pendiente media de la rampa del escalón: 6 m sobre 200 m, el 3 %."""
SHORT_AXIS: tuple[tuple[float, float], tuple[float, float]] = ((100.0, 300.0), (200.0, 300.0))
"""Un eje de 100 m (local) para el rechazo de la rasante (RF-017-16)."""
SHORT_Z_START_M = 0.0
SHORT_Z_END_M = 20.0
"""Sus cotas de inicio y de fin: 20 m de desnivel."""
SHORT_NEEDED_M = 200.0
"""La longitud que piden con pd = 10 % (20 / 0,10): «necesaria 200 m, el eje mide 100 m»."""


def step_terrain(grid: Any = GRID) -> np.ndarray:
    """El terreno en escalón en los centros de ``grid`` (m): 0 m al oeste de x = 200 y 6 m al este; no cambia con y."""
    x, _y = local_centers(grid)
    return np.where(x < STEP_X_M, STEP_LOW_M, STEP_HIGH_M)


def step_profile_m(s: Any) -> np.ndarray:
    """El perfil continuo del terreno en la abscisa ``s`` del eje: 0 m para ``s < 0`` y 6 m desde ``s = 0``."""
    return np.where(np.asarray(s, dtype=np.float64) < 0.0, STEP_LOW_M, STEP_HIGH_M)


def step_grade_by_hand(s: Any, grade_pct: float) -> np.ndarray:
    """La rasante analítica del escalón con pd = ``grade_pct`` %: la media de las dos envolventes de pendiente pd, que
    es ``3 + (pd/2)·s`` recortada a [0, 6] (una rampa de pendiente pd/2 entre ``∓6/pd`` m)."""
    return np.clip(3.0 + (grade_pct / 100.0) / 2.0 * np.asarray(s, dtype=np.float64), STEP_LOW_M, STEP_HIGH_M)


def step_diff_by_hand(grade_pct: float) -> float:
    """``∫|rasante − terreno| ds`` del escalón (m·m): ``18/pd`` (180 con pd = 10 %)."""
    return 18.0 / (grade_pct / 100.0)


AXIS_3D_START_Z_M = 104.0
"""La cota del primer vértice de los ejes 3D (la del plano de la rampa en x = 100)."""
AXIS_3D_INCREMENTS_M: tuple[float, ...] = (1.0, 1.0, 2.0, 3.0, -0.4, 1.6, 2.4, 0.0, 1.0, 2.0)
"""Lo que sube la Z en cada tramo de 20 m del eje 3D irregular."""
AXIS_3D_SLOPES_PCT: tuple[float, ...] = (5.0, 5.0, 10.0, 15.0, -2.0, 8.0, 12.0, 0.0, 5.0, 10.0)
"""Sus pendientes por tramo (%): con pd = 10 % pasan el 4.º (15 %) y el 7.º (12 %); los de 10 % exactos no."""
AXIS_3D_MEAN_PCT = 7.2
"""Su pendiente media Σ|Δz|/S: 14,4 m sobre 200 m."""


def _axis_3d(increments: Sequence[float]) -> np.ndarray:
    z = AXIS_3D_START_Z_M + np.concatenate(([0.0], np.cumsum(increments)))
    local = np.column_stack([100.0 + 20.0 * np.arange(len(z)), np.full(len(z), 250.0)])
    return np.column_stack([absolute(local), z])


def axis_3d_irregular() -> np.ndarray:
    """La línea con Z irregular (11 vértices ``(x, y, z)`` absolutos, float64): de (100, 250) a (300, 250), tramos de
    20 m con las pendientes de :data:`AXIS_3D_SLOPES_PCT`."""
    return _axis_3d(AXIS_3D_INCREMENTS_M)


def axis_3d_smooth() -> np.ndarray:
    """La línea con Z que sigue el plano del 4 %: los mismos vértices y, en cada tramo, el 4 % (0,8 m)."""
    return _axis_3d((0.04 * 20.0,) * 10)


# --- Las esquinas (CE-017-02) -------------------------------------------------------------------------------

CORNER_LONG: tuple[tuple[float, float], ...] = ((60.0, 60.0), (100.0, 60.0), (100.0, 100.0))
"""Dos tramos perpendiculares de 40 m (local): con R = 20 m, tangente 20 m, arco de 31,416 m y 71,416 m de eje."""
CORNER_SHORT: tuple[tuple[float, float], ...] = ((60.0, 140.0), (75.0, 140.0), (75.0, 155.0))
"""Dos tramos perpendiculares de 15 m (local): con R = 20 m el que cabe es el de 15 m."""


@dataclass(frozen=True, slots=True)
class CornerByHand:
    """Una esquina de dos tramos iguales a 90°: la tangente, el radio que cabe (el menor entre el pedido y el tramo,
    porque ``T = R·tan 45° = R``), el arco y la longitud del eje."""

    tangent_m: float
    fitted_radius_m: float
    arc_m: float
    length_m: float


def corner_by_hand(leg_m: float, radius_m: float) -> CornerByHand:
    """La esquina a 90° de dos tramos de ``leg_m`` m con el radio pedido ``radius_m`` m (RF-017-13, 14)."""
    fitted = min(radius_m, leg_m)
    tangent = fitted * math.tan(math.radians(45.0))
    arc = math.pi / 2.0 * fitted
    return CornerByHand(tangent, fitted, arc, 2.0 * (leg_m - tangent) + arc)


# --- La ladera del 38 % (CE-017-04) ----------------------------------------------------------------------------

HILL_SLOPE_PCT = 38.0
"""La pendiente de la ladera (%)."""
HILL_CONTOUR_DEG = 22.5
"""El ángulo de la curva de nivel con el eje x de la rejilla (°): con 16 rumbos la menor pendiente de paso es del
2,7 % y con 8, del 14,5 %."""
HILL_Z0_M = 100.0
"""La cota en el pivote (200, 200) (m)."""
HILL_ORIGIN: tuple[float, float] = (100.0, 100.0)
HILL_DESTINATION: tuple[float, float] = (180.0, 140.0)
"""Una ruta de diez pasos del rumbo (2, 1) de una malla de 4 m ((8, 4) m cada uno): 89,443 m con 2,409 m de
desnivel (2,69 %)."""
HILL_STEPS = 10
"""Los pasos de esa ruta."""


def hillside_terrain(grid: Any = GRID) -> np.ndarray:
    """La ladera en los centros de ``grid`` (m): ``100 + 0,38·(−(x − 200)·sen 22,5° + (y − 200)·cos 22,5°)``, la
    pendiente máxima perpendicular a la curva de nivel."""
    x, y = local_centers(grid)
    angle = math.radians(HILL_CONTOUR_DEG)
    return HILL_Z0_M + HILL_SLOPE_PCT / 100.0 * (-(x - 200.0) * math.sin(angle) + (y - 200.0) * math.cos(angle))


def hillside_heading_slope_pct(dx: int, dy: int) -> float:
    """La pendiente (%) del terreno de la ladera a lo largo del paso ``(dx, dy)``: ``38·|sen(φ − 22,5°)|``."""
    return HILL_SLOPE_PCT * abs(math.sin(math.atan2(dy, dx) - math.radians(HILL_CONTOUR_DEG)))


# --- La franja de un nodo (CE-017-04) -----------------------------------------------------------------------------

STRIP_SLOPE_PCT = 30.0
"""La pendiente del terreno de la franja hacia el este (%)."""
STRIP_BOX: tuple[float, float, float, float] = (100.0, 196.0, 204.0, 200.0)
"""El perímetro que solo deja pasar la franja (local): 104 × 4 m, una fila de 26 bloques de 4 × 4 m alineados con
la malla de la ruta (que cuenta desde el oeste y el norte): 416 m²."""
STRIP_ORIGIN: tuple[float, float] = (102.0, 198.0)
STRIP_DESTINATION: tuple[float, float] = (202.0, 198.0)
"""Los centros del primer y del último nodo: 100 m de largo."""
STRIP_Z_ORIGIN_M = 100.0
"""La cota del terreno en el origen (m); en el destino, 130 m (30 m de desnivel)."""
STRIP_NEEDED_M = 300.0
"""Lo que pide ese desnivel con pd = 10 % (30 / 0,10 m)."""
STRIP_REACH_M = 10.0
"""Lo que sube la rasante desde el origen en los 100 m con pd = 10 %: la cota mayor alcanzada es la del origen + 10 m
(si la altura máxima de desmonte y terraplén de la prueba no la corta antes: hacen falta ≥ 20 m)."""
STRIP_UNTOUCHABLE_BOX: tuple[float, float, float, float] = (148.0, 194.0, 152.0, 202.0)
"""La zona del intocable que cierra el único paso (local): cruza la franja de lado a lado (más ancha que ella) y
quita un nodo, el de 148 a 152 m."""
STRIP_UNTOUCHABLE_NAME = "Intocable de la franja"
"""El nombre de la restricción del intocable."""


def strip_terrain(grid: Any = GRID) -> np.ndarray:
    """El terreno de la franja en los centros de ``grid`` (m): ``100 + 0,30·(x − 102)``."""
    x, _y = local_centers(grid)
    return STRIP_Z_ORIGIN_M + STRIP_SLOPE_PCT / 100.0 * (x - STRIP_ORIGIN[0])


def strip_forbidden(grid: Any = GRID) -> np.ndarray:
    """Las celdas de la zona del intocable (que la ruta no puede pisar)."""
    return in_box(STRIP_UNTOUCHABLE_BOX, grid)


def strip_allowed(grid: Any = GRID, *, untouchable: bool = False) -> np.ndarray:
    """Las celdas por las que la ruta puede pasar: las de la franja y, con ``untouchable``, sin las del intocable."""
    found = in_box(STRIP_BOX, grid)
    return found & ~strip_forbidden(grid) if untouchable else found


# --- El barranco (plan §7.3) -----------------------------------------------------------------------------------

RAVINE_DEPTH_M = 14.0
"""El fondo del barranco (m)."""
RAVINE_X_M = 200.0
"""La x de su eje (norte-sur: perpendicular a la ruta, que va al este) y el punto medio de la ruta."""
RAVINE_HALF_WIDTH_M = 30.0
"""Su semiancho: una V de flancos del 46,7 % (HIPÓTESIS de la forma, que el plan no versiona)."""
RAVINE_ORIGIN: tuple[float, float] = (40.0, 200.0)
RAVINE_DESTINATION: tuple[float, float] = (360.0, 200.0)
"""Una ruta de 320 m que cruza el barranco a medio camino (la de 1,5 km es la de :func:`scale_ravine_spec`)."""


def ravine_depth_m(x: Any, *, axis_x: float = RAVINE_X_M, half_width_m: float = RAVINE_HALF_WIDTH_M,
                   depth_m: float = RAVINE_DEPTH_M) -> np.ndarray:
    """Lo que el barranco baja el terreno en la abscisa ``x`` (m): ``depth·máx(0, 1 − |x − axis|/semiancho)``."""
    return depth_m * np.maximum(0.0, 1.0 - np.abs(np.asarray(x, dtype=np.float64) - axis_x) / half_width_m)


def ravine_terrain(grid: Any = GRID, *, axis_x: float = RAVINE_X_M, half_width_m: float = RAVINE_HALF_WIDTH_M,
                   depth_m: float = RAVINE_DEPTH_M) -> np.ndarray:
    """El plano del 4 % de la rampa con el barranco en los centros de ``grid`` (m): no cambia con y."""
    x, _y = local_centers(grid)
    return RAMP_Z0_M + RAMP_SLOPE_PCT / 100.0 * x - ravine_depth_m(
        x, axis_x=axis_x, half_width_m=half_width_m, depth_m=depth_m)


# --- El tajo (CE-017-05, E2) ----------------------------------------------------------------------------------

PIT_GROUND_M = 141.0
"""El terreno llano que rodea el tajo (m)."""
PIT_FLOOR_BOX: tuple[float, float, float, float] = (60.0, 120.0, 140.0, 200.0)
"""El fondo (local): 80 × 80 m, 6.400 m²."""
PIT_FLOOR_M = 125.0
"""La cota del fondo de la explotación (m)."""
PIT_CORRIDOR_BOX: tuple[float, float, float, float] = (140.0, 150.0, 340.0, 170.0)
"""El corredor (local): 20 m de ancho y 200 m desde el este del fondo, a lo largo de y = 160."""
PIT_CORRIDOR_PCT = 8.0
"""Su rasante, 125 + 0,08·(x − 140): 141 m (el terreno) en x = 340."""
PIT_RESTORED_M = 140.0
"""El fondo relleno de la superficie final restaurada (m): del corredor solo queda lo que pasa de 140 m (de x = 327,5)."""
PIT_FILL_BOX: tuple[float, float, float, float] = (80.0, 140.0, 120.0, 180.0)
"""La zona del «solo relleno» posterior (local), dentro del fondo: 40 × 40 m."""
PIT_FILL_LEVEL_M = 130.0
"""La cota a la que lo sube (m): 5 m sobre el fondo, 1.600 celdas, 8.000 m³."""
PIT_ORIGIN: tuple[float, float] = (345.0, 160.0)
"""El origen de la pista del tajo (local): el terreno al final del corredor."""
PIT_ENTRY: tuple[float, float] = (350.0, 160.0)
"""La entrada de la accesibilidad del tajo (local)."""
PIT_DESTINATION: tuple[float, float] = (100.0, 160.0)
"""El destino (local): el centro del fondo, a 125 m (dentro de la zona de :data:`ZONES`)."""
PIT_Z_MIN_EXPLOITATION_M = 125.0
PIT_Z_MIN_FINAL_M = 140.0
"""La cota mínima alcanzable sobre la explotación (el fondo, por el corredor) y sobre la final (el fondo relleno, por lo
que queda del corredor): el error 23."""


def pit_exploitation(grid: Any = GRID) -> np.ndarray:
    """La superficie de explotación en los centros de ``grid`` (m): terreno a 141 m, el fondo a 125 m, paredes 1:1
    (``125 + distancia al fondo``, tope 141 m, con la distancia de Chebyshev a la caja) y el corredor, que baja el
    terreno a su rasante ``125 + 0,08·(x − 140)``."""
    x, y = local_centers(grid)
    left, bottom, right, top = PIT_FLOOR_BOX
    dx = np.maximum(np.maximum(left - x, x - right), 0.0)
    dy = np.maximum(np.maximum(bottom - y, y - top), 0.0)
    base = np.minimum(PIT_FLOOR_M + np.maximum(dx, dy), PIT_GROUND_M)
    rasante = PIT_FLOOR_M + PIT_CORRIDOR_PCT / 100.0 * (x - PIT_CORRIDOR_BOX[0])
    return np.where(in_box(PIT_CORRIDOR_BOX, grid), np.minimum(base, rasante), base)


def pit_final(grid: Any = GRID) -> np.ndarray:
    """La superficie final restaurada: la explotación con el fondo relleno hasta 140 m (``máx(explotación, 140)``)."""
    return np.maximum(pit_exploitation(grid), PIT_RESTORED_M)


def pit_after_fill(grid: Any = GRID) -> np.ndarray:
    """La explotación con el «solo relleno» posterior: la zona :data:`PIT_FILL_BOX` sube a 130 m."""
    found = pit_exploitation(grid)
    return np.where(in_box(PIT_FILL_BOX, grid), PIT_FILL_LEVEL_M, found)


# --- La cantera con bancos y una rampa (CE-017-07, E4) --------------------------------------------------------

BANK_PROFILE_Y: tuple[float, ...] = (0.0, 40.0, 46.0, 66.0, 76.0, 96.0, 106.0, 126.0, 136.0, 156.0, 192.0, 400.0)
BANK_PROFILE_Z: tuple[float, ...] = (140.0, 140.0, 135.0, 135.0, 125.0, 125.0, 115.0, 115.0, 105.0, 105.0, 140.0,
                                     140.0)
"""El perfil en ``y`` (no depende de ``x``, fuera de las rampas): terreno llano a 140 m (la entrada) al sur, una cara de
5 m en 6 m (83 %), una berma de 20 m a 135 m, una cara de 10 m en 10 m (100 %), la berma de 125 m, la cara, la de
115 m, la cara, la de 105 m y una pared de 35 m en 36 m (97 %) hasta el terreno del norte, a 140 m."""
BANK_ENTRANCE_M = 140.0
"""La cota de la entrada (el terreno del sur)."""
BANK_LEVELS: tuple[float, ...] = (135.0, 125.0, 115.0, 105.0)
"""Las cotas de las cuatro bermas."""
BANK_BERM_RANGES: tuple[tuple[float, float], ...] = ((46.0, 66.0), (76.0, 96.0), (106.0, 126.0), (136.0, 156.0))
"""El rango de ``y`` de cada berma: 400 × 20 m = 8.000 m² (≥ 300 m²)."""
BANK_BERM_AREA_M2 = 8_000.0
"""El área de cada berma (m²), entera, sin descontar lo que graban las rampas (la rejilla de cotas de berma de la 013 es
la del diseño, no sabe de las rampas)."""


@dataclass(frozen=True, slots=True)
class BankRamp:
    """Una rampa grabada: el rectángulo local donde la superficie es su rasante, que es lineal en ``x`` de
    ``z_start_m`` en ``x_start_m`` a ``z_end_m`` en ``x_end_m``."""

    name: str
    x_start_m: float
    x_end_m: float
    y_start_m: float
    y_end_m: float
    z_start_m: float
    z_end_m: float


BANK_RAMPS: tuple[BankRamp, ...] = (
    BankRamp("Rampa 1", 60.0, 100.0, 32.0, 54.0, 140.0, 135.0),
    BankRamp("Rampa 2", 60.0, 140.0, 58.0, 84.0, 125.0, 135.0),
    BankRamp("Rampa 3", 60.0, 140.0, 88.0, 114.0, 125.0, 115.0),
)
"""Las tres rampas del 12,5 % (12,5 m por cada 100 m): la 1, de 140 a 135 m (hacia el este, 40 m) sobre la primera cara;
la 2, de 135 m (en x = 140) a 125 m (en x = 60) sobre la segunda, y la 3, de 125 a 115 m (hacia el este, 80 m) sobre la
tercera. Cada una cubre, además de su cara, 8 m de la berma de cada lado, así que sus extremos quedan a ras de las
bermas (a < 1 celda); no hay rampa sobre la cuarta cara: la berma de 105 m queda sin comunicar."""
BANK_ENTRY: tuple[float, float] = (10.0, 20.0)
"""La entrada (local): el terreno llano de 140 m, al sur de la primera cara y al oeste de las rampas."""
BANK_PLATFORM_BOX: tuple[float, float, float, float] = (10.0, 80.0, 50.0, 92.0)
"""La plataforma de la 015 (local), de 480 m², en la berma de 125 m, al oeste de las rampas (donde llegan la 2 y la 3)."""
BANK_PLATFORM_Z_M = 125.0
"""La cota a que se llega en ella."""
BANK_ZONE_BOXES: Mapping[str, tuple[float, float, float, float]] = {
    "Zona sin acceso": (160.0, 140.0, 220.0, 152.0),
    "Zona con acceso": (160.0, 52.0, 200.0, 62.0),
}
"""Las dos zonas «requiere acceso» (local): la primera, de 720 m² en la berma de 105 m (14 m al norte de la de 115 m, con
10 m de diferencia de cota), no se comunica; la segunda, de 400 m² en la de 135 m, al este de las rampas, sí."""
BANK_ZONE_LEVEL_GAP_M = 10.0
"""La diferencia de cota de la zona sin acceso con lo alcanzable más próximo (la berma de 115 m): 115 − 105."""
BANK_COMMUNICATED: tuple[float, ...] = (135.0, 125.0, 115.0)
BANK_NOT_COMMUNICATED: tuple[float, ...] = (105.0,)
BANK_Z_MIN_M = 115.0
BANK_Z_MAX_M = 140.0
"""Lo que sale, a mano: tres bermas comunicadas (135, 125 y 115 m) y una no (105 m); cotas mínima y máxima alcanzables de 115
y 140 m (la máxima, el terreno de la entrada)."""


def bank_surface(grid: Any = GRID) -> np.ndarray:
    """La superficie de la cantera con bancos en los centros de ``grid`` (m): el perfil en ``y`` de
    :data:`BANK_PROFILE_Z` con las tres rampas grabadas (:data:`BANK_RAMPS`)."""
    x, y = local_centers(grid)
    found = np.interp(y, BANK_PROFILE_Y, BANK_PROFILE_Z)
    for ramp in BANK_RAMPS:
        inside = in_box((ramp.x_start_m, ramp.y_start_m, ramp.x_end_m, ramp.y_end_m), grid)
        grade = np.interp(x, (ramp.x_start_m, ramp.x_end_m), (ramp.z_start_m, ramp.z_end_m))
        found = np.where(inside, grade, found)
    return found


def bank_berms(grid: Any = GRID) -> np.ndarray:
    """La rejilla de cotas de berma de la cantera (la de la 013): la cota de cada berma en sus celdas y ``nan`` en las
    demás."""
    found = np.full(grid.shape, np.nan)
    for level, (low, high) in zip(BANK_LEVELS, BANK_BERM_RANGES, strict=True):
        found[in_box((0.0, low, SIDE_M, high), grid)] = level
    return found


def bank_platform_mask(grid: Any = GRID) -> np.ndarray:
    """La huella de la plataforma de la berma de 125 m."""
    return in_box(BANK_PLATFORM_BOX, grid)


def bank_zone_mask(name: str, grid: Any = GRID) -> np.ndarray:
    """La zona «requiere acceso» ``name`` (de :data:`BANK_ZONE_BOXES`) como máscara de ``grid``."""
    return in_box(BANK_ZONE_BOXES[name], grid)


def bank_zone_constraints() -> tuple[Any, ...]:
    """Las dos zonas como restricciones «requiere acceso» de la 012 (``core.constraints.model.Constraint``, de uid
    ficticio y ``fid`` 0: nuevas), con los códigos ``zona_sin_acceso`` y ``zona_con_acceso``. **No** están en el
    proyecto."""
    cmodel = import_geoblender("core.constraints.model")
    kinds, types = cmodel.GeometryKind, cmodel.ConstraintType
    return tuple(qfx._constraint(name.lower().replace(" ", "_"), name, types.REQUIRES_ACCESS, kinds.POLYGON,
                                 ((cfx.rectangle(*box),),))
                 for name, box in BANK_ZONE_BOXES.items())


# --- Las capas del proyecto (plan §5.2.1) ------------------------------------------------------------------------

POINTS_LAYER = "gis_fea_pistas_puntos"
AXES_LAYER = "gis_fea_pistas_ejes"
ZONES_LAYER = "gis_fea_pistas_zonas"
PLATFORMS_LAYER = "gis_fea_pistas_plataformas"
ENTRIES_LAYER = "gis_fea_pistas_entradas"
LAYERS: tuple[str, ...] = (POINTS_LAYER, AXES_LAYER, ZONES_LAYER, PLATFORMS_LAYER, ENTRIES_LAYER)
"""Las cinco capas de entidades (en el orden en que se escriben): los puntos de origen y destino (``nombre``), los ejes en
planta (con defectos), las zonas de la cota de destino (``nombre`` y ``cota``), los ejes de plataformas de la 015
(``ancho``, ``cota_inicial`` y ``pendiente``) y los puntos de entrada de la accesibilidad."""
BREAKLINES_LAYER = "gis_brk_pistas_eje3d"
"""La tabla de líneas de rotura con las dos líneas con Z (la única capa que guarda la Z)."""
BRANCH_ORIGIN_ABSCISSA_M = 100.0
"""La abscisa del eje de la pista de la rampa de la que sale el ramal (``RDW-001@100``): el punto (200, 200)."""
BRANCH_DESTINATION: tuple[float, float] = (200.0, 260.0)
"""El destino del ramal (local): 60 m al norte de su origen, a cota constante sobre el plano del 4 %."""

POINTS: tuple[tuple[str, tuple[float, float]], ...] = (
    ("Origen rampa", RAMP_ORIGIN), ("Destino rampa", RAMP_DESTINATION),
    ("Origen ladera", HILL_ORIGIN), ("Destino ladera", HILL_DESTINATION),
    ("Origen franja", STRIP_ORIGIN), ("Destino franja", STRIP_DESTINATION),
    ("Origen barranco", RAVINE_ORIGIN), ("Destino barranco", RAVINE_DESTINATION),
    ("Origen tajo", PIT_ORIGIN), ("Destino tajo", PIT_DESTINATION),
    ("Punto en P1", (305.0, 200.0)), ("Destino del ramal", BRANCH_DESTINATION),
    ("Punto fuera de la rejilla", (-20.0, 200.0)),
)
"""Los puntos de origen y destino de los casos (local): dentro de su terreno, salvo el último, que está fuera de la
rejilla a propósito (RF-017-04); «Punto en P1» cae en la huella de la plataforma P1."""
AXES: tuple[tuple[str, tuple[tuple[tuple[float, float], ...], ...]], ...] = (
    ("Eje de 200 m", (STEP_AXIS,)),
    ("Esquina de 40 m", (CORNER_LONG,)),
    ("Esquina de 15 m", (CORNER_SHORT,)),
    ("Eje corto", (SHORT_AXIS,)),
    ("Eje que se corta", (((200.0, 330.0), (260.0, 390.0), (260.0, 330.0), (200.0, 390.0)),)),
    ("Eje de longitud cero", (((50.0, 380.0), (50.0, 380.0)),)),
    ("Eje de dos partes", (((60.0, 340.0), (100.0, 340.0)), ((120.0, 340.0), (160.0, 340.0)))),
    ("Eje con vértice repetido", (((60.0, 360.0), (100.0, 360.0), (100.0, 360.0), (140.0, 360.0)),)),
)
"""Los ejes en planta (local, sin Z): los cuatro primeros son válidos (el eje de 200 m de la rampa y del escalón, las
dos esquinas y el eje corto) y los cuatro últimos tienen los defectos de RF-017-04 (se corta a sí mismo, sin longitud,
de dos partes y con un vértice repetido)."""
ZONES: tuple[tuple[str, tuple[float, float, float, float], float], ...] = (
    ("Zona del fondo", (80.0, 140.0, 120.0, 180.0), PIT_FLOOR_M),
    ("Zona de la berma 115", (200.0, 108.0, 260.0, 124.0), 115.0),
)
"""Las zonas de la cota de destino (local, con su ``cota``): el fondo del tajo (125 m) y la berma de 115 m de la cantera
con bancos (la rampa a una cota, E4)."""
PLATFORMS: tuple[tuple[str, tuple[tuple[float, float], ...], float, float, float], ...] = (
    ("P1", ((300.0, 200.0), (340.0, 200.0)), 30.0, 112.0, 0.0),
    ("Relleno sobre la calzada", ((240.0, 190.0), (240.0, 210.0)), 20.0, 111.0, 0.0),
    ("Plataforma de la berma 125", ((10.0, 86.0), (50.0, 86.0)), 12.0, 125.0, 0.0),
)
"""Los ejes de plataformas (local; nombre, camino, ancho, cota inicial y pendiente): P1 (la de la cadena P1 → pista →
ramal, a 112 m sobre el plano del 4 %), la que se rellena después sobre la calzada de la pista (111 m: 1,4 m sobre su
rasante en x = 240) y la de la berma de 125 m de la cantera con bancos."""
ENTRIES: tuple[tuple[str, tuple[float, float]], ...] = (
    ("Entrada de la cantera de bancos", BANK_ENTRY), ("Entrada del tajo", PIT_ENTRY))
"""Los puntos de entrada de la accesibilidad (local)."""


def platform_footprint_box(name: str) -> tuple[float, float, float, float]:
    """La huella (caja local) de la plataforma ``name`` de :data:`PLATFORMS`, de eje paralelo a un eje de la rejilla: el
    eje con extremos planos y medio ancho a cada lado."""
    for found, path, width, _level, _grade in PLATFORMS:
        if found == name:
            (x0, y0), (x1, y1) = path[0], path[-1]
            half = width / 2.0
            if y0 == y1:
                return (min(x0, x1), y0 - half, max(x0, x1), y0 + half)
            return (x0 - half, min(y0, y1), x0 + half, max(y0, y1))
    raise KeyError(name)


def layers() -> tuple[Any, ...]:
    """Las cinco capas de entidades (arrays nuevos, absolutos), en el orden de :data:`LAYERS`, como
    ``stockpile_data.FieldsLayer``."""
    def one(path: Sequence[Sequence[float]]) -> np.ndarray:
        return absolute(path)

    return (
        sdata.FieldsLayer(POINTS_LAYER, "point", tuple(((one([point]),),) for _name, point in POINTS),
                          tuple(name for name, _point in POINTS), {}),
        sdata.FieldsLayer(AXES_LAYER, "line", tuple(tuple((one(part),) for part in parts) for _name, parts in AXES),
                          tuple(name for name, _parts in AXES), {}),
        sdata.FieldsLayer(ZONES_LAYER, "polygon", tuple(((_rectangle(box),),) for _name, box, _cota in ZONES),
                          tuple(name for name, _box, _cota in ZONES), {"cota": tuple(cota for *_x, cota in ZONES)}),
        sdata.FieldsLayer(PLATFORMS_LAYER, "line", tuple(((one(path),),) for _name, path, *_rest in PLATFORMS),
                          tuple(name for name, *_rest in PLATFORMS),
                          {"ancho": tuple(item[2] for item in PLATFORMS),
                           "cota_inicial": tuple(item[3] for item in PLATFORMS),
                           "pendiente": tuple(item[4] for item in PLATFORMS)}),
        sdata.FieldsLayer(ENTRIES_LAYER, "point", tuple(((one([point]),),) for _name, point in ENTRIES),
                          tuple(name for name, _point in ENTRIES), {}),
    )


def _rectangle(box: tuple[float, float, float, float]) -> np.ndarray:
    return cfx.rectangle(*box)


def breaklines() -> list[np.ndarray]:
    """Las dos líneas con Z de :data:`BREAKLINES_LAYER` (``(n, 3)`` absolutas): la irregular y la lisa."""
    return [axis_3d_irregular(), axis_3d_smooth()]


# --- Los oráculos propios -----------------------------------------------------------------------------------------


def oracle_slope_pct(values: np.ndarray, step_m: float) -> np.ndarray:
    """La pendiente local (%) de cada celda: la mayor tangente a sus ocho vecinas (las diagonales, a ``h·√2``), a mano
    con desplazamientos de numpy; un vecino sin dato (``nan``) o fuera de la rejilla no cuenta."""
    z = np.asarray(values, dtype=np.float64)
    rows, columns = z.shape
    best = np.zeros_like(z)
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            if di == 0 and dj == 0:
                continue
            i0, i1 = max(0, -di), rows - max(0, di)
            j0, j1 = max(0, -dj), columns - max(0, dj)
            tangent = np.abs(z[i0:i1, j0:j1] - z[i0 + di:i1 + di, j0 + dj:j1 + dj]) / (step_m * math.hypot(di, dj))
            best[i0:i1, j0:j1] = np.fmax(best[i0:i1, j0:j1], tangent)
    return best * 100.0


def oracle_reachable(mask: np.ndarray, seeds: Sequence[tuple[int, int]]) -> np.ndarray:
    """Las celdas de ``mask`` 4-conexas con alguna semilla ``(fila, columna)`` que esté en ella (una búsqueda en
    anchura con una cola, sin numpy)."""
    allowed = np.asarray(mask, dtype=bool)
    rows, columns = allowed.shape
    flat = allowed.ravel().tolist()
    seen = bytearray(rows * columns)
    queue: deque[int] = deque()
    for row, column in seeds:
        index = row * columns + column
        if flat[index] and not seen[index]:
            seen[index] = 1
            queue.append(index)
    while queue:
        index = queue.popleft()
        row, column = divmod(index, columns)
        for near_row, near_column in ((row - 1, column), (row + 1, column), (row, column - 1), (row, column + 1)):
            if 0 <= near_row < rows and 0 <= near_column < columns:
                near = near_row * columns + near_column
                if flat[near] and not seen[near]:
                    seen[near] = 1
                    queue.append(near)
    return np.frombuffer(bytes(seen), dtype=np.uint8).reshape(rows, columns).astype(bool)


def erode(mask: np.ndarray, steps: int) -> np.ndarray:
    """``mask`` erosionada ``steps`` veces con la cruz de las cuatro vecinas (lo que hace de «ancho mínimo»): una celda
    queda si ella y sus cuatro vecinas están en la máscara; el borde de la rejilla cuenta como fuera."""
    found = np.asarray(mask, dtype=bool).copy()
    for _ in range(steps):
        padded = np.pad(found, 1, constant_values=False)
        found = found & padded[:-2, 1:-1] & padded[2:, 1:-1] & padded[1:-1, :-2] & padded[1:-1, 2:]
    return found


def dilate(mask: np.ndarray, steps: int) -> np.ndarray:
    """``mask`` dilatada ``steps`` veces con la cruz de las cuatro vecinas."""
    found = np.asarray(mask, dtype=bool).copy()
    for _ in range(steps):
        padded = np.pad(found, 1, constant_values=False)
        found = found | padded[:-2, 1:-1] | padded[2:, 1:-1] | padded[1:-1, :-2] | padded[1:-1, 2:]
    return found


def opening(mask: np.ndarray, steps: int) -> np.ndarray:
    """La apertura de ``mask`` con la cruz (:func:`erode` y luego :func:`dilate`, ``steps`` veces): lo que la
    «apertura con un disco» de A10 hace con el ancho mínimo, en pequeño; quita lo más fino que ``2·steps + 1``
    celdas."""
    return dilate(erode(mask, steps), steps)


# --- El proyecto -----------------------------------------------------------------------------------------------

RASTERS: Mapping[str, Callable[[Any], np.ndarray]] = {
    "rampa": ramp_terrain,
    "rampa_lateral": lambda grid: ramp_terrain(grid, cross_pct=RAMP_CROSS_PCT),
    "escalon": step_terrain,
    "ladera38": hillside_terrain,
    "franja": strip_terrain,
    "barranco": ravine_terrain,
    "banco": bank_surface,
    "tajo": pit_exploitation,
    "tajo_final": pit_final,
    "tajo_relleno": pit_after_fill,
}
"""Los terrenos que se escriben en el proyecto como rejillas (nombre de la orden → su función de la rejilla)."""
BUILD_BUDGET_S = 2.0
"""Lo que añade la plantilla a la cantera de la 015 (copiarla y escribir diez rejillas, cinco capas y las líneas con Z)
se construye en ≤ 2 s de CPU (tarea T01)."""
_TEMPLATES: dict[float, dict[str, Any]] = {}


def dataset_of(label: str) -> str:
    """El dato del proyecto de la rejilla ``label`` de :data:`RASTERS` (``gis_dtm_<label>``)."""
    return f"gis_dtm_{label}"


def _open(folder: Path, made: Mapping[str, Any], clock: FakeClock) -> Any:
    open_mod = import_geoblender("core.project.open")
    userdata = import_geoblender("core.userdata")
    return open_mod.open_project(folder / "proyectos" / made["name"], cp.SESSION, userdata.UserData(folder / "u"),
                                 clock=clock, pid_alive=FakePids({cp.SESSION.pid})).project


def _build(folder: Path, base: Mapping[str, Any], step_m: float) -> dict[str, Any]:
    """Copia el proyecto de la 015 ``base`` en ``folder``, le escribe las rejillas, las capas y las líneas con Z y lo
    cierra."""
    from tests.support.res_fixtures import write_grids

    started = time.process_time()
    shutil.copytree(base["folder"] / "proyectos", folder / "proyectos")
    clock = FakeClock(base["now"])
    project = _open(folder, base, clock)
    try:
        grid = qfx.grid_of(step_m)
        clock.advance(minutes=1)
        write_grids(project, [(label, raster_of(make(grid), grid)) for label, make in RASTERS.items()],
                    message="Terrenos de las pistas")
        for layer in layers():
            sdata.write_layer(project, clock, layer)
        sdata.write_breaklines(project, clock, BREAKLINES_LAYER, breaklines())
        clock.advance(minutes=1)
        return {"folder": folder, "name": base["name"], "now": clock.now(), "versions": base["versions"],
                "build_s": time.process_time() - started}
    finally:
        project.close()


def project_template(step_m: float = COARSE_STEP_M) -> Mapping[str, Any]:
    """El proyecto de la cantera de la 015 con la 017 (véase el módulo) con la rejilla de ``step_m`` m (por defecto la
    gruesa de 2 m), creado y cerrado la primera vez que se pide en el proceso con ese paso, en una carpeta temporal que
    se borra al salir: ``folder``, ``name`` de la carpeta del proyecto, ``now`` del reloj al terminar, los uid de
    ``versions`` (V01 y V02) y ``build_s``, la CPU que gastó **añadir lo de la 017** a la cantera de la 015 (s). No se
    modifica."""
    found = _TEMPLATES.get(step_m)
    if found is None:
        base = efx.project_template(step_m)  # antes del registro: construye la suya con el suyo
        folder = Path(tempfile.mkdtemp(prefix="gb-rt-"))
        atexit.register(shutil.rmtree, folder, ignore_errors=True)
        with cp.constraints_registered():
            found = _TEMPLATES[step_m] = _build(folder, base, step_m)
    return found


@contextmanager
def open_road_project(prefix: str = "gb-rp-", step_m: float = COARSE_STEP_M) -> Iterator[tuple[Any, FakeClock]]:
    """Una copia propia del proyecto de :func:`project_template` abierta en escritura: ``(project, clock)``. Al salir se
    cierra y se borra. Hace falta ``constraints_project.constraints_registered()`` activo (lo está en una
    :class:`RoadProjectCase`)."""
    made = project_template(step_m)
    with project_tmp(prefix) as folder:
        shutil.copytree(made["folder"] / "proyectos", folder / "proyectos")
        clock = FakeClock(made["now"])
        project = _open(folder, made, clock)
        try:
            yield project, clock
        finally:
            project.close()


class RoadProjectCase(qfx.QuarryProjectCase):
    """Una copia **por clase** del proyecto de :func:`project_template`, abierta en escritura: lo de
    :class:`~tests.support.quarry_fixtures.QuarryProjectCase` (``cls.project``, ``cls.root``, ``cls.clock``,
    ``cls.v1``, ``cls.v2``, ``cls.grid``, ``masks``, ``read_layer``, ``stale_causes``, ``recompute_plan``…), en la
    rejilla gruesa de 2 m salvo que la clase ponga otro ``STEP_M``, con los diez terrenos de :data:`RASTERS`
    (``dataset_of``), las cinco capas de :data:`LAYERS` y la tabla :data:`BREAKLINES_LAYER`. Para partir de una
    instantánea del estado en que la deja una clase, ``entity_fixtures.open_copy_of``."""

    STEP_M: ClassVar[float] = COARSE_STEP_M

    @classmethod
    def setUpClass(cls) -> None:
        versions_read = import_geoblender("core.versions.read")
        cls.grid = qfx.grid_of(cls.STEP_M)
        made = project_template(cls.STEP_M)
        cls.enterClassContext(cp.constraints_registered())
        cls.project, cls.clock = cls.enterClassContext(open_road_project("gb-rc-", cls.STEP_M))
        cls.root = Path(cls.project.root)
        with cls.project.read() as conn:
            cls.v1, cls.v2 = (versions_read.version(conn, uid) for uid in made["versions"])


# --- La escala (plan §7.3; T34): bajo demanda -------------------------------------------------------------------

SCALE_ROADS = 20
SCALE_ROAD_VERTICES = 5_000
"""Veinte pistas de 5.000 vértices para la vista previa de RNF-017-08."""
SCALE_ROUTE_M = 1_500.0
"""La ruta de RNF-017-01 y 02."""


def scale_grid() -> Any:
    """La rejilla de escala: 1.654 × 1.699 celdas de 1 m (2,81 M), la de la 013 (otra esquina que :data:`BASE`: usa
    :func:`origin_of`)."""
    return sdata.scale_grid()


@dataclass(frozen=True, slots=True)
class ScaleRavine:
    """La ruta de escala con el barranco a medio camino: el origen y el destino (locales de la rejilla de escala) y la
    x del eje del barranco."""

    origin: tuple[float, float]
    destination: tuple[float, float]
    axis_x: float


def scale_ravine_spec() -> ScaleRavine:
    """Una ruta de 1.500 m de oeste a este por la mitad de la rejilla de escala, con el barranco de 14 m en su punto
    medio (x = 827)."""
    return ScaleRavine((77.0, 850.0), (77.0 + SCALE_ROUTE_M, 850.0), 77.0 + SCALE_ROUTE_M / 2.0)


def scale_ravine_terrain() -> np.ndarray:
    """El terreno de escala con el barranco (2,81 M celdas, ≈ 22 MB, ≈ 0,05 s): **bajo demanda**, no en ``check.py``."""
    return ravine_terrain(scale_grid(), axis_x=scale_ravine_spec().axis_x)


def _zigzag(vertices: int, length_m: float, mean_heading_deg: float, start: tuple[float, float]) -> np.ndarray:
    """Una poligonal de ``vertices`` vértices y ``length_m`` m cuyos tramos, iguales, alternan el rumbo
    ``± 10°`` alrededor de ``mean_heading_deg`` (giran 20° en cada vértice interior), absoluta, ``(k, 2)``, desde
    el punto local ``start`` de la rejilla de escala."""
    legs = vertices - 1
    leg = length_m / legs
    headings = np.radians(mean_heading_deg + np.where(np.arange(legs) % 2 == 0, 10.0, -10.0))
    steps = np.column_stack([leg * np.sin(headings), leg * np.cos(headings)])
    local = np.vstack([[start], start + np.cumsum(steps, axis=0)])
    return absolute(local, scale_grid())


def scale_axis_2km() -> np.ndarray:
    """El eje de 2.035 m con 61 curvas (63 vértices; RNF-017-04), en diagonal dentro de la rejilla de escala."""
    return _zigzag(63, 2_035.0, 45.0, (100.0, 100.0))


def scale_axis_5km() -> np.ndarray:
    """El eje de 5.013 m con 163 vértices (161 curvas; RNF-017-03): no cabe en la rejilla de escala (mide 1,65 km); es
    solo para el eje y la rasante."""
    return _zigzag(163, 5_013.0, 90.0, (100.0, 800.0))


def scale_preview_lines() -> np.ndarray:
    """Veinte pistas de 5.000 vértices ``(x, y, z)`` absolutos para la vista previa (RNF-017-08), float64 con forma
    ``(20, 5000, 3)``: ondas de 1,5 km separadas 70 m en la rejilla de escala."""
    t = np.arange(SCALE_ROAD_VERTICES) / (SCALE_ROAD_VERTICES - 1.0)
    lines = np.empty((SCALE_ROADS, SCALE_ROAD_VERTICES, 3))
    for index in range(SCALE_ROADS):
        local_x = 100.0 + 1_500.0 * t
        local_y = 100.0 + 70.0 * index + 20.0 * np.sin(2.0 * np.pi * 6.0 * t)
        lines[index, :, :2] = absolute(np.column_stack([local_x, local_y]), scale_grid())
        lines[index, :, 2] = 150.0 + 40.0 * t
    return lines


def scale_berm_boxes() -> tuple[tuple[float, float, float, float], ...]:
    """250 tramos de berma de 40 × 16 m (640 m²) en 25 columnas y 10 filas de la rejilla de escala (cajas locales
    disjuntas)."""
    return tuple((60.0 + 60.0 * column, 60.0 + 150.0 * row, 100.0 + 60.0 * column, 76.0 + 150.0 * row)
                 for row in range(10) for column in range(25))


def scale_platform_boxes() -> tuple[tuple[float, float, float, float], ...]:
    """5 plataformas, cada una dentro de un tramo de berma distinto (cajas locales)."""
    return tuple(_inside(scale_berm_boxes()[index]) for index in (0, 60, 120, 180, 240))


def scale_zone_boxes() -> tuple[tuple[float, float, float, float], ...]:
    """20 zonas «requiere acceso», cada una dentro de un tramo de berma distinto del de las plataformas (cajas
    locales)."""
    return tuple(_inside(scale_berm_boxes()[10 + 12 * index]) for index in range(20))


def _inside(box: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    return (box[0] + 4.0, box[1] + 2.0, box[2] - 4.0, box[3] - 2.0)
