# SPDX-License-Identifier: GPL-3.0-or-later
"""Los datos puros de los acopios, el contrafuerte y los cuerpos apoyados a escala (spec 016, T01 y T37; plan 016 §7.1 y §7.3):
solo numpy y la biblioteca estándar, sin cargar ``geoblender``.

Los usan a la vez las pruebas de rendimiento con el Python de Blender (``tests/support/stockpile_perf.py``, que los convierte a las
clases de su copia del paquete, ``import_geoblender``) y las de dentro de Blender
(``tests/rendimiento/blender/perf_stockpiles.py``, que los convierte a las clases de la extensión habilitada: allí no se puede
cargar otra copia del paquete, ``docs/trampas.md`` §4); y ``tests/support/stockpile_data.py`` (T01) los reexporta: **una sola
fuente** para los montones (:class:`Mound`, :func:`mound_heights`) y la escala (``scale_*``).

- **Los montones** (:class:`Mound`, :func:`mound_heights`): troncos de pirámide y de cono de forma conocida.
- **La escala de T01** (:func:`scale_mounds`, :func:`scale_thickness`, :func:`scale_survey`): las 100 marcas, las 2.000 zonas
  candidatas y los 10.000 datos de espesor sueltos de la rejilla de 1.654 × 1.699 celdas de 1 m (2,81 M).
- **Lo que añade T37**: el levantamiento de **9 acopios de 38.000 m²** (:func:`nine_mounds`), las zonas de coronación de 2 y 10 ha
  (:data:`BUTTRESS_ZONES`, :func:`crown_level`), las huellas de los cuerpos (:data:`BODY_BOXES`), las marcas de escala
  (:data:`MARK_HALF_M`) y las secciones diagonales a 45° de las huellas de 20 y 100 ha (:func:`section_lines`).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from tests.support import constraints_data as cdata
from tests.support import design_data as ddata

SHAPES: tuple[str, ...] = ("pyramid", "cone")
"""Las formas de un montón: tronco de pirámide (la distancia es la de Chebyshev) o de cono (la euclídea)."""


@dataclass(frozen=True, slots=True)
class Mound:
    """Un tronco de pirámide o de cono: su ``name``, su ``shape``, el centro ``(cx, cy)`` (local, en un metro
    entero: una esquina de celda), el semilado o radio del pie ``foot`` y de la cima ``top`` (m) y su altura
    ``height`` (m) **sobre el plano**. La altura baja linealmente de ``height`` en la cima a 0 en el pie."""

    name: str
    shape: str
    cx: float
    cy: float
    foot: float
    top: float
    height: float

    def __post_init__(self) -> None:
        if self.shape not in SHAPES:
            raise ValueError(f"la forma de un montón es una de {', '.join(SHAPES)}, no {self.shape!r}")
        if not (0.0 <= self.top < self.foot and self.height > 0.0):
            raise ValueError(f"el montón «{self.name}» pide 0 ≤ cima < pie y una altura positiva")

    @property
    def slope(self) -> float:
        """La pendiente de la ladera del montón (m/m)."""
        return self.height / (self.foot - self.top)

    @property
    def foot_box(self) -> tuple[float, float, float, float]:
        """La caja del pie (local: izquierda, abajo, derecha, arriba)."""
        return (self.cx - self.foot, self.cy - self.foot, self.cx + self.foot, self.cy + self.foot)

    def moved(self, dx: float, dy: float) -> Mound:
        """El mismo montón con el centro trasladado ``(dx, dy)`` m."""
        return replace(self, cx=self.cx + dx, cy=self.cy + dy)

    def heights(self, x: Any, y: Any) -> np.ndarray:
        """La altura (m, ≥ 0) sobre el plano en ``(x, y)`` locales: ``mín(height, pendiente·(pie − d))``, 0 fuera
        del pie, con ``d`` la distancia de Chebyshev (pirámide) o euclídea (cono) al centro."""
        dx, dy = np.abs(np.asarray(x) - self.cx), np.abs(np.asarray(y) - self.cy)
        distance = np.maximum(dx, dy) if self.shape == "pyramid" else np.hypot(dx, dy)
        return np.clip(self.slope * (self.foot - distance), 0.0, self.height)


def mound_heights(shape: tuple[int, int], step_m: float, mounds: Sequence[Mound]) -> np.ndarray:
    """La altura de ``mounds`` sobre el plano en una rejilla de ``shape`` celdas de ``step_m`` m con el origen
    local en su esquina suroeste (m, float64, nueva): donde dos se solapan, la mayor (un montón no suma a otro).
    Evalúa cada montón solo en la caja de su pie."""
    nrows, ncols = shape
    found = np.zeros(shape, dtype=np.float64)
    for mound in mounds:
        left, bottom, right, top = mound.foot_box
        col0, col1 = max(math.floor(left / step_m), 0), min(math.ceil(right / step_m), ncols)
        row0, row1 = max(nrows - math.ceil(top / step_m), 0), min(nrows - math.floor(bottom / step_m), nrows)
        if col0 >= col1 or row0 >= row1:
            continue
        x = (np.arange(col0, col1) + 0.5) * step_m
        y = (nrows - np.arange(row0, row1) - 0.5) * step_m
        part = mound.heights(*np.meshgrid(x, y))
        found[row0:row1, col0:col1] = np.maximum(found[row0:row1, col0:col1], part)
    return found


# --- La escala de T01 (plan §7.1) ---------------------------------------------------------------------------

SCALE_WEST, SCALE_SOUTH = cdata.WEST, cdata.SOUTH
"""La esquina suroeste de la rejilla de escala (m, absoluta): la de la 012 y la 013."""
SCALE_MARKS, SCALE_BUMPS, SCALE_THICKNESS = 100, 2_000, 10_000
"""100 marcas, 2.000 zonas candidatas antes de filtrar y 10.000 datos de espesor."""
SCALE_SEED = 20_261_118
_SCALE_SITES = 46


def _pyramid(name: str, cx: float, cy: float, foot: float, top: float, height: float) -> Mound:
    return Mound(name, "pyramid", cx, cy, foot, top, height)


def scale_mounds() -> tuple[tuple[Mound, ...], tuple[Mound, ...]]:
    """Las 100 marcas (troncos de pirámide de pie 13 m, cima 3 m y 5 m de altura) y las 2.000 zonas candidatas antes
    de filtrar (pie de 6 a 12 m, cima 1 m, de 2,5 a 6 m de altura) de la rejilla de escala, en coordenadas locales
    desde su esquina suroeste: sobre una malla de 46 × 46 sitios (a ≈ 36 m) con una sacudida de ±1 m, separados al
    menos 5 m. Los mismos cada vez (semilla fija)."""
    rng = np.random.default_rng(SCALE_SEED)
    columns = (np.arange(_SCALE_SITES) + 0.5) * (cdata.COLS / _SCALE_SITES)
    rows = (np.arange(_SCALE_SITES) + 0.5) * (cdata.ROWS / _SCALE_SITES)
    sites = np.array([(x, y) for y in rows for x in columns])
    centres = np.round(sites) + rng.integers(-1, 2, size=sites.shape)
    order = rng.permutation(len(sites))
    feet = rng.integers(6, 13, size=SCALE_BUMPS)
    heights = rng.integers(5, 13, size=SCALE_BUMPS) * 0.5
    marks = tuple(_pyramid(f"Marca {number + 1:03d}", *map(float, centres[site]), 13.0, 3.0, 5.0)
                  for number, site in enumerate(order[:SCALE_MARKS]))
    bumps = tuple(_pyramid(f"Montículo {number + 1:04d}", *map(float, centres[site]), float(feet[number]),
                           1.0, float(heights[number]))
                  for number, site in enumerate(order[SCALE_MARKS:SCALE_MARKS + SCALE_BUMPS]))
    return marks, bumps


def scale_thickness() -> np.ndarray:
    """Los 10.000 datos de espesor sueltos (``(10000, 3)``: X e Y absolutas y el espesor, de 0,5 a 3 m) en 100 ha: un
    cuadrado de 1.000 m (de (300, 350) a (1.300, 1.350) locales de la rejilla de escala), a lo sumo uno por celda
    de 1 m. Los mismos cada vez (semilla fija)."""
    rng = np.random.default_rng(SCALE_SEED + 1)
    cells = rng.choice(1_000_000, size=SCALE_THICKNESS, replace=False)
    column, row = cells % 1_000, cells // 1_000
    x = 300.0 + column + 0.5 + rng.uniform(-0.4, 0.4, SCALE_THICKNESS)
    y = 350.0 + row + 0.5 + rng.uniform(-0.4, 0.4, SCALE_THICKNESS)
    return np.column_stack([SCALE_WEST + x, SCALE_SOUTH + y, rng.uniform(0.5, 3.0, SCALE_THICKNESS)])


def scale_survey() -> np.ndarray:
    """**Bajo demanda** (pesa 22 MB y casi un segundo): el levantamiento de escala (``(1699, 1654)``, m, nuevo): el
    terreno de la 013 (``design_data.terrain``, de 145 a 215 m con colinas) más las 100 marcas y las 2.000 zonas
    candidatas de :func:`scale_mounds`."""
    marks, bumps = scale_mounds()
    terrain = np.array(ddata.terrain(), dtype=np.float64)
    return terrain + mound_heights(terrain.shape, cdata.STEP_M, (*marks, *bumps))


# --- Lo que añade T37 ----------------------------------------------------------------------------------------

MARK_HALF_M = 15.0
"""El semilado de la marca de cada acopio de escala (m): 13 del pie más 2."""
MATERIALS: tuple[str, ...] = ("mineral", "estéril")
"""Los materiales de las marcas de escala, alternos (campo ``material``)."""
NINE_FOOT_M, NINE_TOP_M, NINE_HEIGHT_M = 32.5, 8.0, 10.0
"""El semilado del pie, el de la cima y la altura de cada uno de los nueve acopios de RNF-016-07 (m): 65 × 65 = 4.225 m² cada uno,
38.025 en total."""
NINE_MARGIN_M = 3.0
"""Lo que la marca de cada uno de los nueve sobresale de su pie (m)."""
NINE_CENTRES_M: tuple[tuple[float, float], ...] = tuple(
    (300.0 + 220.0 * column, 400.0 + 220.0 * row) for row in range(3) for column in range(3))
"""Los centros de los nueve (locales): una malla de 3 × 3 a 220 m."""


def nine_mounds() -> tuple[Mound, ...]:
    """Los nueve acopios grandes del levantamiento de RNF-016-07: pirámides de :data:`NINE_FOOT_M` m de semilado."""
    return tuple(Mound(f"Acopio {number}", "pyramid", cx, cy, NINE_FOOT_M, NINE_TOP_M, NINE_HEIGHT_M)
                 for number, (cx, cy) in enumerate(NINE_CENTRES_M, start=1))


def scale_terrain() -> np.ndarray:
    """El terreno de la 013 de la rejilla de escala (``(1699, 1654)``, m, float64, nuevo): sin acopios."""
    return np.array(ddata.terrain(), dtype=np.float64)


def survey_nine() -> np.ndarray:
    """El terreno con los nueve acopios grandes (m, float64, nuevo)."""
    terrain = scale_terrain()
    return terrain + mound_heights(terrain.shape, cdata.STEP_M, nine_mounds())


# Las zonas de coronación (locales: izquierda, abajo, derecha, arriba) y cuánto queda su cota por encima del terreno de la zona.
BUTTRESS_ZONES: dict[str, tuple[tuple[float, float, float, float], float]] = {
    "Zona de 2 ha": ((100.0, 100.0, 300.0, 200.0), 12.0),
    "Zona de 10 ha": ((1_150.0, 200.0, 1_550.0, 450.0), 20.0),
}
"""Las dos zonas de coronación de ``plan.md`` §7.3: 2 ha (+12 m) y 10 ha (+20 m)."""
BODY_BOXES: dict[str, tuple[float, float, float, float]] = {
    "Cuerpo de 1 ha": (300.0, 350.0, 400.0, 450.0),
    "Cuerpo de 18 ha": (300.0, 350.0, 700.0, 800.0),
    "Cuerpo de 20 ha": (300.0, 350.0, 700.0, 850.0),
    "Cuerpo de 100 ha": (300.0, 350.0, 1_300.0, 1_350.0),
}
"""Las huellas de los cuerpos (locales; a 1 m las celdas son los m²): 1, 18 (400 × 450), 20 (400 × 500) y 100 ha (1.000 × 1.000),
con la esquina suroeste común, que contienen los datos sueltos de :func:`scale_thickness`."""
PROFILE_ANCHOR_M, PROFILE_HEIGHT_M = ddata.PROFILES[0].anchor_m, ddata.PROFILES[0].height_m
"""El ancla y la altura del perfil de banco del contrafuerte (el primero de los diez de §2.2 de la 013)."""
PROFILE_CODE = ddata.PROFILES[0].code
"""El código de ese perfil."""


def crown_level(zone: str) -> float:
    """La cota de coronación de la zona ``zone``: la del ancla del perfil más próxima a la **media del terreno** de la zona más lo
    que dice :data:`BUTTRESS_ZONES` (+12 m en la de 2 ha y +20 m en la de 10 ha)."""
    (left, bottom, right, top), up = BUTTRESS_ZONES[zone]
    rows = slice(cdata.ROWS - int(round(top)), cdata.ROWS - int(round(bottom)))
    columns = slice(int(round(left)), int(round(right)))
    wanted = float(np.mean(scale_terrain()[rows, columns])) + up
    return PROFILE_ANCHOR_M + math.ceil((wanted - PROFILE_ANCHOR_M) / PROFILE_HEIGHT_M - 0.5) * PROFILE_HEIGHT_M


def section_lines(box: tuple[float, float, float, float], spacing_m: float, lines: int) -> list[np.ndarray]:
    """Las ``lines`` secciones de ``box`` (locales): líneas 3D **diagonales a 45°** (``v = u + k·spacing − ancho/2``, con ``u`` y
    ``v`` desde la esquina suroeste: las astillas de ``plan.md`` §5.7 P-7, el caso en que los triángulos del TIN tienen las cajas
    más grandes), separadas ``spacing_m`` m de desplazamiento, con **un vértice por metro** de ``u`` (centros de celda),
    ABSOLUTOS, ``(n, 3)``, con el espesor, de 0,5 a 3 m, en su Z. Con una caja de 1.000 m, 100 m y 10 líneas son las 10 secciones y
    los 7.500 datos de la T24. Las que no tocan la caja no se dan."""
    left, bottom, right, top = box
    width, height = right - left, top - bottom
    found = []
    for number in range(lines):
        offset = -width / 2.0 + number * spacing_m
        first, last = max(0.0, -offset), min(width, height - offset)
        if last - first < 2.0:
            continue
        u = np.arange(math.ceil(first), math.floor(last)) + 0.5
        x, y = left + u, bottom + u + offset
        z = 1.75 + 1.25 * np.sin(x / 90.0 + number) * np.cos(y / 70.0)
        found.append(np.column_stack([SCALE_WEST + x, SCALE_SOUTH + y, z]))
    return found


SECTION_SPECS: dict[str, tuple[tuple[float, float, float, float], float, int]] = {
    "20": (BODY_BOXES["Cuerpo de 20 ha"], 50.0, 14),
    "100": (BODY_BOXES["Cuerpo de 100 ha"], 100.0, 10),
    "100 anchas": (BODY_BOXES["Cuerpo de 100 ha"], 200.0, 5),
    "100 anchas 8": (BODY_BOXES["Cuerpo de 100 ha"], 200.0, 8),
}
"""Las secciones de cada tamaño: la caja, la separación entre líneas y cuántas: de 20 ha (14 líneas a 50 m: ≈ 3.700 datos; el plan
midió 3.584), de 100 ha (**10 a 100 m: los 7.500 datos de la T24**; el plan midió 7.985), de 100 ha con las líneas al doble de
separación (5 a 200 m: 141 m entre ellas, ≈ 3.700 datos; más astillas largas, solo para medir cuánto sube el cálculo; sin
presupuesto) y de 100 ha con **8 a 200 m (4.600 datos: 500, 700, 900, 900, 700, 500, 300 y 100 por línea)**, el caso de más de 10 s
de «Calcular» a «Crear» de la T37 y la T44 (10,09 s calculados, 11,3 s medidos) que fija ``test_i`` de ``test_stockpiles_perf.py``
(T49, E-4)."""
SECTION_NAMES = {"20": "gis_brk_secciones_20", "100": "gis_brk_secciones_100", "100 anchas": "gis_brk_secciones_100_anchas",
                 "100 anchas 8": "gis_brk_secciones_100_anchas_8"}
"""Las cuatro tablas de líneas 3D del proyecto de escala."""


def rectangle_ring(box: tuple[float, float, float, float]) -> np.ndarray:
    """El anillo ABSOLUTO, cerrado y antihorario, del rectángulo local ``box`` (m desde la esquina suroeste de la rejilla de escala)."""
    left, bottom, right, top = box
    west, south = SCALE_WEST, SCALE_SOUTH
    return np.array([(west + left, south + bottom), (west + right, south + bottom), (west + right, south + top),
                     (west + left, south + top), (west + left, south + bottom)], dtype=np.float64)


def mark_ring(mound: Mound, half_m: float = MARK_HALF_M) -> np.ndarray:
    """El anillo absoluto de la marca de ``mound``: un cuadrado de ``half_m`` m de semilado centrado en el montón."""
    return rectangle_ring((mound.cx - half_m, mound.cy - half_m, mound.cx + half_m, mound.cy + half_m))
