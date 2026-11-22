# SPDX-License-Identifier: GPL-3.0-or-later
"""Los terrenos y las cortas de prueba de la corta por bancos (spec 018, T01; plan 018 §5.1, §7.1, §7.3 y §7.4;
CE-018-01 a 08; E1 a E5).

Todo es sintético (ningún dato de cliente), en coordenadas **locales** (m desde la esquina suroeste de la rejilla; ``x``
al este, ``y`` al norte; la fila 0 de una rejilla es el norte) y float64; ``absolute`` de ``tests.support.road_data``
las pasa a absolutas (EPSG:25830 + EPSG:5782) desde la esquina de la cantera. Se apoya, sin tocarlos, en
``design_fixtures`` (los perfiles de banco de la 013), ``quarry_fixtures`` (la rejilla y el proyecto de la cantera),
``entity_fixtures`` (el proyecto de la 015) y ``road_data`` (las ayudas de rejilla de la 017). Cada función que da un
array da uno **nuevo**. Las cuentas de la docstring de cada constante están hechas a mano; las comprueba
``tests/unit/design/test_pit_fixtures.py`` otra vez, de otra manera.

- **Los perfiles** (:data:`EXPL`, :data:`DESD`): ``EXPL_10_60_6`` (h = 10 m, α = 60°, B = 6 m: avance 11,77 m) y
  ``DESD_10_45_6`` (h = 10 m, α = 45°, B = 6 m: avance 16,00 m), valores de prueba de la 013, con el ancla en la cota
  de fondo (125 m en la 013; aquí :data:`FLOOR_Z_M` y :data:`LIMIT_TERRAIN_Z_M`, para que los bancos de CE-018-03 y 04
  caigan en cotas redondas). **Ninguno es un valor por defecto del producto.**
- **La roseta de CE-018-02** (:data:`ROSE_TWO_RANGES`, :func:`rose_distance_by_hand`): dos rangos de azimut de la cara,
  [0°, 180°) con α = 60° y [180°, 360°) con α = 45°, con h = 10 m y B = 6 m: la cresta queda a 5,7735 m del pie
  donde la cara tiene azimut 90° y a 10,0000 m donde tiene azimut 270° (el azimut de la cara es hacia donde baja).
- **Los terrenos** (:func:`flat_terrain`, :func:`inclined_terrain`, :func:`limit_terrain`; :data:`RASTERS`): llano a
  175 m (cinco bancos de 10 m sobre un fondo a 125 m: CE-018-03), inclinado un 10 % hacia el este (CE-018-07; 130 m en
  x = 0 y 150 m en x = 200, el centro de la corta) y llano a 100 m (CE-018-04).
- **Las cortas** (:func:`circle_ring`, :func:`square_ring`, :func:`rect_ring`): el **fondo circular de 50 m** con 720
  vértices (CE-018-02, 03, 05 y 07), el **cuadrado de 100 m** (CE-018-01), el **límite cuadrado de 200 m** (CE-018-04) y
  la **corta rectangular de 200 × 60 m** del zig-zag (CE-018-06), todos centrados en :data:`CENTER` (200, 200).
- **Las cuentas a mano**: el volumen analítico del círculo (:func:`circle_radii_by_hand`,
  :func:`circle_volume_by_hand`: 961.661,6 m³ con cinco troncos de cono; CE-018-03) y su superficie analítica
  (:func:`circle_surface`), el área de la cresta del cuadrado (:func:`square_crest_area_by_hand`: 12.414,12 m²
  redondeada y ``L² + 4·L·d + 4·d²`` con inglete; CE-018-01), los bancos del límite (:func:`limit_benches_by_hand`:
  lados 180, 148, 116, 84 y 52 m; CE-018-04) y la longitud de eje que pide cada banco (:func:`ramp_run_by_hand`: 125 m
  con g = 8 %, 100 m con g = 10 %; CE-018-05 y 06).
- **La polilínea rugosa** (:func:`rough_ring`, :func:`rough_case`): una curva en estrella respecto del centro (simple por
  construcción) con un ruido radial de 0 a 0,8 m y semillas fijas, para la batería de 300 casos de la T09.
- **La escala** (:func:`scale_grid`, :func:`scale_rings`; plan §7.3, para la T36): la rejilla de 1.654 × 1.699 celdas
  (2,81 M) y cortas de 40 y de 60 bancos con ≈ 160.000 vértices. **Solo bajo demanda**: no se construyen en ``check.py``.
- **El proyecto** (:func:`project_template`, :class:`PitProjectCase`): el de la cantera de la 015 con los tres terrenos
  como rejillas (:data:`RASTERS`). Se crea **una vez por proceso** y paso de rejilla (en ≤ 2 s de CPU: :data:`BUILD_BUDGET_S`)
  y cada clase trabaja en su copia. Las capas de la corta (fondos, límites, sectores, zonas) las añaden las tareas
  que las leen (T21).

**HIPÓTESIS** (decisión de la sesión principal T01-a; ninguna es valor por defecto del producto): las tolerancias de arco,
de simplificación y la ventana de azimut no tienen valor de referencia en la spec (D-14, D-15, P-5); las pruebas usan
:data:`HYPOTHESES` (arco de 1 mm en las cifras a mano y de 5 cm en las demás, simplificación de 0,05 m, ventana de 12 m).
"""

from __future__ import annotations

import atexit
import math
import shutil
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from tests.support import constraints_project as cp
from tests.support import design_fixtures as dfx
from tests.support import entity_fixtures as efx
from tests.support import quarry_fixtures as qfx
from tests.support import road_data as rd
from tests.support import stockpile_data as sdata
from tests.support.core_fixtures import FakeClock, FakePids, project_tmp
from tests.support.package import import_geoblender

CRS = rd.CRS
VERTICAL = rd.VERTICAL
BASE = rd.BASE
GRID = rd.GRID
STEP_M = rd.STEP_M
COARSE_STEP_M = rd.COARSE_STEP_M
grid_of = rd.grid_of
local_centers = rd.local_centers
raster_of = rd.raster_of
absolute = rd.absolute
origin_of = rd.origin_of

# --- Hipótesis (T01-a) ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Hypotheses:
    """Los valores de prueba de lo que la spec no fija (D-14, D-15, P-5): ``arc_hand_m`` (arco de las cifras a mano),
    ``arc_m`` (arco de las demás), ``simplify_m`` (la simplificación de inv. 07 §3.4) y ``az_window_m`` (la ventana de
    suavizado del azimut de la cara). **HIPÓTESIS**: ninguno pasa a valor por defecto."""

    arc_hand_m: float
    arc_m: float
    simplify_m: float
    az_window_m: float


HYPOTHESES = Hypotheses(arc_hand_m=0.001, arc_m=0.05, simplify_m=0.05, az_window_m=12.0)
HYPOTHESIS_NAMES: tuple[str, ...] = ("arc_hand_m", "arc_m", "simplify_m", "az_window_m")
"""Los campos de :class:`Hypotheses`, todos HIPÓTESIS."""

# --- Los perfiles y la roseta --------------------------------------------------------------------------------

CENTER: tuple[float, float] = (200.0, 200.0)
"""El centro (local, m) de todas las cortas: el de la rejilla de la cantera de 400 × 400 m."""
FLOOR_Z_M = 125.0
"""La cota del fondo de la corta ascendente (m): el ancla de :data:`EXPL`."""
TOP_Z_M = 175.0
"""El terreno llano de CE-018-03: cinco bancos de 10 m sobre el fondo."""
BENCHES = 5
"""Los bancos de CE-018-03."""
LIMIT_TERRAIN_Z_M = 100.0
"""El terreno llano de CE-018-04 (m); el ancla de :data:`DESD`."""
LIMIT_FLOOR_Z_M = 50.0
"""El fondo de CE-018-04 sin cota de fondo pedida (5 bancos de 10 m)."""
LIMIT_BOTTOM_Z_M = 70.0
"""La cota de fondo de CE-018-04 con la que se detiene a los 3 bancos."""
MIN_FLOOR_WIDTH_M = 30.0
"""El ancho mínimo de fondo de CE-018-04 (m): valor de prueba."""
INCLINED_PCT = 10.0
"""La inclinación del terreno de CE-018-07 (%): sube hacia el este."""
INCLINED_Z_AT_X0_M = 130.0
"""La cota del terreno inclinado en x = 0 (m): 150 m en x = 200, el centro de la corta."""

EXPL = replace(dfx.EXPL_10_60_6, anchor_m=FLOOR_Z_M)
"""``EXPL_10_60_6`` (h = 10, α = 60°, B = 6: avance 11,7735 m) con el ancla en el fondo de la corta ascendente."""
DESD = replace(dfx.DESD_10_45_6, anchor_m=LIMIT_TERRAIN_Z_M)
"""``DESD_10_45_6`` (h = 10, α = 45°, B = 6: avance 16 m) con el ancla en el terreno del límite."""


@dataclass(frozen=True, slots=True)
class RoseRangeData:
    """Un rango de azimut de la cara ``[from_deg, to_deg)`` con su inclinación de cara ``face_deg`` y su berma
    ``berm_m`` (m)."""

    from_deg: float
    to_deg: float
    face_deg: float
    berm_m: float


ROSE_TWO_RANGES: tuple[RoseRangeData, ...] = (RoseRangeData(0.0, 180.0, 60.0, 6.0), RoseRangeData(180.0, 360.0, 45.0, 6.0))
"""La roseta de CE-018-02 (valores de prueba)."""


def rose_distance_by_hand(rose: Sequence[RoseRangeData], azimuth_deg: float, height_m: float = 10.0) -> float:
    """La distancia horizontal de la cara ``h / tan α`` del rango que contiene ``azimuth_deg`` (módulo 360):
    5,7735 m en 90° y 10,0000 m en 270° con :data:`ROSE_TWO_RANGES` y h = 10 m (CE-018-02)."""
    azimuth = azimuth_deg % 360.0
    for item in rose:
        if item.from_deg <= azimuth < item.to_deg:
            return height_m / math.tan(math.radians(item.face_deg))
    raise ValueError(f"el azimut {azimuth_deg} no está en ningún rango")


# --- Los terrenos --------------------------------------------------------------------------------------------


def flat_terrain(grid: Any = GRID, z_m: float = TOP_Z_M) -> np.ndarray:
    """Un terreno llano a ``z_m`` m (por defecto :data:`TOP_Z_M`, el de CE-018-03)."""
    return np.full(grid.shape, z_m, dtype=np.float64)


def inclined_terrain(grid: Any = GRID, pct: float = INCLINED_PCT, z_at_x0_m: float = INCLINED_Z_AT_X0_M) -> np.ndarray:
    """El terreno plano inclinado ``pct`` % hacia el este (CE-018-07): ``z = z_at_x0 + pct/100 · x`` con ``x`` local."""
    x, _y = local_centers(grid)
    return z_at_x0_m + pct / 100.0 * x


def limit_terrain(grid: Any = GRID) -> np.ndarray:
    """El terreno llano a 100 m del límite de CE-018-04."""
    return flat_terrain(grid, LIMIT_TERRAIN_Z_M)


# --- Las cortas ----------------------------------------------------------------------------------------------

CIRCLE_RADIUS_M = 50.0
"""El radio del fondo circular (m)."""
CIRCLE_VERTICES = 720
"""Los vértices del fondo circular (uno cada 0,5°)."""
SQUARE_SIDE_M = 100.0
"""El lado del cuadrado de CE-018-01 (m)."""
LIMIT_SIDE_M = 200.0
"""El lado del límite cuadrado de CE-018-04 (m)."""
ZIGZAG_LENGTH_M = 200.0
ZIGZAG_WIDTH_M = 60.0
"""La corta rectangular de CE-018-06 (m): 200 de largo (este-oeste) por 60 de ancho."""


def circle_ring(radius_m: float = CIRCLE_RADIUS_M, vertices: int = CIRCLE_VERTICES,
                center: tuple[float, float] = CENTER) -> np.ndarray:
    """Un anillo circular antihorario de ``vertices`` vértices (sin repetir el primero), local, float64 ``(n, 2)``."""
    angle = 2.0 * math.pi * np.arange(vertices) / vertices
    return np.column_stack([center[0] + radius_m * np.cos(angle), center[1] + radius_m * np.sin(angle)])


def rect_ring(length_m: float, width_m: float, center: tuple[float, float] = CENTER) -> np.ndarray:
    """Un rectángulo antihorario de 4 vértices (desde el suroeste), local, float64 ``(4, 2)``."""
    half_x, half_y = length_m / 2.0, width_m / 2.0
    return np.array([[center[0] - half_x, center[1] - half_y], [center[0] + half_x, center[1] - half_y],
                     [center[0] + half_x, center[1] + half_y], [center[0] - half_x, center[1] + half_y]])


def square_ring(side_m: float, center: tuple[float, float] = CENTER) -> np.ndarray:
    """Un cuadrado antihorario de 4 vértices (desde el suroeste), local, float64 ``(4, 2)``."""
    return rect_ring(side_m, side_m, center)


# --- Las cuentas a mano --------------------------------------------------------------------------------------


def circle_radii_by_hand(profile: Any = EXPL, radius_m: float = CIRCLE_RADIUS_M,
                         benches: int = BENCHES) -> tuple[tuple[float, float], ...]:
    """Los radios ``(pie_k, cresta_k)`` de los ``benches`` bancos de la corta circular: ``cresta = pie + h/tan α`` y
    ``pie_{k+1} = cresta_k + B`` (CE-018-03)."""
    run = profile.height_m / math.tan(math.radians(profile.face_deg))
    found = []
    foot = radius_m
    for _ in range(benches):
        found.append((foot, foot + run))
        foot = foot + run + profile.berm_m
    return tuple(found)


def circle_volume_by_hand(profile: Any = EXPL, radius_m: float = CIRCLE_RADIUS_M, benches: int = BENCHES) -> float:
    """El volumen analítico de la corta circular sobre un terreno llano a la cresta del último banco: la suma de los
    troncos de cono de las caras, ``π·h/3·(r² + r·R + R²)`` (cada rodaja de altura ``h`` tiene por radio el del pie del
    banco y llega al de su cresta: la berma no añade volumen). 961.661,57 m³ con :data:`EXPL` y 5 bancos (CE-018-03)."""
    return math.fsum(math.pi * profile.height_m / 3.0 * (r * r + r * big + big * big)
                     for r, big in circle_radii_by_hand(profile, radius_m, benches))


def circle_surface(grid: Any = GRID, profile: Any = EXPL, radius_m: float = CIRCLE_RADIUS_M, benches: int = BENCHES,
                   terrain_m: float = TOP_Z_M, floor_m: float = FLOOR_Z_M,
                   center: tuple[float, float] = CENTER) -> np.ndarray:
    """La superficie analítica de la corta circular (CE-018-03) muestreada en el centro de cada celda: el fondo a
    ``floor_m``, la cara del banco ``k`` desde su pie hasta su cresta con la tangente de ``α``, la berma a la cota de la
    cresta y, fuera de la última cresta, el terreno ``terrain_m``."""
    x, y = local_centers(grid)
    radius = np.hypot(x - center[0], y - center[1])
    tan_face = math.tan(math.radians(profile.face_deg))
    surface = np.full(grid.shape, terrain_m, dtype=np.float64)
    surface[radius <= radius_m] = floor_m
    for index, (foot, crest) in enumerate(circle_radii_by_hand(profile, radius_m, benches)):
        low = floor_m + index * profile.height_m
        face = (radius > foot) & (radius <= crest)
        surface[face] = low + (radius[face] - foot) * tan_face
        if index + 1 < benches:
            berm = (radius > crest) & (radius <= crest + profile.berm_m)
            surface[berm] = low + profile.height_m
    return np.minimum(surface, terrain_m)


def square_crest_area_by_hand(side_m: float, distance_m: float, *, rounded: bool) -> float:
    """El área de la cresta a ``distance_m`` del pie de un cuadrado de lado ``side_m``: ``L² + 4·L·d + π·d²`` con las
    esquinas redondeadas y ``L² + 4·L·d + 4·d²`` con inglete (CE-018-01: 12.414,12 m² con L = 100 y d = 5,7735)."""
    corner = math.pi if rounded else 4.0
    return side_m * side_m + 4.0 * side_m * distance_m + corner * distance_m * distance_m


@dataclass(frozen=True, slots=True)
class LimitBench:
    """Un banco de la corta descendente: cota y lado de la cresta, cota y lado del pie (m)."""

    number: int
    crest_z_m: float
    crest_side_m: float
    foot_z_m: float
    foot_side_m: float


def limit_benches_by_hand(side_m: float = LIMIT_SIDE_M, profile: Any = DESD, terrain_m: float = LIMIT_TERRAIN_Z_M,
                          min_width_m: float = MIN_FLOOR_WIDTH_M, bottom_m: float | None = None
                          ) -> tuple[tuple[LimitBench, ...], str]:
    """Los bancos del límite cuadrado de CE-018-04 con un bucle: el pie de cada banco queda ``h/tan α`` por dentro de su
    cresta en cada lado (lado − 2·h/tan α) y la cresta siguiente, ``B`` más adentro (lado − 2·B). Se detiene por el
    primero de la cota de fondo ``bottom_m`` y del ancho mínimo (el siguiente pie sería menor que ``min_width_m``).
    Devuelve los bancos y el criterio (``"bottom"`` o ``"min_width"``): con los valores de prueba, 5 bancos con los
    lados de pie 180, 148, 116, 84 y 52 m y ``"min_width"``; con ``bottom_m = 70``, 3 bancos y ``"bottom"``."""
    run = profile.height_m / math.tan(math.radians(profile.face_deg))
    found: list[LimitBench] = []
    crest_side = side_m
    crest_z = terrain_m
    while True:
        foot_z = crest_z - profile.height_m
        foot_side = crest_side - 2.0 * run
        if bottom_m is not None and foot_z < bottom_m - 1e-9:
            return tuple(found), "bottom"
        if foot_side < min_width_m - 1e-9:
            return tuple(found), "min_width"
        found.append(LimitBench(len(found) + 1, crest_z, crest_side, foot_z, foot_side))
        if bottom_m is not None and foot_z <= bottom_m + 1e-9:
            return tuple(found), "bottom"
        crest_side = foot_side - 2.0 * profile.berm_m
        crest_z = foot_z


def ramp_run_by_hand(height_m: float, grade_pct: float) -> float:
    """La longitud de eje que pide subir un banco de ``height_m`` con la pendiente ``grade_pct`` %: ``h / g``: 125 m con
    g = 8 % (la espiral de CE-018-05) y 100 m con g = 10 % (el zig-zag de CE-018-06)."""
    return height_m / (grade_pct / 100.0)


SPIRAL_GRADE_PCT = 8.0
ZIGZAG_GRADE_PCT = 10.0
"""Las pendientes de rampa de CE-018-05 y 06 (valores de prueba)."""

# --- La polilínea rugosa -------------------------------------------------------------------------------------

ROUGH_CASES = 300
"""Los casos de la batería de la T09."""
ROUGH_MAX_NOISE_M = 0.8
"""El ruido radial máximo (m)."""


def rough_ring(seed: int, vertices: int, noise_m: float, radius_m: float = 60.0,
               center: tuple[float, float] = CENTER) -> np.ndarray:
    """Una polilínea cerrada y rugosa, antihoraria, local, float64 ``(vertices, 2)``: un radio de ``radius_m`` m con tres
    armónicos suaves (hasta el 8 % del radio) y un ruido radial uniforme en ``[-noise_m, noise_m]``, todo con la
    semilla ``seed``. Es **simple por construcción**: sus vértices están en orden de ángulo creciente alrededor de
    ``center`` y con radio positivo (una estrella)."""
    rng = np.random.default_rng(seed)
    angle = 2.0 * math.pi * np.arange(vertices) / vertices
    phase = rng.uniform(0.0, 2.0 * math.pi, 3)
    amplitude = 0.08 * radius_m * rng.uniform(0.3, 1.0, 3)
    wobble = sum(amplitude[j] * np.sin((j + 2) * angle + phase[j]) for j in range(3))
    radius = radius_m + wobble + rng.uniform(-noise_m, noise_m, vertices)
    return np.column_stack([center[0] + radius * np.cos(angle), center[1] + radius * np.sin(angle)])


@dataclass(frozen=True, slots=True)
class RoughCase:
    """Un caso de la batería: su número, semilla, vértices (300 a 1.500), ruido (0 a 0,8 m), si es descendente y si lleva
    roseta; el anillo está en ``ring``."""

    index: int
    seed: int
    vertices: int
    noise_m: float
    descending: bool
    with_rose: bool
    ring: np.ndarray


def rough_case(index: int) -> RoughCase:
    """El caso ``index`` (0 a :data:`ROUGH_CASES` − 1) de la batería, **determinista**: la semilla ``1000 + index``, los
    vértices ``300 + (401·index mod 1.201)``, el ruido ``0,8 · ((37·index) mod 101)/100`` y las cuatro combinaciones de
    ascendente o descendente con y sin roseta, por turnos."""
    vertices = 300 + (401 * index) % 1201
    noise = ROUGH_MAX_NOISE_M * ((37 * index) % 101) / 100.0
    return RoughCase(index, 1000 + index, vertices, noise, bool(index % 2), bool((index // 2) % 2),
                     rough_ring(1000 + index, vertices, noise))


def rough_cases(count: int = ROUGH_CASES) -> Iterator[RoughCase]:
    """Los primeros ``count`` casos de :func:`rough_case`."""
    for index in range(count):
        yield rough_case(index)


# --- La escala (plan §7.3; T36): bajo demanda -----------------------------------------------------------------

SCALE_BENCH_COUNTS: tuple[int, ...] = (40, 60)
SCALE_VERTICES = 160_000
"""Las cortas de escala: 40 y 60 bancos con ≈ 160.000 vértices en total (pie y cresta de cada banco)."""


def scale_grid() -> Any:
    """La rejilla de escala: 1.654 × 1.699 celdas de 1 m (2,81 M), la de la 013 (otra esquina que :data:`BASE`)."""
    return sdata.scale_grid()


def scale_rings(benches: int, total_vertices: int = SCALE_VERTICES, profile: Any = EXPL,
                start_radius_m: float = 100.0) -> np.ndarray:
    """Los anillos concéntricos (pie y cresta de cada banco) de una corta circular de ``benches`` bancos en la rejilla
    de escala, centrada en ella: ``(2·benches, m, 2)`` locales con ``m = total_vertices // (2·benches)``. 60 bancos de
    :data:`EXPL` desde 100 m ocupan hasta 806 m de radio (cabe en 1.654 × 1.699 m)."""
    grid = scale_grid()
    center = (grid.ncols * grid.dx / 2.0, grid.nrows * grid.dy / 2.0)
    per_ring = total_vertices // (2 * benches)
    rings = []
    for foot, crest in circle_radii_by_hand(profile, start_radius_m, benches):
        rings.append(circle_ring(foot, per_ring, center))
        rings.append(circle_ring(crest, per_ring, center))
    return np.stack(rings)


# --- El proyecto ---------------------------------------------------------------------------------------------

RASTERS: Mapping[str, Callable[[Any], np.ndarray]] = {
    "corta_llano": flat_terrain,
    "corta_inclinado": inclined_terrain,
    "corta_limite": limit_terrain,
}
"""Los terrenos que se escriben en el proyecto como rejillas (nombre de la orden → su función de la rejilla)."""
BUILD_BUDGET_S = 2.0
"""Lo que añade la plantilla a la cantera de la 015 (copiarla y escribir tres rejillas) se construye en ≤ 2 s de CPU."""
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
    """Copia el proyecto de la 015 ``base`` en ``folder``, le escribe las rejillas de la corta y lo cierra."""
    from tests.support.res_fixtures import write_grids

    started = time.process_time()
    shutil.copytree(base["folder"] / "proyectos", folder / "proyectos")
    clock = FakeClock(base["now"])
    project = _open(folder, base, clock)
    try:
        grid = qfx.grid_of(step_m)
        clock.advance(minutes=1)
        write_grids(project, [(label, raster_of(make(grid), grid)) for label, make in RASTERS.items()],
                    message="Terrenos de la corta")
        clock.advance(minutes=1)
        return {"folder": folder, "name": base["name"], "now": clock.now(), "versions": base["versions"],
                "build_s": time.process_time() - started}
    finally:
        project.close()


def project_template(step_m: float = COARSE_STEP_M) -> Mapping[str, Any]:
    """El proyecto de la cantera de la 015 con los terrenos de la corta, con la rejilla de ``step_m`` m (por defecto la
    gruesa de 2 m), creado y cerrado la primera vez que se pide en el proceso con ese paso, en una carpeta temporal que
    se borra al salir: ``folder``, ``name``, ``now``, los uid de ``versions`` (V01 y V02) y ``build_s``, la CPU que
    gastó **añadir lo de la 018** (s). No se modifica."""
    found = _TEMPLATES.get(step_m)
    if found is None:
        base = efx.project_template(step_m)  # antes del registro: construye la suya con el suyo
        folder = Path(tempfile.mkdtemp(prefix="gb-pt-"))
        atexit.register(shutil.rmtree, folder, ignore_errors=True)
        with cp.constraints_registered():
            found = _TEMPLATES[step_m] = _build(folder, base, step_m)
    return found


@contextmanager
def open_pit_project(prefix: str = "gb-pp-", step_m: float = COARSE_STEP_M) -> Iterator[tuple[Any, FakeClock]]:
    """Una copia propia del proyecto de :func:`project_template` abierta en escritura: ``(project, clock)``. Al salir se
    cierra y se borra. Hace falta ``constraints_project.constraints_registered()`` activo (lo está en una
    :class:`PitProjectCase`)."""
    made = project_template(step_m)
    with project_tmp(prefix) as folder:
        shutil.copytree(made["folder"] / "proyectos", folder / "proyectos")
        clock = FakeClock(made["now"])
        project = _open(folder, made, clock)
        try:
            yield project, clock
        finally:
            project.close()


class PitProjectCase(qfx.QuarryProjectCase):
    """Una copia **por clase** del proyecto de :func:`project_template`, abierta en escritura: lo de
    :class:`~tests.support.quarry_fixtures.QuarryProjectCase` (``cls.project``, ``cls.root``, ``cls.clock``,
    ``cls.v1``, ``cls.v2``, ``cls.grid``…), en la rejilla gruesa de 2 m salvo que la clase ponga otro ``STEP_M``, con los
    tres terrenos de :data:`RASTERS` (``dataset_of``)."""

    STEP_M: ClassVar[float] = COARSE_STEP_M

    @classmethod
    def setUpClass(cls) -> None:
        versions_read = import_geoblender("core.versions.read")
        cls.grid = qfx.grid_of(cls.STEP_M)
        made = project_template(cls.STEP_M)
        cls.enterClassContext(cp.constraints_registered())
        cls.project, cls.clock = cls.enterClassContext(open_pit_project("gb-pc-", cls.STEP_M))
        cls.root = Path(cls.project.root)
        with cls.project.read() as conn:
            cls.v1, cls.v2 = (versions_read.version(conn, uid) for uid in made["versions"])
