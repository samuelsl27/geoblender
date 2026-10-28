# SPDX-License-Identifier: GPL-3.0-or-later
"""Datos de referencia de los límites legales y las restricciones (spec 012, T02; plan 012 §7.1
y §2.2; CE-012-01 a CE-012-06).

Todo es sintético y pequeño (rejillas de ≤ 160 × 160 celdas, RNF-001-01), en coordenadas
**absolutas** float64 (EPSG:25830 + EPSG:5782), desde la esquina :data:`BASE` (dentro de la
ventana del proyecto sintético de ``tests.support.core_fixtures``, alineada con sus celdas de 1
y de 2 m). No usan el código de la 012: son sus entradas y sus cifras hechas a mano.

- **Máscaras de referencia** (CE-012-01; RF-012-12; :func:`mask_cases`): con celdas de 1 y de
  2 m, en una ventana de 140 m (:func:`mask_grid`): el cuadrado de 100 m alineado con la rejilla
  y el desplazado media celda, con 8 m de resguardo hacia fuera; un punto en una esquina de celda
  y otro en un centro, con 8 m; una línea de 100 m sobre una línea de la rejilla, con 8 m; y el
  cuadrado alineado como límite con 10 m hacia dentro. Sus recuentos a mano (plan §2.2 y
  :data:`HAND_COUNTS`), con la regla de D-1 (una celda está en la zona si la distancia exacta de
  la geometría a la celda es < r − τ; dentro de un límite, si está entera dentro):

  - cuadrado alineado: n² + 4·n·k + 4·q (n celdas de lado, k = 8 m / paso celdas de banda y q
    las celdas de una esquina con (i² + j²)·paso² < 64): 10.000 + 3.200 + 224 = **13.424** con
    1 m; 2.500 + 800 + 60 = **3.360** con 2 m;
  - desplazado media celda (0,5 m con 1 m; 1 m con 2 m): 101² + 4·101·8 + 4·52 = **13.641**;
    51² + 4·51·4 + 4·13 = **3.469**;
  - punto en una esquina: los cuatro cuadrantes de una esquina, **224** y **60**; en un centro,
    **241** y **69**;
  - línea de 100 m: 100·16 + 2·112 = **1.824**; 50·8 + 2·30 = **460**;
  - límite con 10 m hacia dentro: entera dentro 10.000 y 2.500; la banda, 3.600 y 900; el
    núcleo, 80² = **6.400** y 40² = **1.600**.

- **El sitio** (:data:`SITE_GRID`, celdas de 2 m, 160 × 160): el límite legal «Concesión» (un
  cuadrado de 200 m, 4 ha) y el perímetro de actuación con un lóbulo fuera del límite
  (:func:`limits`): perímetro 34.400 m², intersección 27.600 m² y la franja perímetro ∖ límite
  de **0,68 ha** en una parte de centro conocido (CE-012-03; RF-012-05); el perímetro
  redibujado en QGIS con **+1,43 ha** ganadas y nada perdido (CE-012-04; RF-012-06), con su
  franja de dos partes. Polígonos de coordenadas enteras alineadas con las celdas: sus áreas son
  exactas y las celdas las reproducen.
- **Superficies del sitio** (:func:`tower_case`, :func:`pond_case`, :func:`strip_case`): la
  partida, un llano a :data:`START_Z`; la torre de CE-012-02 (un punto con 8 m en una esquina de
  celda, 60 celdas de 4 m²) y una final que rebaja 26,6 m su entorno: 60 · 4 · 26,6 m³ de corte
  en su zona, un grupo centrado en la torre; la que respeta la zona, 0 m³ en ella. La balsa
  «sin relleno» de CE-012-06 con un relleno de 5,375 m en 200 celdas: **4.300 m³**. Un corte y
  un relleno de 3 m en la franja (CE-012-03).
- **El GeoPackage de las fuentes** (:func:`write_sources`: ``fuentes/`` de la carpeta que se
  le da, fuera del proyecto, como la carpeta del cliente de ``tests.support.demo_project``):
  restricciones de los once tipos en polígonos y algunas en líneas y puntos, con sus campos (tipo
  en español, nombre, motivo, decisor y fecha); una capa de infraestructuras (``GEOMETRY``) con
  una torre a **6 m** del sector 2 y una línea eléctrica a **15 m** del sector 1; dos sectores sin
  solapes; y las marcas del cliente con su rol. Las distancias, a mano
  (:data:`TOWER_TO_SECTOR_M`, :data:`POWER_LINE_TO_SECTOR_M`). :func:`write_gpkg_layer` escribe
  cualquier otra capa (para las variantes de las pruebas).

Ningún dato de cliente: nombres, motivos, decisores y fechas son de prueba.
"""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from tests.support.package import import_geoblender

gis = import_geoblender("gis")
georef = import_geoblender("core.georef")

CATALOG = georef.load_catalog()
CRS = CATALOG.horizontal(25830)
"""El CRS de todos los casos (ETRS89 / UTM 30N)."""
VERTICAL = CATALOG.vertical(5782)
"""La referencia vertical de las superficies (Alicante)."""
SRS_ID = 25830

BASE: tuple[float, float] = (699_700.0, 4_399_700.0)
"""Esquina de las coordenadas locales de todos los casos (m, absoluta): a 200 m de la esquina
suroeste de la ventana sintética de ``core_fixtures`` (alineada con celdas de 1 y de 2 m)."""

TAU_M = 1e-9
"""τ de D-1 y D-37 (m): lo que solo toca dentro del redondeo no cuenta."""

# Tipos y roles ------------------------------------------------------------------------------

CONSTRAINT_TYPES: Mapping[str, str] = {
    "legal_limit": "Límite legal",
    "action_perimeter": "Perímetro de actuación",
    "untouchable": "Intocable",
    "exclusion": "Exclusión",
    "no_cut": "Sin corte",
    "fill_only": "Solo relleno",
    "restoration_only": "Solo restauración",
    "setback": "Banda de resguardo",
    "no_fill": "Sin relleno",
    "avoid": "Preferible no afectar",
    "requires_access": "Requiere acceso",
}
"""Los once tipos (D-16; plan §5.2.1): ``ctype`` → su nombre en la interfaz."""

INTENTION_ROLES: Mapping[str, str] = {
    "protect": "Proteger",
    "fill": "Rellenar",
    "mine_to_elevation": "Explotar a una cota",
    "keep_as_is": "Conservar como está",
    "platform": "Plataforma",
    "slope_to_treat": "Talud a tratar",
}
"""Los seis roles de una marca del cliente (RF-012-26; plan §5.2.1)."""


def absolute(points: Sequence[Sequence[float]]) -> np.ndarray:
    """Los puntos locales ``(x, y)`` (m desde :data:`BASE`) en coordenadas absolutas, float64
    ``(k, 2)``."""
    return np.asarray(points, dtype=np.float64).reshape(-1, 2) + np.asarray(BASE)


def rectangle(left: float, bottom: float, right: float, top: float) -> np.ndarray:
    """El anillo ABSOLUTO cerrado y antihorario del rectángulo local dado (m desde
    :data:`BASE`)."""
    return absolute([(left, bottom), (right, bottom), (right, top), (left, top),
                     (left, bottom)])


def ring_area(ring: np.ndarray) -> float:
    """Área con signo de un anillo cerrado (m², fórmula del polígono; > 0 si es antihorario),
    en coordenadas relativas a su primer vértice para no perder decimales."""
    local = np.asarray(ring, dtype=np.float64) - ring[0]
    x, y = local[:, 0], local[:, 1]
    return float(np.sum(x[:-1] * y[1:] - x[1:] * y[:-1]) / 2.0)


# CE-012-01: máscaras de referencia ---------------------------------------------------------

MASK_STEPS = (1.0, 2.0)
"""Los pasos de celda de CE-012-01 (m)."""
MASK_WINDOW_M = 140.0
"""Lado de la ventana de cada caso de CE-012-01 (m, desde :data:`BASE`)."""
MASK_OUTWARD_M = 8.0
"""Resguardo hacia fuera de los casos de CE-012-01 (m; valor de prueba, D-5)."""
MASK_INWARD_M = 10.0
"""Resguardo hacia dentro del límite de CE-012-01 (m; valor de prueba, D-5)."""

HAND_COUNTS: Mapping[float, Mapping[str, int]] = {
    1.0: {"square": 13_424, "square_shifted": 13_641, "point_corner": 224,
          "point_center": 241, "line": 1_824, "limit": 6_400},
    2.0: {"square": 3_360, "square_shifted": 3_469, "point_corner": 60,
          "point_center": 69, "line": 460, "limit": 1_600},
}
"""Recuentos a mano de CE-012-01 por paso (plan §2.2): celdas de la zona; del límite, las del
núcleo (enteras dentro, sin la banda hacia dentro)."""
LIMIT_INSIDE_CELLS: Mapping[float, int] = {1.0: 10_000, 2.0: 2_500}
"""Celdas enteras dentro del límite de CE-012-01 (con su banda)."""
LIMIT_BAND_CELLS: Mapping[float, int] = {1.0: 3_600, 2.0: 900}
"""Celdas de la banda hacia dentro del límite de CE-012-01 (10 m: 100² − 80², 50² − 40²)."""


@dataclass(frozen=True, slots=True, eq=False)
class MaskCase:
    """Un caso de CE-012-01: ``key`` (la de :data:`HAND_COUNTS`), su nombre, el tipo de
    geometría (``"POLYGON"``, ``"LINESTRING"`` o ``"POINT"``) y sus coordenadas ABSOLUTAS
    (polígono: tupla de anillos cerrados ``(k, 2)``; línea: ``(k, 2)``; punto: ``(2,)``), los
    resguardos hacia fuera y hacia dentro (m; ``None`` si no aplica), la rejilla, las celdas a
    mano (``cells``: la zona, o el núcleo de un límite), las enteras dentro y las de la banda (un
    límite; si no, ``None``) y el área exacta del polígono (m²; ``None`` en una línea o un
    punto). Los arrays no se modifican."""

    key: str
    name: str
    geometry_type: str
    coords: Any
    outward_m: float | None
    inward_m: float | None
    grid: Any
    cells: int
    inside_cells: int | None = None
    band_cells: int | None = None
    area_m2: float | None = None

    @property
    def step(self) -> float:
        """El paso de la rejilla (m)."""
        return float(self.grid.dx)

    @property
    def is_limit(self) -> bool:
        """Verdadero si es el límite con resguardo hacia dentro."""
        return self.inward_m is not None


def mask_grid(step: float) -> Any:
    """La rejilla de los casos de CE-012-01: :data:`MASK_WINDOW_M` m de lado desde
    :data:`BASE`, con celdas de ``step`` m."""
    cells = int(MASK_WINDOW_M / step)
    return gis.Grid(BASE[0], BASE[1] + MASK_WINDOW_M, step, step, cells, cells)


def mask_cases(step: float) -> tuple[MaskCase, ...]:
    """Los seis casos de CE-012-01 con celdas de ``step`` m (1 o 2), con sus recuentos a mano."""
    if step not in HAND_COUNTS:
        raise ValueError(f"CE-012-01 tiene recuentos a mano con 1 y 2 m, no con {step!r}")
    grid = mask_grid(step)
    counts = HAND_COUNTS[step]
    half = step / 2.0
    square = (rectangle(20.0, 20.0, 120.0, 120.0),)
    shifted = (rectangle(20.0 + half, 20.0 + half, 120.0 + half, 120.0 + half),)
    return (
        MaskCase("square", "Cuadrado de 100 m alineado", "POLYGON", square, MASK_OUTWARD_M,
                 None, grid, counts["square"], area_m2=10_000.0),
        MaskCase("square_shifted", "Cuadrado de 100 m desplazado media celda", "POLYGON",
                 shifted, MASK_OUTWARD_M, None, grid, counts["square_shifted"],
                 area_m2=10_000.0),
        MaskCase("point_corner", "Punto en una esquina de celda", "POINT",
                 absolute([(70.0, 70.0)])[0], MASK_OUTWARD_M, None, grid,
                 counts["point_corner"]),
        MaskCase("point_center", "Punto en el centro de una celda", "POINT",
                 absolute([(70.0 + half, 70.0 + half)])[0], MASK_OUTWARD_M, None, grid,
                 counts["point_center"]),
        MaskCase("line", "Línea de 100 m sobre una línea de la rejilla", "LINESTRING",
                 absolute([(20.0, 70.0), (120.0, 70.0)]), MASK_OUTWARD_M, None, grid,
                 counts["line"]),
        MaskCase("limit", "Límite con 10 m hacia dentro", "POLYGON", square, None,
                 MASK_INWARD_M, grid, counts["limit"], inside_cells=LIMIT_INSIDE_CELLS[step],
                 band_cells=LIMIT_BAND_CELLS[step], area_m2=10_000.0),
    )


# El sitio: límites (CE-012-03, CE-012-04) --------------------------------------------------

SITE_STEP_M = 2.0
SITE_GRID = gis.Grid(BASE[0] - 20.0, BASE[1] + 220.0, SITE_STEP_M, SITE_STEP_M, 160, 160)
"""La rejilla del sitio: de (−20, −100) a (300, 220) locales, celdas de 2 m (160 × 160)."""

LEGAL_LIMIT_LOCAL = ((0.0, 0.0), (200.0, 0.0), (200.0, 200.0), (0.0, 200.0), (0.0, 0.0))
PERIMETER_LOCAL = ((20.0, 20.0), (180.0, 20.0), (180.0, 50.0), (268.0, 50.0), (268.0, 150.0),
                   (180.0, 150.0), (180.0, 180.0), (20.0, 180.0), (20.0, 20.0))
REDRAWN_PERIMETER_LOCAL = ((20.0, -90.0), (150.0, -90.0), (150.0, 20.0), (180.0, 20.0),
                           (180.0, 50.0), (268.0, 50.0), (268.0, 150.0), (180.0, 150.0),
                           (180.0, 180.0), (20.0, 180.0), (20.0, -90.0))


@dataclass(frozen=True, slots=True, eq=False)
class StripPart:
    """Una parte de la franja perímetro ∖ límite legal: su anillo ABSOLUTO, su área (m²) y su
    centro absoluto (el de su área)."""

    ring: np.ndarray
    area_m2: float
    center: tuple[float, float]


@dataclass(frozen=True, slots=True, eq=False)
class LimitsCase:
    """El límite legal y el perímetro del sitio (anillos ABSOLUTOS cerrados y antihorarios) con
    sus áreas a mano (m²): la del límite, la del perímetro, la de su intersección y la franja con
    sus partes (CE-012-03); el perímetro redibujado con su área, lo ganado y lo perdido frente al
    primero (m²) y su franja (CE-012-04)."""

    legal_limit: np.ndarray
    perimeter: np.ndarray
    redrawn_perimeter: np.ndarray
    legal_area_m2: float
    perimeter_area_m2: float
    intersection_m2: float
    strip_m2: float
    strip_parts: tuple[StripPart, ...]
    redrawn_area_m2: float
    gained_m2: float
    lost_m2: float
    redrawn_strip_m2: float
    redrawn_strip_parts: tuple[StripPart, ...]


def _part(left: float, bottom: float, right: float, top: float) -> StripPart:
    area = (right - left) * (top - bottom)
    center = (BASE[0] + (left + right) / 2.0, BASE[1] + (bottom + top) / 2.0)
    return StripPart(rectangle(left, bottom, right, top), area, center)


def limits() -> LimitsCase:
    """Los límites del sitio: «Concesión» (200 × 200 m, 40.000 m²) y el perímetro (el cuadrado
    de 160 m de (20, 20) a (180, 180), 25.600 m², más un lóbulo de 88 × 100 m hacia el este,
    8.800 m²: 34.400 m²). La intersección, 25.600 + 20 · 100 = 27.600 m²; la franja, el
    rectángulo de (200, 50) a (268, 150): 68 · 100 = **6.800 m² = 0,68 ha** de centro (234, 100)
    (CE-012-03). Redibujado: más el rectángulo de (20, −90) a (150, 20), 130 · 110 = **14.300
    m² = 1,43 ha** ganadas, 0 perdidas (48.700 m²; CE-012-04); su franja suma la parte de (20,
    −90) a (150, 0), 11.700 m² de centro (85, −45): 18.500 m²."""
    strip = _part(200.0, 50.0, 268.0, 150.0)
    south = _part(20.0, -90.0, 150.0, 0.0)
    return LimitsCase(
        legal_limit=absolute(LEGAL_LIMIT_LOCAL),
        perimeter=absolute(PERIMETER_LOCAL),
        redrawn_perimeter=absolute(REDRAWN_PERIMETER_LOCAL),
        legal_area_m2=40_000.0,
        perimeter_area_m2=34_400.0,
        intersection_m2=27_600.0,
        strip_m2=6_800.0,
        strip_parts=(strip,),
        redrawn_area_m2=48_700.0,
        gained_m2=14_300.0,
        lost_m2=0.0,
        redrawn_strip_m2=18_500.0,
        redrawn_strip_parts=(strip, south),
    )


# Superficies del sitio (CE-012-02, CE-012-03, CE-012-06) ----------------------------------

START_Z = 650.0
"""Cota de la superficie de partida del sitio, llana (m)."""
TOWER_LOCAL = (186.0, 100.0)
"""La torre (local): una esquina de celda de 2 m, a 6 m del sector 2 y dentro del perímetro."""
TOWER_OUTWARD_M = 8.0
"""Resguardo de la torre como intocable (m; valor de prueba, D-5)."""
TOWER_ZONE_CELLS = 60
"""Celdas de 2 m de la zona de la torre con 8 m: las de un punto en una esquina (CE-012-01)."""
TOWER_DROP_M = 26.6
"""Lo que la final de CE-012-02 rebaja el entorno de la torre (m)."""
POND_LOCAL = (60.0, 80.0, 120.0, 130.0)
"""La balsa «sin relleno» (local: izquierda, abajo, derecha, arriba): 60 × 50 m."""
POND_FILL_M = 5.375
"""El relleno sintético en la balsa (m; exacto en binario)."""
POND_FILL_LOCAL = (70.0, 90.0, 110.0, 110.0)
"""Dónde rellena (local): 40 × 20 m = 200 celdas de 4 m²: 800 · 5,375 = 4.300 m³."""
STRIP_THICKNESS_M = 3.0
"""El corte o el relleno en la franja de CE-012-03 (m)."""
STRIP_MOVE_LOCAL = (210.0, 80.0, 250.0, 120.0)
"""Dónde corta o rellena en la franja (local): 40 × 40 m = 400 celdas: 4.800 m³."""


@dataclass(frozen=True, slots=True, eq=False)
class ComplianceCase:
    """Una verificación de referencia en :data:`SITE_GRID`: la partida y la final (``Raster``,
    float64), la geometría de la zona (``zone_type`` y ``zone_coords``, ABSOLUTAS, como
    :class:`MaskCase`) con su resguardo hacia fuera (m) y sus celdas a mano, y lo que se espera en
    ella: corte y relleno (m³) y, si incumple, un solo grupo con sus celdas, su área (m²), su
    volumen (m³), su espesor máximo (m) y su centro absoluto; ``None`` si no hay grupo."""

    name: str
    start: Any
    final: Any
    zone_type: str
    zone_coords: Any
    zone_outward_m: float
    zone_cells: int
    cut_m3: float
    fill_m3: float
    group_cells: int | None
    group_area_m2: float | None
    group_volume_m3: float | None
    group_max_m: float | None
    group_center: tuple[float, float] | None


def site_centers() -> tuple[np.ndarray, np.ndarray]:
    """Las coordenadas LOCALES (m desde :data:`BASE`) de los centros de celda de
    :data:`SITE_GRID`, de forma ``grid.shape`` (fila 0 al norte)."""
    grid = SITE_GRID
    columns = (np.arange(grid.ncols) + 0.5) * grid.dx + (grid.west - BASE[0])
    rows = (grid.north - BASE[1]) - (np.arange(grid.nrows) + 0.5) * grid.dy
    return np.meshgrid(columns, rows)


def _in_rectangle(box: tuple[float, float, float, float]) -> np.ndarray:
    x, y = site_centers()
    left, bottom, right, top = box
    return (x > left) & (x < right) & (y > bottom) & (y < top)


def _site_raster(values: np.ndarray) -> Any:
    return gis.Raster(SITE_GRID, values, CRS, VERTICAL)


def site_start() -> Any:
    """La superficie de partida del sitio: el llano a :data:`START_Z`."""
    return _site_raster(np.full(SITE_GRID.shape, START_Z, dtype=np.float64))


def tower_case(*, respectful: bool = False) -> ComplianceCase:
    """CE-012-02: la torre con 8 m (60 celdas) y una final que rebaja 26,6 m el cuadrado local
    de (172, 86) a (200, 114) (14 × 14 = 196 celdas), toda la zona: corte 60 · 4 · 26,6 =
    6.384 m³, un grupo de 240 m² centrado en la torre. Con ``respectful``, la final no toca el
    cuadrado de (178, 92) a (194, 108) (64 celdas, que contiene la zona): 0 m³ en ella."""
    drop = _in_rectangle((172.0, 86.0, 200.0, 114.0))
    if respectful:
        drop &= ~_in_rectangle((178.0, 92.0, 194.0, 108.0))
    final = np.where(drop, START_Z - TOWER_DROP_M, START_Z)
    area = TOWER_ZONE_CELLS * SITE_GRID.cell_area
    tower = absolute([TOWER_LOCAL])[0]
    return ComplianceCase(
        name="Torre respetada" if respectful else "Torre rebajada 26,6 m",
        start=site_start(), final=_site_raster(final), zone_type="POINT", zone_coords=tower,
        zone_outward_m=TOWER_OUTWARD_M, zone_cells=TOWER_ZONE_CELLS,
        cut_m3=0.0 if respectful else area * TOWER_DROP_M, fill_m3=0.0,
        group_cells=None if respectful else TOWER_ZONE_CELLS,
        group_area_m2=None if respectful else area,
        group_volume_m3=None if respectful else area * TOWER_DROP_M,
        group_max_m=None if respectful else TOWER_DROP_M,
        group_center=None if respectful else (float(tower[0]), float(tower[1])),
    )


def pond_case() -> ComplianceCase:
    """CE-012-06: la balsa «sin relleno» (sin resguardo: 750 celdas) con 5,375 m de relleno en
    200 celdas: 4.300 m³, un grupo de 800 m² de centro (90, 100) local."""
    fill = _in_rectangle(POND_FILL_LOCAL)
    final = np.where(fill, START_Z + POND_FILL_M, START_Z)
    left, bottom, right, top = POND_FILL_LOCAL
    cells = int(((right - left) / SITE_STEP_M) * ((top - bottom) / SITE_STEP_M))
    area = cells * SITE_GRID.cell_area
    return ComplianceCase(
        name="Balsa rellenada", start=site_start(), final=_site_raster(final),
        zone_type="POLYGON", zone_coords=(rectangle(*POND_LOCAL),), zone_outward_m=0.0,
        zone_cells=750, cut_m3=0.0, fill_m3=4_300.0, group_cells=cells, group_area_m2=area,
        group_volume_m3=4_300.0, group_max_m=POND_FILL_M,
        group_center=(BASE[0] + (left + right) / 2.0, BASE[1] + (bottom + top) / 2.0),
    )


def strip_case(*, fill: bool = False) -> ComplianceCase:
    """CE-012-03: 3 m de corte (o de relleno, con ``fill``) en 400 celdas de la franja (fuera del
    límite legal, dentro del perímetro): 4.800 m³. Su «zona» es la franja (34 × 50 celdas): el
    corte no cumple (fuera del límite legal); el relleno, sí (sin grupo)."""
    move = _in_rectangle(STRIP_MOVE_LOCAL)
    sign = 1.0 if fill else -1.0
    final = np.where(move, START_Z + sign * STRIP_THICKNESS_M, START_Z)
    volume = 400 * SITE_GRID.cell_area * STRIP_THICKNESS_M
    left, bottom, right, top = STRIP_MOVE_LOCAL
    return ComplianceCase(
        name="Relleno en la franja" if fill else "Corte en la franja",
        start=site_start(), final=_site_raster(final), zone_type="POLYGON",
        zone_coords=(limits().strip_parts[0].ring,), zone_outward_m=0.0, zone_cells=34 * 50,
        cut_m3=0.0 if fill else volume, fill_m3=volume if fill else 0.0,
        group_cells=None if fill else 400,
        group_area_m2=None if fill else 400 * SITE_GRID.cell_area,
        group_volume_m3=None if fill else volume,
        group_max_m=None if fill else STRIP_THICKNESS_M,
        group_center=None if fill else (BASE[0] + (left + right) / 2.0,
                                        BASE[1] + (bottom + top) / 2.0),
    )


# El GeoPackage de las fuentes ---------------------------------------------------------------

SOURCES_DIR = "fuentes"
SOURCES_FILE = "Restricciones_sinteticas.gpkg"
LAYER_POLYGONS = "restricciones_poligonos"
LAYER_LINES = "restricciones_lineas"
LAYER_POINTS = "restricciones_puntos"
LAYER_INFRASTRUCTURE = "infraestructuras"
LAYER_SECTORS = "sectores"
LAYER_MARKS = "marcas_cliente"

CONSTRAINT_FIELDS: tuple[tuple[str, str], ...] = (
    ("tipo", "TEXT"), ("nombre", "TEXT"), ("motivo", "TEXT"), ("decisor", "TEXT"),
    ("fecha", "DATE"))
INFRASTRUCTURE_FIELDS: tuple[tuple[str, str], ...] = (("nombre", "TEXT"), ("clase", "TEXT"))
SECTOR_FIELD = "sector"
SECTOR_FIELDS: tuple[tuple[str, str], ...] = ((SECTOR_FIELD, "TEXT"),)
MARK_FIELDS: tuple[tuple[str, str], ...] = (
    ("rol", "TEXT"), ("nombre", "TEXT"), ("cota", "REAL"), ("fecha", "DATE"))

SECTORS_LOCAL: Mapping[str, tuple[float, float, float, float]] = {
    "Sector 1": (20.0, 20.0, 90.0, 180.0),
    "Sector 2": (110.0, 20.0, 180.0, 180.0),
}
"""Los dos sectores (local: izquierda, abajo, derecha, arriba), sin solapes y dentro del
perímetro: 11.200 m² cada uno."""
SECTORS_UNCOVERED_M2 = 12_000.0
"""Área del perímetro que no cubre ningún sector (RF-012-07): 34.400 − 2 · 11.200 m²."""
POWER_LINE_LOCAL = ((-40.0, 195.0), (80.0, 195.0))
"""La línea eléctrica (local): 15 m al norte del sector 1."""
SEARCH_DISTANCE_M = 25.0
"""La distancia de búsqueda de intocables (m): la ADOPTADA «sin confirmar» de D-5."""
TOWER_TO_SECTOR_M: Mapping[str, float] = {"Sector 1": 96.0, "Sector 2": 6.0}
"""Distancia de la torre a cada sector (m, a mano): 186 − 90 y 186 − 180."""
POWER_LINE_TO_SECTOR_M: Mapping[str, float] = {"Sector 1": 15.0, "Sector 2": math.sqrt(1_125.0)}
"""Distancia de la línea eléctrica a cada sector (m, a mano): 195 − 180, y del extremo (80, 195)
a la esquina (110, 180) del sector 2, √(30² + 15²) = 33,541 m."""
MINE_ELEVATION_M = 612.5
"""La cota de la marca «explotar a una cota» (m)."""


@dataclass(frozen=True, slots=True, eq=False)
class SourceFeature:
    """Una entidad de una capa de las fuentes: su número, su tipo de geometría (``POINT``,
    ``LINESTRING`` o ``POLYGON``), sus coordenadas ABSOLUTAS (como las de ``encode_geometry``)
    y sus atributos (campo → valor)."""

    fid: int
    geometry_type: str
    coords: Any
    attributes: Mapping[str, Any]


def _constraint(fid: int, kind: str, coords: Any, ctype: str, name: str, reason: str,
                decided_by: str, decided_on: str) -> SourceFeature:
    return SourceFeature(fid, kind, coords, {
        "tipo": CONSTRAINT_TYPES[ctype], "nombre": name, "motivo": reason,
        "decisor": decided_by, "fecha": decided_on})


def _box(left: float, bottom: float, right: float, top: float) -> tuple[np.ndarray, ...]:
    return (rectangle(left, bottom, right, top),)


def source_features() -> dict[str, tuple[SourceFeature, ...]]:
    """Las entidades de cada capa de :func:`write_sources` (capa → entidades): los once tipos
    en polígonos (el límite y el perímetro de :func:`limits`, la balsa de :func:`pond_case` y
    rectángulos de 20 m), tres líneas y tres puntos; la torre y la línea eléctrica; los dos
    sectores; y las seis marcas del cliente, una por rol."""
    lim = limits()
    polygons = (
        _constraint(1, "POLYGON", (lim.legal_limit,), "legal_limit", "Concesión",
                    "Concesión de explotación sintética", "Autoridad minera", "2024-03-15"),
        _constraint(2, "POLYGON", (lim.perimeter,), "action_perimeter", "Perímetro",
                    "Autorización de explotación", "Dirección facultativa", "2025-06-01"),
        _constraint(3, "POLYGON", _box(30.0, 150.0, 50.0, 170.0), "untouchable", "Cementerio",
                    "Protección sanitaria", "Ayuntamiento", "2025-01-20"),
        _constraint(4, "POLYGON", _box(60.0, 150.0, 80.0, 170.0), "exclusion", "Yacimiento",
                    "Patrimonio arqueológico", "Consejería de cultura", "2025-02-11"),
        _constraint(5, "POLYGON", _box(130.0, 150.0, 150.0, 170.0), "no_cut", "Ladera",
                    "Estabilidad de la ladera", "Dirección facultativa", "2025-03-04"),
        _constraint(6, "POLYGON", _box(30.0, 30.0, 50.0, 50.0), "fill_only", "Vaguada",
                    "Relleno previsto en la restauración", "Propiedad", "2025-03-18"),
        _constraint(7, "POLYGON", _box(60.0, 30.0, 80.0, 50.0), "restoration_only",
                    "Escombrera antigua", "Plan de restauración", "Consejería de medio ambiente",
                    "2025-04-02"),
        _constraint(8, "POLYGON", _box(130.0, 30.0, 150.0, 50.0), "setback", "Borde de camino",
                    "Servidumbre de paso", "Ayuntamiento", "2025-04-15"),
        _constraint(9, "POLYGON", (rectangle(*POND_LOCAL),), "no_fill", "Balsa",
                    "Balsa de decantación en uso", "Dirección facultativa", "2025-05-06"),
        _constraint(10, "POLYGON", _box(136.0, 60.0, 166.0, 80.0), "avoid", "Encinar",
                    "Arbolado de interés", "Propiedad", "2025-05-20"),
        _constraint(11, "POLYGON", _box(20.0, 90.0, 40.0, 110.0), "requires_access",
                    "Finca vecina", "Acceso a la finca colindante", "Propiedad", "2025-06-10"),
    )
    lines = (
        _constraint(1, "LINESTRING", absolute([(100.0, 20.0), (100.0, 180.0)]), "untouchable",
                    "Acequia", "Riego de las fincas", "Comunidad de regantes", "2025-02-25"),
        _constraint(2, "LINESTRING", absolute([(20.0, 140.0), (90.0, 140.0)]), "no_fill",
                    "Cauce", "Dominio público hidráulico", "Confederación hidrográfica",
                    "2025-03-11"),
        _constraint(3, "LINESTRING", absolute([(110.0, 140.0), (180.0, 140.0)]), "setback",
                    "Camino", "Servidumbre de paso", "Ayuntamiento", "2025-04-15"),
    )
    points = (
        _constraint(1, "POINT", absolute([(40.0, 120.0)])[0], "untouchable", "Pozo",
                    "Abastecimiento", "Ayuntamiento", "2025-01-27"),
        _constraint(2, "POINT", absolute([(150.0, 120.0)])[0], "avoid", "Árbol singular",
                    "Catálogo de árboles", "Consejería de medio ambiente", "2025-05-20"),
        _constraint(3, "POINT", absolute([(160.0, 170.0)])[0], "exclusion",
                    "Vértice geodésico", "Red geodésica", "Instituto geográfico", "2025-02-03"),
    )
    infrastructure = (
        SourceFeature(1, "POINT", absolute([TOWER_LOCAL])[0],
                      {"nombre": "Torre 14", "clase": "Torre eléctrica"}),
        SourceFeature(2, "LINESTRING", absolute(POWER_LINE_LOCAL),
                      {"nombre": "Línea de 20 kV", "clase": "Línea eléctrica"}),
    )
    sectors = tuple(
        SourceFeature(fid, "POLYGON", _box(*box), {SECTOR_FIELD: name})
        for fid, (name, box) in enumerate(SECTORS_LOCAL.items(), start=1))
    marks = (
        _mark(1, "POINT", absolute([(120.0, 165.0)])[0], "protect", "Ermita"),
        _mark(2, "POLYGON", _box(30.0, 60.0, 50.0, 80.0), "fill", "Hondonada"),
        _mark(3, "POLYGON", _box(140.0, 90.0, 170.0, 110.0), "mine_to_elevation",
              "Plaza de cantera", MINE_ELEVATION_M),
        _mark(4, "LINESTRING", absolute([(60.0, 60.0), (90.0, 60.0)]), "keep_as_is",
              "Muro de piedra"),
        _mark(5, "POLYGON", _box(200.0, 160.0, 240.0, 190.0), "platform",
              "Plataforma de acopio"),
        _mark(6, "LINESTRING", absolute([(20.0, 178.0), (180.0, 178.0)]), "slope_to_treat",
              "Talud norte"),
    )
    return {LAYER_POLYGONS: polygons, LAYER_LINES: lines, LAYER_POINTS: points,
            LAYER_INFRASTRUCTURE: infrastructure, LAYER_SECTORS: sectors, LAYER_MARKS: marks}


def _mark(fid: int, kind: str, coords: Any, role: str, name: str,
          elevation: float | None = None) -> SourceFeature:
    return SourceFeature(fid, kind, coords, {"rol": INTENTION_ROLES[role], "nombre": name,
                                             "cota": elevation, "fecha": "2025-09-12"})


LAYER_SPECS: Mapping[str, tuple[str, tuple[tuple[str, str], ...]]] = {
    LAYER_POLYGONS: ("POLYGON", CONSTRAINT_FIELDS),
    LAYER_LINES: ("LINESTRING", CONSTRAINT_FIELDS),
    LAYER_POINTS: ("POINT", CONSTRAINT_FIELDS),
    LAYER_INFRASTRUCTURE: ("GEOMETRY", INFRASTRUCTURE_FIELDS),
    LAYER_SECTORS: ("POLYGON", SECTOR_FIELDS),
    LAYER_MARKS: ("GEOMETRY", MARK_FIELDS),
}
"""Cada capa de las fuentes: su tipo de geometría en ``gpkg_geometry_columns`` y sus campos."""


def write_gpkg_layer(path: Path, layer: str, geometry_type: str,
                     fields: Sequence[tuple[str, str]],
                     features: Sequence[SourceFeature]) -> None:
    """Añade al GeoPackage ``path`` (lo crea, con EPSG:25830, si no existe) la capa ``layer``
    como las de QGIS: ``fid`` entero, ``geom`` de tipo ``geometry_type`` (2D) y los campos
    ``fields`` (nombre, tipo SQL), con las entidades ``features``."""
    base = import_geoblender("core.gpkg.base")
    wkb = import_geoblender("core.gpkg.wkb")
    path = Path(path)
    new = not path.exists()
    conn = sqlite3.connect(path)
    try:
        if new:
            base.create_base(conn, CRS)
        columns = "".join(f', "{name}" {kind}' for name, kind in fields)
        conn.execute(f'CREATE TABLE "{layer}" (fid INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, '
                     f'geom {geometry_type}{columns})')
        conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, "
                     "description, srs_id) VALUES (?, 'features', ?, '', ?)",
                     (layer, layer, SRS_ID))
        conn.execute("INSERT INTO gpkg_geometry_columns VALUES (?, 'geom', ?, ?, 0, 0)",
                     (layer, geometry_type, SRS_ID))
        marks = ", ".join("?" * (len(fields) + 2))
        for feature in features:
            blob = wkb.encode_geometry(feature.geometry_type, feature.coords, SRS_ID, False)
            values = [feature.attributes.get(name) for name, _kind in fields]
            conn.execute(f'INSERT INTO "{layer}" VALUES ({marks})',
                         (feature.fid, blob, *values))
        conn.commit()
    finally:
        conn.close()


def write_sources(folder: Path) -> Path:
    """Escribe el GeoPackage de las fuentes en ``folder/fuentes/`` (fuera del proyecto) con las
    capas de :data:`LAYER_SPECS` y las entidades de :func:`source_features`; devuelve su ruta.
    Si ya existe, ``FileExistsError``: cada prueba escribe el suyo."""
    target = Path(folder) / SOURCES_DIR
    target.mkdir(parents=True, exist_ok=True)
    path = target / SOURCES_FILE
    if path.exists():
        raise FileExistsError(f"«{path.name}» ya existe: las fuentes se escriben una vez")
    features = source_features()
    for layer, (geometry_type, fields) in LAYER_SPECS.items():
        write_gpkg_layer(path, layer, geometry_type, fields, features[layer])
    return path
