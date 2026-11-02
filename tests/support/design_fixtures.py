# SPDX-License-Identifier: GPL-3.0-or-later
"""Datos de referencia de las envolventes y el escalonado (spec 013, T01; plan 013 §7.1;
CE-013-01 a CE-013-05, CE-013-07 y CE-013-09).

Todo es sintético y pequeño (rejillas de ≤ 240 × 240 celdas, RNF-001-01), en coordenadas
**absolutas** float64 (EPSG:25830 + EPSG:5782) desde la esquina :data:`BASE` de
``tests.support.constraints_fixtures`` (alineada con celdas de 1 y de 2 m). No usan el código de
``design``: son sus entradas y sus cifras hechas a mano. Cada método que da un array da uno
**nuevo**: cambiarlo no cambia el siguiente. En las rejillas, la fila 0 es el norte y una celda
sin semilla vale ``+inf`` (:class:`~design.seeds.SeedSet`); las envolventes son
``E_up = mín_q [f_q + t·d]`` y ``E_down = máx_q [f_q − t·d]`` con la distancia ``d`` entre
centros de celda en metros.

- **Cono** (:func:`cone_case`, CE-013-01): una semilla en el centro de 201 × 201 celdas de 1 m; las
  distancias entre centros con triángulos pitagóricos (:data:`CONE_HAND`), la ascendente y la
  descendente exactas con la tangente de 35° y :func:`analytic_distance`, la distancia analítica de
  un punto a los centros de celda.
- **Pared** (:func:`wall_case`, CE-013-01): una columna entera de semillas a la misma cota,
  alineada con la rejilla, con pendiente 0,5 exacta. **Ojo (T06):** la euclídea da ``f ± t·h·n``;
  el *chamfer* 5×5 con la escala 0,98644 del ADR-0014 da un 1,356 % menos a lo largo del eje (solo
  sin escala es exacto: ``tests/unit/design/test_oracles.py``).
- **Semillas dispersas** (:func:`scattered_seeds`, CE-013-02): deterministas, con cotas múltiplos de
  0,25 m.
- **Perfiles de banco** (:data:`PROFILES`, CE-013-03; RF-013-20): ``EXPL_10_60_6`` (11,77 m y
  40,3°), ``REST_5_35_6`` (13,14 m y 20,83°) y ``DESD_10_45_6`` (16,00 m y 32,0°), con ancla 125 m,
  y :func:`hand_levels`, las cotas ``z₀ + n·h`` de un rango.
- **Plano inclinado** (:func:`plane_case`, CE-013-03): 160 × 40 celdas de 1 m, cota
  ``140 + 0,25·(columna + 0,5)``, exacta en binario.
- **Sectores** (:func:`imposed_sector_case`, :func:`three_sectors_case`, CE-013-04, CE-013-05): el
  de 10,6° con ``REST_5_35_6`` y berma ``máx(B, h/tan β − h/tan α)`` = **19,5765237 m**
  (:data:`IMPOSED_BERM_M`; el RF-013-25 y el CE-013-04 citan «19,576 m», que es ese valor
  truncado al milímetro: contra la cuenta a mano, no contra 19,576), y tres sectores de 50 columnas
  con taludes de 10,6°, 18° y el del perfil. Con sus anillos absolutos, sus etiquetas por celda y
  su cresta de semillas.
- **Corta circular** (:func:`pit_case`, CE-013-09; inv. 07 §3.10): R = 50 m, seis bancos de 10 m,
  cara de 70°, berma de 8 m, terreno llano a 60 m y fondo a 0 m: **1.308.944,0056 m³** analíticos
  (los de la 006, ADR-0014), con celdas de 1 y de 2 m en 240 × 240 m.
- **Ladera y relleno ×40** (:func:`hillside_case`, :data:`FILL_RATIO`, CE-013-07; errores 10, 17,
  56 y 66): semillas «en toda la ladera» con 2.000 celdas fuera del dominio y un relleno de
  716.000 m³ frente a 17.607 m³ de la revisión anterior.
- **El proyecto del diseño** (:func:`project_template`, :class:`DesignProjectCase`): el de las
  restricciones de la 012 (``tests.support.constraints_project``: V01 y V02, 160 × 160 celdas de
  2 m, el límite legal, las cinco restricciones y los dos sectores) con las búsquedas de
  intocables de los dos sectores cerradas, la superficie de partida del sitio como rejilla del
  proyecto (:data:`START_DATASET`) y las máscaras de V01 compiladas; V02 sin compilar. Se crea
  **una vez por proceso** y cada clase trabaja en su copia (menos de 1 s).

Ningún dato de cliente.
"""

from __future__ import annotations

import atexit
import math
import shutil
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import constraints_project as cp
from tests.support.core_fixtures import FakeClock, FakePids, project_tmp
from tests.support.package import import_geoblender

gis = import_geoblender("gis")

CRS = cfx.CRS
"""El CRS de todos los casos (ETRS89 / UTM 30N)."""
VERTICAL = cfx.VERTICAL
"""La referencia vertical de las superficies (Alicante)."""
BASE: tuple[float, float] = cfx.BASE
"""La esquina suroeste de las rejillas de los casos (m, absoluta)."""


# --- Ayudas ----------------------------------------------------------------------------------


def grid_from(nrows: int, ncols: int, step: float, *, west: float | None = None,
              south: float | None = None) -> Any:
    """Una rejilla de ``nrows × ncols`` celdas de ``step`` m con su esquina suroeste en
    ``(west, south)`` (por defecto, :data:`BASE`)."""
    corner_x = BASE[0] if west is None else float(west)
    corner_y = BASE[1] if south is None else float(south)
    return gis.Grid(corner_x, corner_y + nrows * step, step, step, ncols, nrows)


def raster(grid: Any, values: np.ndarray) -> Any:
    """``values`` como superficie (``gis.Raster``) de ``grid`` con el CRS y el datum vertical de los
    casos."""
    return gis.Raster(grid, values, CRS, VERTICAL)


def centers(grid: Any) -> tuple[np.ndarray, np.ndarray]:
    """Las coordenadas de los centros de celda en metros desde la esquina suroeste de ``grid``
    (``x`` hacia el este, ``y`` hacia el norte), de forma ``grid.shape`` y en float64."""
    columns = (np.arange(grid.ncols) + 0.5) * grid.dx
    rows = (grid.nrows - np.arange(grid.nrows) - 0.5) * grid.dy
    return np.meshgrid(columns, rows)


def south_of(grid: Any) -> float:
    """El borde sur de ``grid`` (m, absoluto)."""
    return float(grid.north - grid.nrows * grid.dy)


def analytic_distance(grid: Any, x: float, y: float) -> np.ndarray:
    """La distancia (m) del punto absoluto ``(x, y)`` al centro de cada celda de ``grid``: el cono
    analítico de un punto (CE-013-01), calculada desde la esquina de la rejilla para no perder
    decimales."""
    cell_x, cell_y = centers(grid)
    return np.hypot(cell_x - (x - grid.west), cell_y - (y - south_of(grid)))


def _ring(left: float, bottom: float, right: float, top: float) -> np.ndarray:
    """El anillo absoluto, cerrado y antihorario del rectángulo dado (m, absolutos)."""
    return np.array([(left, bottom), (right, bottom), (right, top), (left, top), (left, bottom)],
                    dtype=np.float64)


# --- Cono (CE-013-01) ------------------------------------------------------------------------

CONE_HAND: tuple[tuple[int, int, float], ...] = (
    (0, 0, 0.0), (3, 4, 5.0), (5, 12, 13.0), (8, 15, 17.0), (20, 21, 29.0), (0, 100, 100.0),
    (60, 80, 100.0), (100, 100, 100.0 * math.sqrt(2.0)),
)
"""Distancias a mano entre centros de celda: ``(filas, columnas, metros)`` desde la semilla, con
celdas de 1 m (triángulos 3-4-5, 5-12-13, 8-15-17, 20-21-29 y 60-80-100; 100 m de eje y 100√2 m de
diagonal). Valen en los cuatro cuadrantes."""


@dataclass(frozen=True, slots=True, eq=False)
class ConeCase:
    """El cono de una semilla: la rejilla (201 × 201 celdas de 1 m), la celda de la semilla
    (``seed_row``, ``seed_col``), su cota (``seed_z``) y la pendiente (``slope_deg``)."""

    grid: Any
    seed_row: int
    seed_col: int
    seed_z: float
    slope_deg: float

    @property
    def slope_tan(self) -> float:
        """La tangente de la pendiente."""
        return math.tan(math.radians(self.slope_deg))

    @property
    def seed_point(self) -> tuple[float, float]:
        """El centro de la celda de la semilla (m, absoluto): ``x = oeste + (columna + 0,5)·dx`` e
        ``y = norte − (fila + 0,5)·dy``."""
        grid = self.grid
        return (grid.west + (self.seed_col + 0.5) * grid.dx,
                grid.north - (self.seed_row + 0.5) * grid.dy)

    def seeds(self) -> np.ndarray:
        """La rejilla de semillas: ``seed_z`` en la celda de la semilla y ``+inf`` en las demás."""
        found = np.full(self.grid.shape, np.inf)
        found[self.seed_row, self.seed_col] = self.seed_z
        return found

    def distances(self) -> np.ndarray:
        """La distancia (m) entre centros de celda de cada celda a la de la semilla."""
        rows, cols = np.indices(self.grid.shape)
        return self.grid.dx * np.hypot(rows - self.seed_row, cols - self.seed_col)

    def up(self) -> np.ndarray:
        """La ascendente exacta: ``f + t·d``."""
        return self.seed_z + self.slope_tan * self.distances()

    def down(self) -> np.ndarray:
        """La descendente exacta: ``f − t·d``."""
        return self.seed_z - self.slope_tan * self.distances()


def cone_case() -> ConeCase:
    """El cono de CE-013-01: una semilla a 200 m en el centro de 201 × 201 celdas de 1 m, con la
    pendiente de 35°."""
    return ConeCase(grid_from(201, 201, 1.0), 100, 100, 200.0, 35.0)


# --- Pared (CE-013-01) y semillas dispersas (CE-013-02) -------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class WallCase:
    """Una pared plana alineada con la rejilla: la columna ``column`` entera de semillas a la cota
    ``wall_z``, con la tangente ``slope_tan``."""

    grid: Any
    column: int
    wall_z: float
    slope_tan: float

    def seeds(self) -> np.ndarray:
        """Las semillas: la columna de la pared a ``wall_z``; ``+inf`` en el resto."""
        found = np.full(self.grid.shape, np.inf)
        found[:, self.column] = self.wall_z
        return found

    def _offset(self) -> np.ndarray:
        columns = np.abs(np.arange(self.grid.ncols) - self.column) * self.grid.dx
        return np.broadcast_to(self.slope_tan * columns, self.grid.shape).copy()

    def up(self) -> np.ndarray:
        """La ascendente exacta: ``f + t·h·|columna − pared|``."""
        return self.wall_z + self._offset()

    def down(self) -> np.ndarray:
        """La descendente exacta: ``f − t·h·|columna − pared|``."""
        return self.wall_z - self._offset()


def wall_case(step: float = 1.0) -> WallCase:
    """La pared de CE-013-01: 41 × 41 celdas de ``step`` m, la columna 20 a 250 m y t = 0,5."""
    return WallCase(grid_from(41, 41, step), 20, 250.0, 0.5)


def scattered_seeds(shape: tuple[int, int], count: int, *, seed: int, low: float = 100.0,
                    high: float = 130.0) -> np.ndarray:
    """``count`` semillas en celdas distintas elegidas al azar (determinista con ``seed``), con
    cotas entre ``low`` y ``high`` redondeadas a 0,25 m (exactas en binario); ``+inf`` en las demás.
    ``ValueError`` si ``count`` no cabe en la rejilla."""
    cells = shape[0] * shape[1]
    if not 0 < count <= cells:
        raise ValueError(f"no caben {count} semillas en una rejilla de {shape[0]} × {shape[1]}")
    rng = np.random.default_rng(seed)
    found = np.full(shape, np.inf)
    chosen = rng.choice(cells, size=count, replace=False)
    found.flat[chosen] = np.round(rng.uniform(low, high, size=count) * 4.0) / 4.0
    return found


ZONE_KINDS: tuple[str, ...] = ("loose", "contour", "solid", "mixed")
"""Las formas de :func:`random_zone`."""


def random_zone(rng: np.random.Generator, shape: tuple[int, int], kind: str,
                rise: float) -> np.ndarray:
    """Unas semillas aleatorias (T08, la euclídea exacta) de la forma ``kind``: ``loose`` (1 a 6
    celdas sueltas), ``contour`` (el contorno de un rectángulo), ``solid`` (el rectángulo entero,
    con un plano de hasta 2 ``rise`` por celda más un ruido, de modo que unas vecinas pasan del
    umbral de la semilla redundante y otras no) o ``mixed`` (macizas y sueltas). ``rise`` es lo que
    sube la envolvente por celda (``t·h``, m); la rejilla de salida es nueva, con ``+inf`` donde no
    hay semilla. ``shape`` ha de tener al menos 3 filas y 3 columnas."""
    nrows, ncols = shape
    values = np.full(shape, np.inf)
    amplitude = rise if rise > 0.0 else 0.5
    if kind in ("contour", "solid", "mixed"):
        top = int(rng.integers(0, nrows - 2))
        bottom = int(rng.integers(top + 2, nrows))
        left = int(rng.integers(0, ncols - 2))
        right = int(rng.integers(left + 2, ncols))
        rows, cols = np.indices((bottom - top + 1, right - left + 1))
        plane = (float(rng.uniform(-2, 2)) * rows + float(rng.uniform(-2, 2)) * cols) * amplitude
        noise = rng.uniform(-0.5, 0.5, rows.shape) * amplitude * float(rng.choice([0.2, 1.0, 3.0]))
        patch = 100.0 + plane + noise
        if kind == "contour":
            edge = np.zeros(rows.shape, dtype=bool)
            edge[0, :] = edge[-1, :] = edge[:, 0] = edge[:, -1] = True
            patch = np.where(edge, patch, np.inf)
        values[top:bottom + 1, left:right + 1] = patch
    if kind in ("loose", "mixed"):
        count = min(int(rng.integers(1, 7)), values.size)
        cells = rng.choice(values.size, size=count, replace=False)
        values.flat[cells] = rng.uniform(90.0, 130.0, count)
    return values


# --- Perfiles de banco (RF-013-18, RF-013-20) ------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProfileData:
    """Un perfil de banco: nombre, código (ASCII en minúsculas del nombre, D-17), altura de banco
    ``height_m`` (m), inclinación de la cara ``face_deg`` (°), berma mínima ``berm_m`` (m), cota de
    ancla ``anchor_m`` (m) y factor de malla. Los derivados, a mano (RF-013-20)."""

    name: str
    code: str
    height_m: float
    face_deg: float
    berm_m: float
    anchor_m: float
    mesh_factor: float = 1.0

    @property
    def advance_m(self) -> float:
        """El avance ``a = h/tan α + B`` (m)."""
        return self.height_m / math.tan(math.radians(self.face_deg)) + self.berm_m

    @property
    def general_tan(self) -> float:
        """La tangente del talud general: ``h / a``."""
        return self.height_m / self.advance_m

    @property
    def general_deg(self) -> float:
        """El talud general ``atan(h / a)`` (°)."""
        return math.degrees(math.atan(self.general_tan))


ANCHOR_M = 125.0
"""La cota de ancla de los perfiles de prueba (m)."""


def _profile(name: str) -> ProfileData:
    _prefix, height, face, berm = name.split("_")
    return ProfileData(name, name.lower(), float(height), float(face), float(berm), ANCHOR_M)


EXPL_10_60_6 = _profile("EXPL_10_60_6")
REST_5_35_6 = _profile("REST_5_35_6")
DESD_10_45_6 = _profile("DESD_10_45_6")
PROFILES: Mapping[str, ProfileData] = {item.name: item for item in
                                       (EXPL_10_60_6, REST_5_35_6, DESD_10_45_6)}
"""Los tres perfiles de la spec: ``EXPL_10_60_6``, ``REST_5_35_6`` y ``DESD_10_45_6``."""


def hand_levels(profile: ProfileData, low: float, high: float) -> tuple[float, ...]:
    """Las cotas ``z₀ + n·h`` (``n`` entero, también negativo) del perfil dentro de ``[low, high]``,
    de menor a mayor."""
    first = math.ceil((low - profile.anchor_m) / profile.height_m)
    last = math.floor((high - profile.anchor_m) / profile.height_m)
    return tuple(profile.anchor_m + number * profile.height_m for number in range(first, last + 1))


def imposed_berm_m(profile: ProfileData, imposed_deg: float | None) -> float:
    """La berma de un sector (RF-013-25, a mano): ``máx(B, h/tan β − h/tan α)`` con el talud general
    máximo impuesto ``β``; sin talud impuesto, la mínima del perfil."""
    if imposed_deg is None:
        return profile.berm_m
    face = profile.height_m / math.tan(math.radians(profile.face_deg))
    general = profile.height_m / math.tan(math.radians(imposed_deg))
    return max(profile.berm_m, general - face)


# --- Plano inclinado (CE-013-03) -------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class PlaneCase:
    """Un plano inclinado hacia el este: cota ``base_z + slope_tan·(columna + 0,5)·dx``."""

    grid: Any
    base_z: float
    slope_tan: float

    def surface(self) -> np.ndarray:
        """La superficie en los centros de celda (exacta en binario con pendiente 0,25)."""
        columns = self.base_z + self.slope_tan * (np.arange(self.grid.ncols) + 0.5) * self.grid.dx
        return np.broadcast_to(columns, self.grid.shape).copy()


def plane_case() -> PlaneCase:
    """El plano de CE-013-03: 160 × 40 celdas de 1 m, de 140,125 a 179,875 m (pendiente 0,25)."""
    return PlaneCase(grid_from(40, 160, 1.0), 140.0, 0.25)


# --- Sectores con talud impuesto (CE-013-04, CE-013-05) -------------------------------------

IMPOSED_DEG = 10.6
"""El talud general máximo impuesto de CE-013-04 (°)."""
IMPOSED_BERM_M = imposed_berm_m(REST_5_35_6, IMPOSED_DEG)
"""La berma del sector de 10,6° con ``REST_5_35_6``: 5/tan 10,6° − 5/tan 35° = 19,5765237 m (el
«19,576 m» de la spec, truncado al milímetro)."""
CREST_Z = 200.0
"""La cota de la cresta de semillas de los sectores (m)."""


@dataclass(frozen=True, slots=True, eq=False)
class SectorsCase:
    """Un frente de sectores en franjas de columnas: la rejilla, los ``codes`` de los sectores, los
    bordes ``edges`` de sus columnas (uno más que sectores), el talud general máximo impuesto de
    cada uno en grados (``None``: ninguno), el perfil base y la cota de la cresta ``crest_z`` (la
    fila norte, de semillas)."""

    grid: Any
    codes: tuple[str, ...]
    edges: tuple[int, ...]
    imposed_deg: tuple[float | None, ...]
    profile: ProfileData
    crest_z: float

    def labels(self) -> np.ndarray:
        """El sector de cada celda (``int16``, 1 a n por el orden de ``codes``; 0 = ninguno)."""
        found = np.zeros(self.grid.shape, dtype=np.int16)
        for index, (left, right) in enumerate(zip(self.edges[:-1], self.edges[1:], strict=True),
                                              start=1):
            found[:, left:right] = index
        return found

    def rings(self) -> dict[str, np.ndarray]:
        """El anillo absoluto, cerrado y antihorario de cada sector (código → ``(5, 2)``)."""
        grid = self.grid
        south = south_of(grid)
        return {code: _ring(grid.west + left * grid.dx, south, grid.west + right * grid.dx,
                            grid.north)
                for code, left, right in zip(self.codes, self.edges[:-1], self.edges[1:],
                                             strict=True)}

    def seeds(self) -> np.ndarray:
        """La cresta: la fila norte entera a ``crest_z``; ``+inf`` en el resto."""
        found = np.full(self.grid.shape, np.inf)
        found[0, :] = self.crest_z
        return found

    def berm_m(self, code: str) -> float:
        """La berma esperada del sector ``code`` (a mano, RF-013-25). ``KeyError`` si no existe."""
        imposed = dict(zip(self.codes, self.imposed_deg, strict=True))[code]
        return imposed_berm_m(self.profile, imposed)


def imposed_sector_case() -> SectorsCase:
    """CE-013-04: 120 × 100 celdas de 1 m en dos mitades de 60 columnas: «frente_tendido» con 10,6°
    y «frente_normal» sin talud impuesto, con ``REST_5_35_6``."""
    return SectorsCase(grid_from(100, 120, 1.0), ("frente_tendido", "frente_normal"), (0, 60, 120),
                       (IMPOSED_DEG, None), REST_5_35_6, CREST_Z)


def three_sectors_case() -> SectorsCase:
    """CE-013-05: 150 × 100 celdas de 1 m en tres franjas de 50 columnas con taludes de 10,6°, 18° y
    el del perfil (``REST_5_35_6``)."""
    return SectorsCase(grid_from(100, 150, 1.0), ("sector_a", "sector_b", "sector_c"),
                       (0, 50, 100, 150), (IMPOSED_DEG, 18.0, None), REST_5_35_6, CREST_Z)


# --- Corta circular (CE-013-09) --------------------------------------------------------------

PIT_SIDE_M = 240.0
"""El lado de la rejilla de la corta (m): 120 m de eje a borde, más que su boca (111,84 m)."""
PIT_PROFILE = ProfileData("CORTA_10_70_8", "corta_10_70_8", 10.0, 70.0, 8.0, 0.0)
"""El perfil de la corta de inv. 07 §3.10: bancos de 10 m, cara de 70°, berma de 8 m, ancla en el
fondo (0 m)."""
PIT_RADIUS_M = 50.0
"""El radio del fondo (m)."""
PIT_BENCHES = 6


@dataclass(frozen=True, slots=True, eq=False)
class PitCase:
    """La corta circular de CE-013-09 en una rejilla de ``PIT_SIDE_M`` m con el eje (``axis``,
    absoluto) en un nodo: fondo de radio ``floor_radius_m`` a ``floor_z``, ``benches`` bancos del
    perfil ``profile`` y terreno llano a ``terrain_z``."""

    grid: Any
    axis: tuple[float, float]
    floor_radius_m: float
    floor_z: float
    benches: int
    profile: ProfileData

    @property
    def depth_m(self) -> float:
        """La profundidad: ``bancos · h`` (m)."""
        return self.benches * self.profile.height_m

    @property
    def terrain_z(self) -> float:
        """La cota del terreno llano (m)."""
        return self.floor_z + self.depth_m

    @property
    def face_m(self) -> float:
        """La proyección horizontal de la cara de un banco: ``h / tan α`` (m)."""
        return self.profile.height_m / math.tan(math.radians(self.profile.face_deg))

    @property
    def top_radius_m(self) -> float:
        """El radio de la boca (m): ``R + n·(h/tan α + B) − B`` con ``n`` bancos."""
        return (self.floor_radius_m + self.benches * self.face_m
                + (self.benches - 1) * self.profile.berm_m)

    @property
    def analytic_m3(self) -> float:
        """El volumen analítico (m³): la suma de los troncos de cono de los bancos,
        ``Σ π·h/3·(rᵢ² + rᵢ·Rᵢ + Rᵢ²)`` con ``rᵢ = R + i·(h/tan α + B)`` y ``Rᵢ = rᵢ + h/tan α``."""
        total = 0.0
        for index in range(self.benches):
            lower = self.floor_radius_m + index * (self.face_m + self.profile.berm_m)
            upper = lower + self.face_m
            total += math.pi * self.profile.height_m / 3.0 * (
                lower * lower + lower * upper + upper * upper)
        return total

    def terrain(self) -> np.ndarray:
        """El terreno llano."""
        return np.full(self.grid.shape, self.terrain_z)

    def seeds(self) -> np.ndarray:
        """La semilla: el disco del fondo (los centros de celda a ≤ ``floor_radius_m`` del eje) a
        ``floor_z``; ``+inf`` en el resto."""
        cell_x, cell_y = centers(self.grid)
        radius = np.hypot(cell_x - (self.axis[0] - self.grid.west),
                          cell_y - (self.axis[1] - south_of(self.grid)))
        return np.where(radius <= self.floor_radius_m, self.floor_z, np.inf)

    def surface(self) -> np.ndarray:
        """La corta analítica muestreada en el centro de cada celda: cara de cada banco y berma
        plana hasta el terreno (la fórmula de la 006)."""
        cell_x, cell_y = centers(self.grid)
        radius = np.hypot(cell_x - (self.axis[0] - self.grid.west),
                          cell_y - (self.axis[1] - south_of(self.grid)))
        tangent = math.tan(math.radians(self.profile.face_deg))
        module = self.face_m + self.profile.berm_m
        out = np.maximum(radius - self.floor_radius_m, 0.0)
        bench = np.floor(out / module)
        rise = np.minimum(out - bench * module, self.face_m) * tangent
        return self.floor_z + np.minimum(bench * self.profile.height_m + rise, self.depth_m)

    @property
    def cut_m3(self) -> float:
        """El desmonte de la corta muestreada (m³): ``Σ (terreno − corta)·área de celda``."""
        return float(np.sum(self.terrain() - self.surface())) * self.grid.cell_area


def pit_case(step: float) -> PitCase:
    """La corta de CE-013-09 con celdas de ``step`` m (1 o 2; vale cualquier paso que deje el eje en
    un nodo). ``ValueError`` si el paso no es > 0 o no divide los 120 m de eje a borde."""
    value = float(step)
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"el paso debe ser un número finito > 0, no {step!r}")
    half = PIT_SIDE_M / 2.0 / value
    if abs(half - round(half)) > 1e-9:
        raise ValueError(f"el paso {step!r} no deja el eje de la corta en un nodo de la rejilla")
    cells = int(round(PIT_SIDE_M / value))
    grid = grid_from(cells, cells, value)
    axis = (grid.west + PIT_SIDE_M / 2.0, grid.north - PIT_SIDE_M / 2.0)
    return PitCase(grid, axis, PIT_RADIUS_M, 0.0, PIT_BENCHES, PIT_PROFILE)


# --- Ladera y relleno ×40 (CE-013-07) --------------------------------------------------------

FILL_PREVIOUS_M3 = 17_607.0
"""El relleno de la revisión anterior (m³; errores 10, 17, 56 y 66)."""
FILL_CURRENT_M3 = 716_000.0
"""El relleno que sale con las semillas «en toda la ladera» (m³)."""
FILL_RATIO = FILL_CURRENT_M3 / FILL_PREVIOUS_M3
"""Cuántas veces mayor es (×40,66), por encima del umbral de aviso (2,0, D-7)."""


@dataclass(frozen=True, slots=True, eq=False)
class HillsideCase:
    """Una ladera de ``nrows × ncols`` celdas de 2 m que sube hacia el norte (``slope_tan``) con
    semillas en toda ella: las ``seed_rows`` filas del norte, sobre el terreno. El dominio de
    trabajo son las celdas a más de ``margin`` del borde; las semillas que quedan fuera se
    cuentan a mano."""

    grid: Any
    base_z: float
    slope_tan: float
    seed_rows: int
    margin: int

    def terrain(self) -> np.ndarray:
        """El terreno: ``base_z + t·y`` con ``y`` los metros desde el borde sur al centro."""
        _cell_x, cell_y = centers(self.grid)
        return self.base_z + self.slope_tan * cell_y

    def seeds(self) -> np.ndarray:
        """Las semillas: las ``seed_rows`` filas del norte a la cota del terreno; ``+inf`` en el
        resto."""
        found = np.full(self.grid.shape, np.inf)
        found[:self.seed_rows] = self.terrain()[:self.seed_rows]
        return found

    def domain(self) -> np.ndarray:
        """El dominio de trabajo: las celdas a más de ``margin`` celdas del borde."""
        found = np.zeros(self.grid.shape, dtype=bool)
        found[self.margin:-self.margin, self.margin:-self.margin] = True
        return found

    @property
    def seed_cells(self) -> int:
        """Las celdas de semilla, a mano: ``filas · columnas``."""
        return self.seed_rows * self.grid.ncols

    @property
    def inside_domain(self) -> int:
        """Las semillas dentro del dominio, a mano."""
        return (self.seed_rows - self.margin) * (self.grid.ncols - 2 * self.margin)

    @property
    def outside_domain(self) -> int:
        """Las semillas fuera del dominio, a mano."""
        return self.seed_cells - self.inside_domain


def hillside_case() -> HillsideCase:
    """La ladera de CE-013-07: 100 × 100 celdas de 2 m, tan = 0,5 hacia el norte, semillas en las
    60 filas del norte (6.000 celdas) y dominio de 80 × 80 celdas (2.000 semillas fuera)."""
    return HillsideCase(grid_from(100, 100, 2.0), 100.0, 0.5, 60, 10)


# --- El proyecto del diseño ------------------------------------------------------------------

START_LABEL = "partida"
"""El nombre de la superficie de partida del sitio al escribirla (``write_grids``)."""
START_DATASET = f"gis_dtm_{START_LABEL}"
"""El dato de la superficie de partida del sitio en el proyecto: el llano a
``constraints_fixtures.START_Z`` (650 m) en la rejilla del sitio."""
_TEMPLATE: dict[str, Any] = {}


def _close_searches(project: Any, clock: FakeClock) -> None:
    """Cierra la búsqueda de intocables de cada sector (con su huella), como hará la orden de la
    012: los sectores quedan sin la marca de búsqueda pendiente."""
    cmodel = import_geoblender("core.constraints.model")
    cstore = import_geoblender("core.constraints.store")
    operations = import_geoblender("core.provenance.operations")
    for index, sector in enumerate(cp.sectors(), start=1):
        clock.advance(minutes=1)
        handle = operations.begin_operation(project, cp.EDIT_TYPE, settings={"count": 0},
                                            executor="blender")
        record = cmodel.SearchRecord(f"search{index}{'0' * 25}", handle.uid, sector.code,
                                     cstore.sector_sha256(sector), cfx.SEARCH_DISTANCE_M,
                                     "Samuel (IMGA)", "2026-10-28T10:00:00Z")
        with project.write_transaction() as conn:
            cstore.append_search(conn, record, ())
            handle.complete(conn, outputs=cstore.dataset_specs(crs_epsg=project.record.crs_epsg),
                            message="Búsqueda de prueba")


def _build(folder: Path) -> dict[str, Any]:
    """Crea el proyecto de :func:`project_template` en ``folder/proyectos`` y lo cierra."""
    from tests.support.res_fixtures import write_grids

    open_mod = import_geoblender("core.project.open")
    userdata = import_geoblender("core.userdata")
    versions_read = import_geoblender("core.versions.read")
    access = import_geoblender("gis.masks.access")
    base = cp.project_template()
    shutil.copytree(base["folder"] / "proyectos", folder / "proyectos")
    clock = FakeClock(base["now"])
    with cp.constraints_registered():
        project = open_mod.open_project(
            folder / "proyectos" / base["name"], cp.SESSION, userdata.UserData(folder / "u"),
            clock=clock, pid_alive=FakePids({cp.SESSION.pid})).project
        try:
            with project.read() as conn:
                first = versions_read.version(conn, base["versions"][0])
            _close_searches(project, clock)
            clock.advance(minutes=1)
            write_grids(project, [(START_LABEL, cfx.site_start())],
                        message="Superficie de partida del sitio")
            clock.advance(minutes=1)
            for _step in access.ensure_masks_steps(project, first.uid):
                pass
            clock.advance(minutes=1)
            return {"folder": folder, "name": base["name"], "now": clock.now(),
                    "versions": tuple(base["versions"])}
        finally:
            project.close()


def project_template() -> Mapping[str, Any]:
    """El proyecto del diseño (véase el módulo), creado y cerrado la primera vez que se pide en el
    proceso en una carpeta temporal que se borra al salir: lo que copian :func:`open_design_project`
    y :class:`DesignProjectCase` (``folder``, ``name`` de la carpeta del proyecto, ``now`` del reloj
    al terminar y los uid de ``versions``: V01 y V02). No se modifica."""
    if not _TEMPLATE:
        folder = Path(tempfile.mkdtemp(prefix="gb-dt-"))
        atexit.register(shutil.rmtree, folder, ignore_errors=True)
        _TEMPLATE.update(_build(folder))
    return _TEMPLATE


@contextmanager
def open_design_project(prefix: str = "gb-dp-") -> Iterator[tuple[Any, FakeClock]]:
    """Una copia propia del proyecto del diseño abierta en escritura: ``(project, clock)``, con el
    reloj en el punto en que lo dejó la plantilla. Al salir se cierra y se borra. Hace falta que
    ``tests.support.constraints_project.constraints_registered()`` esté activo (lo está en una
    :class:`DesignProjectCase`)."""
    open_mod = import_geoblender("core.project.open")
    userdata = import_geoblender("core.userdata")
    made = project_template()
    with project_tmp(prefix) as folder:
        shutil.copytree(made["folder"] / "proyectos", folder / "proyectos")
        clock = FakeClock(made["now"])
        project = open_mod.open_project(
            folder / "proyectos" / made["name"], cp.SESSION, userdata.UserData(folder / "u"),
            clock=clock, pid_alive=FakePids({cp.SESSION.pid})).project
        try:
            yield project, clock
        finally:
            project.close()


class DesignProjectCase(cp.ConstraintsProjectCase):
    """Una copia **por clase** del proyecto del diseño (véase el módulo), abierta en escritura
    (``cls.project``, en ``cls.root``), con lo de ``constraints_registered`` registrado, su reloj
    (``cls.clock``) y V01 y V02 (``cls.v1``, ``cls.v2``); además de ``query``, ``record`` y
    ``stored_constraints`` de ``ConstraintsProjectCase``:

    - :meth:`masks`: el ``MaskSet`` de una versión (por defecto V01, que tiene las máscaras al día);
    - :meth:`write_surfaces`: escribe más superficies como rejillas del proyecto;
    - :meth:`write_layer`: escribe una capa de entidades (polígonos, líneas) o de dominios;
    - :meth:`write_tin`: escribe un TIN del proyecto.

    Para un sector con la búsqueda pendiente, cambie la geometría de un sector con
    ``constraints_project.edit_constraints``; para no tocar la copia de la clase, use
    :func:`open_design_project`."""

    @classmethod
    def setUpClass(cls) -> None:
        versions_read = import_geoblender("core.versions.read")
        made = project_template()
        cls.enterClassContext(cp.constraints_registered())
        cls.project, cls.clock = cls.enterClassContext(open_design_project("gb-dc-"))
        cls.root = Path(cls.project.root)
        with cls.project.read() as conn:
            cls.v1, cls.v2 = (versions_read.version(conn, uid) for uid in made["versions"])

    def masks(self, version: Any = None) -> Any:
        """Las máscaras de ``version`` (``Version``; por defecto V01) ya compiladas
        (``gis.masks.access.load_masks``); ``MaskError`` si no están al día."""
        access = import_geoblender("gis.masks.access")
        target = self.v1 if version is None else version
        return access.load_masks(self.project, target.uid)

    def write_surfaces(self, *grids: tuple[str, Any]) -> None:
        """Escribe cada ``(nombre, Raster)`` como rejilla del proyecto (``gis_dtm_<nombre>``; la que
        ya está, con contenido nuevo), un minuto después."""
        from tests.support.res_fixtures import write_grids

        self.clock.advance(minutes=1)
        write_grids(self.project, list(grids), message="Superficies de prueba")

    def write_layer(self, name: str, entities: Sequence[Sequence[Sequence[np.ndarray]]], *,
                    kind: str = "polygon", domains: bool = False,
                    names: Sequence[str] | None = None) -> None:
        """Escribe una capa del proyecto como lo hace la importación de la 006: ``gis_fea_…``
        (entidades, la 012; ``kind``: ``polygon`` o ``line``) o, con ``domains``, ``gis_dom_…``
        (dominios de polígonos, la 011). ``entities``: por entidad, sus partes y, de cada una,
        sus anillos (el primero, el exterior) o su camino, ABSOLUTOS. ``name`` ha de llevar el
        prefijo de su familia. Cada entidad se llama «Entidad <fid>» en el campo ``nombre`` o,
        con ``names``, como dice ese texto (uno por entidad): con él se declaran sectores con el
        nombre que se quiera."""
        from tests.support.provenance_contract import registered

        contract = import_geoblender("core.provenance.contract")
        operations = import_geoblender("core.provenance.operations")
        datasets = import_geoblender("core.datasets")
        builtin = import_geoblender("core.content.builtin")
        gstore = import_geoblender("gis.store")
        vector = import_geoblender("gis.vector")
        srs = int(self.project.record.crs_epsg)
        column = vector.FieldColumn("nombre", "nombre", "TEXT")
        fids = tuple(range(1, len(entities) + 1))
        if names is not None and len(names) != len(entities):
            raise ValueError("hace falta un nombre por entidad")
        values = {"nombre": tuple(f"Entidad {fid}" for fid in fids) if names is None
                  else tuple(names)}
        polygons = tuple(tuple(tuple(np.asarray(ring, dtype=np.float64) for ring in polygon)
                               for polygon in entity) for entity in entities)
        if domains:
            layer: Any = vector.DomainSet(fids, polygons, (column,), values)
            rows, geometry_type, role = gstore.domain_rows(layer, srs), "MULTIPOLYGON", "domains"
        else:
            layer = vector.FeatureLayer(kind, fids, polygons, (column,), values)
            rows, geometry_type, role = (gstore.feature_rows(layer, srs), layer.geometry_type,
                                         "features")
        writer = contract.OperationDef(LAYERS_TYPE, "1.0", "gis", "Layers of the tests", False)
        with registered(writer):
            self.clock.advance(minutes=1)
            handle = operations.begin_operation(self.project, LAYERS_TYPE,
                                                settings={"name": name}, executor="blender")
            with self.project.write_transaction() as conn:
                conn.execute(f'CREATE TABLE "{name}" (fid INTEGER PRIMARY KEY NOT NULL, '
                             f'geom {geometry_type}, "nombre" TEXT)')
                conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, "
                             "description, srs_id) VALUES (?, 'features', ?, '', ?)",
                             (name, name, srs))
                conn.execute("INSERT INTO gpkg_geometry_columns (table_name, column_name, "
                             "geometry_type_name, srs_id, z, m) VALUES (?, 'geom', ?, ?, 0, 0)",
                             (name, geometry_type, srs))
                conn.executemany(f'INSERT INTO "{name}" (fid, geom, "nombre") VALUES (?, ?, ?)',
                                 rows)
                handle.complete(conn, outputs=(datasets.DatasetSpec(
                    name, "gis", "vector", datasets.Store.GPKG, name,
                    reader=builtin.GPKG_LAYER.id, role=role, crs_epsg=srs, input_uid=None,
                    immutable=False),), message="Capa de prueba")

    def write_tin(self, label: str) -> str:
        """Escribe un TIN de cuatro triángulos sobre la rejilla del sitio como ``gis_tin_<label>``
        y devuelve su nombre."""
        from tests.support.provenance_contract import registered

        operations = import_geoblender("core.provenance.operations")
        provenance = import_geoblender("gis.provenance")
        gstore = import_geoblender("gis.store")
        tin_mod = import_geoblender("gis.tin")
        xy = np.array([[0.0, 0.0], [40.0, 0.0], [40.0, 40.0], [0.0, 40.0], [20.0, 20.0]])
        xy += np.asarray(BASE)
        z = np.array([650.0, 651.0, 652.5, 651.5, 653.25])
        faces = np.array([[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]], dtype=np.int32)
        tin = tin_mod.Tin(np.column_stack([xy, z]), faces, np.empty((0, 2), np.int32),
                          np.zeros(5, np.uint8), triangulator="pure@1")
        defs = provenance.operation_defs({provenance.TIN_FROM_POINTS: _never_recomputed},
                                         op_types=[provenance.TIN_FROM_POINTS])
        with registered(*defs):
            self.clock.advance(minutes=1)
            handle = operations.begin_operation(self.project, provenance.TIN_FROM_POINTS,
                                                settings={"nombre": label}, executor="blender")
            with gstore.ResultWriter(self.project, handle) as out:
                out.tin(label, tin)
                (record,) = out.commit(software={"triangulator": "pure@1"},
                                       message="TIN de prueba")
        return str(record.name)


LAYERS_TYPE = "gis.test_layers"
"""La operación de prueba de ``gis`` que escribe las capas de polígonos (hace lo que la
importación de la 006)."""


def _never_recomputed(request: Any) -> Any:
    raise AssertionError("las pruebas del diseño no recalculan con la función de bl")
