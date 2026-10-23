# SPDX-License-Identifier: GPL-3.0-or-later
"""Datos de referencia de la cubicación entre superficies (spec 011, T02; plan 011 §7.1;
CE-011-01, CE-011-02 y CE-011-03).

Todo es sintético y pequeño (rejillas de ≤ 400 × 400 celdas, RNF-001-01); coordenadas
**absolutas** en float64 (EPSG:25830 + EPSG:5782). Cada caso es un :class:`SurfacePair` (una
superficie de partida y una final en la misma rejilla, con su desmonte y su terraplén
analíticos, m³) o la columna de materiales (:class:`MaterialColumnCase`). No usan el núcleo de
``reserves``: son sus datos de entrada y sus cifras de referencia.

- **Pirámide** (CE-011-01): base cuadrada de :data:`PYRAMID_BASE_M` m y
  :data:`PYRAMID_HEIGHT_M` m de altura sobre el plano de la cota :data:`PYRAMID_FLOOR_Z`
  (166.666,667 m³; :func:`pyramid_volume`) y sus rodajas desde la base
  (:func:`pyramid_slices`, :func:`pyramid_slice_volume`: V·[(1 − h₀/H)³ − (1 − h₁/H)³]).
  :func:`pyramid` la muestrea en el centro de cada celda de la rejilla del proyecto de una
  ventana de 200 m (:func:`pyramid_grid`) con 2, 1 y 0,5 m (:data:`PYRAMID_STEPS`) y el
  vértice en una de sus 24 posiciones (:func:`pyramid_apexes`: 6 de x y 4 de y, las de los
  prototipos del plan, §2.2); :func:`pyramid_tin` es el TIN de cinco vértices y
  :func:`pyramid_from_tin`, ese TIN llevado a rejilla con ``gis.tin_to_raster`` (sin dato fuera
  de la base); :func:`pyramid_quadrants`, sus cuatro cuadrantes cortados por el vértice, que
  parten la ventana (cada uno, V/4 por simetría). Tolerancia: :data:`PYRAMID_TOLERANCE` (D-14 a).
- **Corta circular de la 006** (RF-006-03): el generador de
  ``tests/referencia/gis/test_ref_volume.py`` (no se copia: :func:`circular_pit` lo llama), el
  terreno llano como partida y la corta como final; 1.308.944,006 m³
  (:func:`circular_pit_volume`), las 6 posiciones de su eje (:func:`circular_pit_axes`) y sus
  tolerancias por paso (:data:`CIRCULAR_PIT_TOLERANCE`).
- **Prisma B24** (RF-006-02): 10 m de espesor sobre celdas de 1,0002942907592702 ×
  1,0003022974607014 m (:func:`b24_prism`); con 1.000 × 1.000 celdas, 10.005.966,77 m³
  (:func:`b24_volume`); con menos celdas, para que las pruebas sean rápidas, 10·n²·dx·dy.
- **Columna de materiales** (CE-011-02, CE-011-03; :func:`material_column`): de arriba abajo,
  un acopio (antrópico, suelto, útil), un escombro de espesor conocido sobre la capa útil
  (antrópico, suelto, estéril), la montera, la capa útil compuesta (caliza útil y arcilla
  estéril) y el muro (la última unidad, sin base), con superficies planas inclinadas y huellas
  alineadas con las celdas: la suma en los centros de celda es la integral exacta, así que sus
  volúmenes analíticos son los de la rejilla salvo el redondeo. Sin la unidad de escombro
  (``debris=False``), las mismas superficies: la capa útil no cambia (errores 18 y 63) y la
  montera recibe el volumen del escombro.

Las densidades, los K y los porcentajes de la columna son **valores sintéticos de prueba**, de
ningún material ni proyecto real (la 011 no da ninguno por defecto, D-8): están para que las
pruebas de las toneladas (CE-011-03: un acopio de V m³ pesa V·ρ/K) tengan de dónde leer.

Para el núcleo (T09): :func:`column_layers` da las bases y los espesores de una banda de la
columna como los pide ``reserves.kernel.BandValues`` y :func:`domain_column`, la columna como
``reserves.materials.MaterialColumn`` (lo importa al llamarla: los demás datos no dependen de
``reserves``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from tests.referencia.gis import test_ref_volume as _ref006
from tests.support.package import import_geoblender

gis = import_geoblender("gis")
georef = import_geoblender("core.georef")

CATALOG = georef.load_catalog()
CRS = CATALOG.horizontal(25830)
"""El CRS de todos los casos (ETRS89 / UTM 30N)."""
VERTICAL = CATALOG.vertical(5782)
"""La referencia vertical de todos los casos (Alicante)."""

# Pirámide (CE-011-01) -----------------------------------------------------------------------

PYRAMID_BASE_M = 100.0
"""Lado de la base de la pirámide (m)."""
PYRAMID_HEIGHT_M = 50.0
"""Altura de la pirámide (m)."""
PYRAMID_FLOOR_Z = 600.0
"""Cota del plano de la base de la pirámide (m): la superficie final."""
PYRAMID_STEPS = (2.0, 1.0, 0.5)
"""Los pasos de rejilla de CE-011-01 (m)."""
PYRAMID_TOLERANCE = 1e-3
"""Error relativo admitido del total, y de cada rodaja de 10 m sobre el total (D-14 a)."""
PYRAMID_WINDOW = georef.Window(735_100.0, 4_434_100.0, 735_300.0, 4_434_300.0)
"""La ventana de la pirámide (200 × 200 m, alineada con los tres pasos)."""
PYRAMID_CENTER = (735_200.0, 4_434_200.0)
"""El centro de la ventana: un nodo de la rejilla con los tres pasos."""
QUADRANT_FIELD = "cuadrante"
"""El campo que nombra cada cuadrante (el de una capa de dominios)."""
_X_OFFSETS = (0.0, 0.13, 0.25, 0.5, 0.71)  # más 0,37 del paso (plan §2.2, pyramid.py)
_Y_OFFSETS = (0.0, 0.29, 0.83)  # más medio paso, en tercer lugar
_QUADRANTS = ("Noreste", "Noroeste", "Suroeste", "Sureste")

# Corta circular de la 006 y prisma B24 (RF-006-03, RF-006-02) --------------------------------

CIRCULAR_PIT_TOLERANCE: dict[float, float] = dict(_ref006.PIT_TOLERANCE)
"""Error relativo admitido de la corta circular por paso de rejilla (RF-006-03, spec 006 0.4):
0,025 % con 4 m y 0,01 % con 2, 1 y 0,5 m."""
B24_DX = _ref006.B24_DX
B24_DY = _ref006.B24_DY
B24_CELLS = _ref006.B24_CELLS
B24_THICKNESS = _ref006.B24_THICKNESS
_B24_WEST = 700_000.0
_B24_NORTH = 4_401_000.0

# Columna de materiales (CE-011-02, CE-011-03) ------------------------------------------------

COLUMN_WINDOW = georef.Window(735_000.0, 4_434_000.0, 735_100.0, 4_434_080.0)
"""La ventana de la columna (100 × 80 m)."""
COLUMN_STEP = 2.0
"""El paso de la rejilla de la columna (m): 50 × 40 celdas de 4 m²."""
ANTHROPIC_PRESENCE_M = 0.30
"""El umbral de presencia de las unidades antrópicas por defecto de la 011 (plan §5.2.2,
``res.anthropic_presence_m``): los espesores de la columna son 0 o lo pasan con holgura."""

# Planos (cota, pendiente en u, pendiente en v) en coordenadas relativas a la esquina suroeste
# de la ventana (u = x − oeste, v = y − sur, m), y rectángulos (u₁, v₁, u₂, v₂) alineados con las
# celdas de 2 m.
_Plane = tuple[float, float, float]
_Rect = tuple[float, float, float, float]
_MURO_TOP: _Plane = (600.0, 0.05, 0.02)  # base de la capa útil
_USEFUL_TOP: _Plane = (614.0, 0.03, 0.04)  # base de la montera y del escombro
_GROUND: _Plane = (622.0, 0.02, 0.05)  # el terreno, base del acopio
_FLOOR: _Plane = (595.0, 0.0, 0.0)  # la final, salvo el terraplén
_WHOLE: _Rect = (0.0, 0.0, 100.0, 80.0)
_DEBRIS: _Rect = (10.0, 10.0, 30.0, 30.0)  # escombro sobre la capa útil (sin montera)
_DEBRIS_M = 5.0
_STOCKPILE: _Rect = (60.0, 40.0, 90.0, 70.0)  # acopio sobre el terreno
_STOCKPILE_M = 4.0
_FILL: _Rect = (90.0, 0.0, 100.0, 20.0)  # terraplén sobre el terreno
_FILL_M = 3.0


@dataclass(frozen=True, slots=True, eq=False)
class SurfacePair:
    """Dos superficies en la misma rejilla, CRS y datum: ``start`` (la de partida) y ``final``,
    con el desmonte (``cut_m3``) y el terraplén (``fill_m3``) analíticos (m³); ``center``, en
    planta, el vértice de la pirámide o el eje de la corta (``None`` si no lo hay). Los arrays
    no se modifican."""

    name: str
    start: gis.Raster
    final: gis.Raster
    cut_m3: float
    fill_m3: float = 0.0
    center: tuple[float, float] | None = None

    @property
    def grid(self) -> gis.Grid:
        """La rejilla de las dos superficies."""
        return self.start.grid


@dataclass(frozen=True, slots=True, eq=False)
class DomainPolygon:
    """Un polígono de una capa de dominios, con los campos de ``reserves.polygons.Polygon``
    (plan §5.3.1): ``fid``, el valor de su campo (``value``) y sus anillos ABSOLUTOS
    (``rings``: arrays float64 ``(k, 2)`` cerrados, el primer vértice repetido al final como en
    un GeoPackage; el exterior antihorario y los huecos horarios)."""

    fid: int
    value: str
    rings: tuple[np.ndarray, ...]


@dataclass(frozen=True, slots=True)
class ColumnComponent:
    """Un componente de una unidad compuesta: código, nombre, papel (``useful``/``waste``),
    estado (el de su unidad), porcentaje, densidad in situ (t/m³) y K sintéticos de prueba, y
    su volumen analítico (m³: el de su unidad por su porcentaje)."""

    code: str
    name: str
    role: str
    state: str
    percent: float
    density_t_m3: float
    swell: float
    expected_m3: float


@dataclass(frozen=True, slots=True, eq=False)
class ColumnUnit:
    """Una unidad de la columna, con los nombres de la tabla ``res_materials`` (plan §5.2.1):
    código, nombre, clase (``natural``, ``anthropic`` o ``compound``), papel (``useful``,
    ``waste`` o ``None`` en una compuesta), estado (``in_situ`` o ``loose``), base (``None`` en
    la última), espesor (solo en una antrópica: m, ≥ 0), densidad in situ (t/m³) y K sintéticos
    de prueba (``None`` en una compuesta: los llevan sus componentes), componentes y su volumen
    analítico de desmonte (m³)."""

    code: str
    name: str
    kind: str
    role: str | None
    state: str
    base: gis.Raster | None
    thickness: gis.Raster | None
    density_t_m3: float | None
    swell: float | None
    components: tuple[ColumnComponent, ...]
    expected_m3: float


@dataclass(frozen=True, slots=True, eq=False)
class MaterialColumnCase:
    """La columna sintética: su rejilla, la superficie de partida y la final, las unidades de
    arriba abajo y el desmonte y el terraplén analíticos (m³; el terraplén no se reparte)."""

    grid: gis.Grid
    start: gis.Raster
    final: gis.Raster
    units: tuple[ColumnUnit, ...]
    cut_m3: float
    fill_m3: float


def _raster(grid: gis.Grid, values: np.ndarray) -> gis.Raster:
    return gis.Raster(grid, values, CRS, VERTICAL)


# Pirámide -----------------------------------------------------------------------------------


def pyramid_volume() -> float:
    """El volumen analítico de la pirámide (m³): A²·H/3 = 166.666,667."""
    return PYRAMID_BASE_M * PYRAMID_BASE_M * PYRAMID_HEIGHT_M / 3.0


def pyramid_slice_volume(bottom: float, top: float) -> float:
    """El volumen analítico de la pirámide entre las cotas ``bottom`` y ``top`` (m, absolutas):
    V·[(1 − h₁/H)³ − (1 − h₂/H)³] con las alturas sobre la base recortadas a [0, H]."""
    low = min(max(bottom - PYRAMID_FLOOR_Z, 0.0), PYRAMID_HEIGHT_M)
    high = min(max(top - PYRAMID_FLOOR_Z, 0.0), PYRAMID_HEIGHT_M)
    return pyramid_volume() * ((1.0 - low / PYRAMID_HEIGHT_M) ** 3
                               - (1.0 - high / PYRAMID_HEIGHT_M) ** 3)


def pyramid_slices(height_m: float = 10.0) -> tuple[tuple[float, float, float], ...]:
    """Las rodajas de ``height_m`` desde la base de la pirámide hasta su vértice: ``(cota de
    abajo, cota de arriba, m³)``; con 10 m, 81.333,333, 49.333,333, 25.333,333, 9.333,333 y
    1.333,333 m³."""
    count = math.ceil(PYRAMID_HEIGHT_M / height_m)
    return tuple(
        (PYRAMID_FLOOR_Z + k * height_m, PYRAMID_FLOOR_Z + (k + 1) * height_m,
         pyramid_slice_volume(PYRAMID_FLOOR_Z + k * height_m,
                              PYRAMID_FLOOR_Z + (k + 1) * height_m))
        for k in range(count)
    )


def pyramid_grid(step: float) -> gis.Grid:
    """La rejilla del proyecto de paso ``step`` (m) sobre :data:`PYRAMID_WINDOW`."""
    return gis.project_grid(PYRAMID_WINDOW, step)


def pyramid_apexes(step: float) -> tuple[tuple[float, float], ...]:
    """Las 24 posiciones del vértice con el paso ``step``: el centro de la ventana desplazado
    en x 0, 0,13, 0,25, 0,5, 0,71 m y 0,37 del paso, y en y 0, 0,29 m, medio paso y 0,83 m
    (las de los prototipos del plan, §2.2: nodos, centros de celda y posiciones cualesquiera)."""
    xs = (*_X_OFFSETS, 0.37 * step)
    ys = (_Y_OFFSETS[0], _Y_OFFSETS[1], 0.5 * step, _Y_OFFSETS[2])
    cx, cy = PYRAMID_CENTER
    return tuple((cx + dx, cy + dy) for dx in xs for dy in ys)


def pyramid_heights(x: np.ndarray, y: np.ndarray, apex: tuple[float, float]) -> np.ndarray:
    """La altura de la pirámide de vértice ``apex`` sobre su base en los puntos ``(x, y)``
    (m, ≥ 0): H·(1 − r/(A/2)) con r la mayor de |x − xᵥ| y |y − yᵥ|, y 0 fuera de la base."""
    r = np.maximum(np.abs(x - apex[0]), np.abs(y - apex[1]))
    return np.maximum(PYRAMID_HEIGHT_M * (1.0 - r / (PYRAMID_BASE_M / 2.0)), 0.0)


def pyramid(step: float, apex: tuple[float, float] = PYRAMID_CENTER) -> SurfacePair:
    """La pirámide muestreada en el centro de cada celda de :func:`pyramid_grid` como partida
    y el plano de su base como final; desmonte, :func:`pyramid_volume`."""
    grid = pyramid_grid(step)
    x, y = grid.centers()
    start = PYRAMID_FLOOR_Z + pyramid_heights(x, y, apex)
    return SurfacePair(
        f"Pirámide ({step:g} m, vértice {apex[0]:.2f} {apex[1]:.2f})",
        _raster(grid, start),
        _raster(grid, np.full(grid.shape, PYRAMID_FLOOR_Z)),
        cut_m3=pyramid_volume(),
        center=apex,
    )


def pyramid_tin(apex: tuple[float, float] = PYRAMID_CENTER) -> gis.Tin:
    """La pirámide como TIN de cinco vértices (las cuatro esquinas de la base y el vértice) y
    cuatro caras antihorarias vistas desde arriba, sin aristas obligatorias."""
    ax, ay = apex
    half = PYRAMID_BASE_M / 2.0
    vertices = np.array(
        [
            [ax - half, ay - half, PYRAMID_FLOOR_Z],
            [ax + half, ay - half, PYRAMID_FLOOR_Z],
            [ax + half, ay + half, PYRAMID_FLOOR_Z],
            [ax - half, ay + half, PYRAMID_FLOOR_Z],
            [ax, ay, PYRAMID_FLOOR_Z + PYRAMID_HEIGHT_M],
        ],
        dtype=np.float64,
    )
    faces = np.array([[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]], dtype=np.int32)
    return gis.Tin(vertices, faces, np.zeros((0, 2), dtype=np.int32),
                   np.zeros(len(vertices), dtype=np.uint8))


def pyramid_from_tin(step: float, apex: tuple[float, float] = PYRAMID_CENTER) -> SurfacePair:
    """:func:`pyramid_tin` llevado a :func:`pyramid_grid` con ``gis.tin_to_raster`` (sin dato
    fuera de la base) como partida y el plano de la base como final."""
    grid = pyramid_grid(step)
    start = gis.tin_to_raster(pyramid_tin(apex), grid, crs=CRS, vertical=VERTICAL)
    return SurfacePair(
        f"Pirámide como TIN ({step:g} m, vértice {apex[0]:.2f} {apex[1]:.2f})",
        start,
        _raster(grid, np.full(grid.shape, PYRAMID_FLOOR_Z)),
        cut_m3=pyramid_volume(),
        center=apex,
    )


def pyramid_quadrants(apex: tuple[float, float] = PYRAMID_CENTER,
                      window: georef.Window = PYRAMID_WINDOW) -> tuple[DomainPolygon, ...]:
    """Los cuatro cuadrantes de la pirámide de vértice ``apex``, cortados por él, hasta los
    bordes de ``window`` (la parten): Noreste, Noroeste, Suroeste y Sureste (``fid`` 1 a 4,
    campo :data:`QUADRANT_FIELD`); cada uno tiene la cuarta parte del volumen de la pirámide."""
    ax, ay = apex
    west, south, east, north = window.xmin, window.ymin, window.xmax, window.ymax
    corners = (
        ((ax, ay), (east, ay), (east, north), (ax, north)),
        ((west, ay), (ax, ay), (ax, north), (west, north)),
        ((west, south), (ax, south), (ax, ay), (west, ay)),
        ((ax, south), (east, south), (east, ay), (ax, ay)),
    )
    return tuple(
        DomainPolygon(fid, value, (np.array([*points, points[0]], dtype=np.float64),))
        for fid, (value, points) in enumerate(zip(_QUADRANTS, corners, strict=True), start=1)
    )


# Corta circular de la 006 y prisma B24 --------------------------------------------------------


def circular_pit_volume() -> float:
    """El volumen analítico de la corta circular de la 006 (m³): 1.308.944,006."""
    return _ref006._pit_analytic()


def circular_pit_axes() -> list[tuple[str, tuple[float, float]]]:
    """Las 6 posiciones del eje de la corta de la 006, con su nombre: el centro de la ventana,
    un nodo de la rejilla con todos los pasos y 4 con semilla fija."""
    return _ref006._pit_axes()


def circular_pit(step: float, axis: tuple[float, float]) -> SurfacePair:
    """La corta circular de la 006 con el eje en ``axis``, muestreada en el centro de cada celda
    de la rejilla del proyecto de paso ``step`` (m) sobre su ventana de 260 m: el terreno llano
    como partida y la corta como final (todo desmonte)."""
    grid = gis.project_grid(_ref006.WINDOW, step)
    x, y = grid.centers()
    floor = _ref006.TERRAIN_Z - _ref006.PIT_BENCHES * _ref006.PIT_BENCH
    pit = floor + _ref006._pit_height(np.hypot(x - axis[0], y - axis[1]))
    return SurfacePair(
        f"Corta circular ({step:g} m, eje {axis[0]:.2f} {axis[1]:.2f})",
        _raster(grid, np.full(grid.shape, _ref006.TERRAIN_Z)),
        _raster(grid, pit),
        cut_m3=circular_pit_volume(),
        center=axis,
    )


def b24_volume(cells: int = B24_CELLS) -> float:
    """El volumen analítico del prisma B24 de ``cells`` × ``cells`` celdas (m³):
    10·n²·dx·dy; con 1.000, 10.005.966,77."""
    return B24_THICKNESS * cells * cells * B24_DX * B24_DY


def b24_prism(cells: int = B24_CELLS) -> SurfacePair:
    """El prisma B24: 10 m sobre la superficie sintética de ``tests/data/gis`` (z = 800 + 0,5x −
    0,25y + 3 sin(x/7), en m relativos), en ``cells`` × ``cells`` celdas de
    1,0002942907592702 × 1,0003022974607014 m; la cara de arriba como partida y la base como
    final."""
    grid = gis.Grid(west=_B24_WEST, north=_B24_NORTH, dx=B24_DX, dy=B24_DY, ncols=cells,
                    nrows=cells)
    x, y = grid.centers()
    east = x - _B24_WEST
    base = 800.0 + 0.5 * east - 0.25 * (y - 4_400_000.0) + 3.0 * np.sin(east / 7.0)
    return SurfacePair(
        f"Prisma B24 ({cells} × {cells} celdas)",
        _raster(grid, base + B24_THICKNESS),
        _raster(grid, base),
        cut_m3=b24_volume(cells),
    )


# Columna de materiales -------------------------------------------------------------------------


def _area(rect: _Rect) -> float:
    return (rect[2] - rect[0]) * (rect[3] - rect[1])


def _mean(plane: _Plane, rect: _Rect) -> float:
    """La cota media de ``plane`` en ``rect``: la de su centro (es lineal)."""
    z, slope_u, slope_v = plane
    return z + slope_u * (rect[0] + rect[2]) / 2.0 + slope_v * (rect[1] + rect[3]) / 2.0


def _between(upper: _Plane, lower: _Plane, rect: _Rect) -> float:
    """∫∫ (upper − lower) en ``rect`` (m³)."""
    return _area(rect) * (_mean(upper, rect) - _mean(lower, rect))


def _plane_values(plane: _Plane, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    z, slope_u, slope_v = plane
    return z + slope_u * u + slope_v * v


def _inside(rect: _Rect, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Las celdas con el centro dentro de ``rect`` (alineado con las celdas: ningún centro cae
    en su borde)."""
    return (u > rect[0]) & (u < rect[2]) & (v > rect[1]) & (v < rect[3])


def _column_volumes(debris: bool) -> dict[str, float]:
    """Los volúmenes analíticos de desmonte de cada unidad (m³), sin las celdas del terraplén:
    el muro, de su techo a la final; la capa útil, entera (también bajo el escombro); la
    montera, fuera del escombro (o, sin la unidad de escombro, también el escombro); el
    escombro y el acopio, su espesor por su huella."""
    debris_m3 = _area(_DEBRIS) * _DEBRIS_M
    overburden = (_between(_GROUND, _USEFUL_TOP, _WHOLE) - _between(_GROUND, _USEFUL_TOP, _DEBRIS)
                  - _between(_GROUND, _USEFUL_TOP, _FILL))
    volumes = {"acopio": _area(_STOCKPILE) * _STOCKPILE_M}
    if debris:
        volumes["escombro"] = debris_m3
    volumes["montera"] = overburden if debris else overburden + debris_m3
    volumes["capa_util"] = (_between(_USEFUL_TOP, _MURO_TOP, _WHOLE)
                            - _between(_USEFUL_TOP, _MURO_TOP, _FILL))
    volumes["muro"] = _between(_MURO_TOP, _FLOOR, _WHOLE) - _between(_MURO_TOP, _FLOOR, _FILL)
    return volumes


def _column_cut() -> float:
    """El desmonte analítico de la columna (m³), por las superficies y no por las unidades: el
    terreno sobre la final fuera del terraplén, sin la montera de la huella del escombro y con
    el escombro y el acopio."""
    return (_between(_GROUND, _FLOOR, _WHOLE) - _between(_GROUND, _FLOOR, _FILL)
            - _between(_GROUND, _USEFUL_TOP, _DEBRIS) + _area(_DEBRIS) * _DEBRIS_M
            + _area(_STOCKPILE) * _STOCKPILE_M)


def material_column(*, debris: bool = True) -> MaterialColumnCase:
    """La columna sintética (CE-011-02, CE-011-03) en 50 × 40 celdas de 2 m. De arriba abajo:

    - **acopio** (antrópico, suelto, útil): 4 m sobre el terreno en un rectángulo de 30 × 30 m
      (3.600 m³); base, el terreno; espesor, 4 m allí y 0 fuera;
    - **escombro** (antrópico, suelto, estéril; solo con ``debris``): 5 m sobre la capa útil, sin
      montera, en un rectángulo de 20 × 20 m (2.000 m³); base, el techo de la capa útil;
    - **montera** (natural, in situ, estéril): del techo de la capa útil al terreno (58.570 m³;
      sin la unidad de escombro, 60.570 m³: también los 5 m del escombro);
    - **capa útil** (compuesta, in situ): de 12 a 15,6 m de espesor (107.940 m³), caliza útil
      82,50 % y arcilla estéril 17,50 %;
    - **muro** (natural, in situ, estéril; sin base): de su techo a la final (64.410 m³).

    La final está en la cota 595 salvo un terraplén de 3 m sobre el terreno en 10 × 20 m (600 m³,
    que no se reparte por unidades); el desmonte, 236.520 m³. Las superficies son las mismas con
    y sin la unidad de escombro."""
    grid = gis.project_grid(COLUMN_WINDOW, COLUMN_STEP)
    x, y = grid.centers()
    u = x - COLUMN_WINDOW.xmin
    v = y - COLUMN_WINDOW.ymin
    muro_top = _plane_values(_MURO_TOP, u, v)
    useful_top = _plane_values(_USEFUL_TOP, u, v)
    ground = _plane_values(_GROUND, u, v)
    in_debris = _inside(_DEBRIS, u, v)
    in_stockpile = _inside(_STOCKPILE, u, v)
    in_fill = _inside(_FILL, u, v)
    start = ground.copy()
    start[in_debris] = useful_top[in_debris] + _DEBRIS_M
    start[in_stockpile] = ground[in_stockpile] + _STOCKPILE_M
    final = np.full(grid.shape, _FLOOR[0])
    final[in_fill] = start[in_fill] + _FILL_M
    stockpile_m = np.where(in_stockpile, _STOCKPILE_M, 0.0)
    debris_m = np.where(in_debris, _DEBRIS_M, 0.0)

    volumes = _column_volumes(debris)
    useful = volumes["capa_util"]
    components = (
        ColumnComponent("caliza", "Caliza", "useful", "in_situ", 82.50, 2.65, 1.60,
                        useful * 82.50 / 100.0),
        ColumnComponent("arcilla", "Arcilla", "waste", "in_situ", 17.50, 2.10, 1.30,
                        useful * 17.50 / 100.0),
    )
    units = [
        ColumnUnit("acopio", "Acopio", "anthropic", "useful", "loose", _raster(grid, ground),
                   _raster(grid, stockpile_m), 2.60, 1.50, (), volumes["acopio"]),
    ]
    if debris:
        units.append(
            ColumnUnit("escombro", "Escombro", "anthropic", "waste", "loose",
                       _raster(grid, useful_top), _raster(grid, debris_m), 2.20, 1.35, (),
                       volumes["escombro"])
        )
    units += [
        ColumnUnit("montera", "Montera", "natural", "waste", "in_situ", _raster(grid, useful_top),
                   None, 2.00, 1.25, (), volumes["montera"]),
        ColumnUnit("capa_util", "Capa útil", "compound", None, "in_situ",
                   _raster(grid, muro_top), None, None, None, components, useful),
        ColumnUnit("muro", "Muro", "natural", "waste", "in_situ", None, None, 2.45, 1.45, (),
                   volumes["muro"]),
    ]
    return MaterialColumnCase(
        grid=grid,
        start=_raster(grid, start),
        final=_raster(grid, final),
        units=tuple(units),
        cut_m3=_column_cut(),
        fill_m3=_area(_FILL) * _FILL_M,
    )


def column_layers(case: MaterialColumnCase, rows: slice | None = None
                  ) -> tuple[tuple[np.ndarray | None, ...], tuple[np.ndarray | None, ...]]:
    """Las bases y los espesores de las unidades de ``case``, de arriba abajo, en las filas
    ``rows`` (todas, sin ellas), como los pide ``reserves.kernel.BandValues``: la base de la
    última unidad y el espesor de las que no son antrópicas, ``None``."""
    rows = slice(None) if rows is None else rows
    bases = tuple(None if unit.base is None else unit.base.values[rows] for unit in case.units)
    thicknesses = tuple(None if unit.thickness is None else unit.thickness.values[rows]
                        for unit in case.units)
    return bases, thicknesses


def domain_column(case: MaterialColumnCase):
    """La columna de ``case`` como ``reserves.materials.MaterialColumn``: la base de cada unidad,
    el dato del proyecto ``base_<código>`` (D-24), y el espesor de una antrópica,
    ``espesor_<código>`` (D-23)."""
    materials = import_geoblender("reserves.materials")
    surfaces = import_geoblender("reserves.surfaces")

    def ref(prefix: str, unit: ColumnUnit, raster: gis.Raster | None):
        if raster is None:
            return None
        return surfaces.SurfaceRef(dataset=f"{prefix}_{unit.code}",
                                   label=f"{prefix.capitalize()} de {unit.name}")

    return materials.MaterialColumn(tuple(
        materials.Unit(
            unit.code, unit.name, unit.kind, unit.role, unit.state,
            ref("base", unit, unit.base), ref("espesor", unit, unit.thickness),
            tuple(materials.Component(item.code, item.name, item.role)
                  for item in unit.components),
        )
        for unit in case.units
    ))
