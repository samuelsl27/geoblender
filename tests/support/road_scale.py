# SPDX-License-Identifier: GPL-3.0-or-later
"""Los datos puros de las pistas a escala (spec 017, T34; plan 017 §7.1 y §7.3; ``tests/rendimiento/des/test_roads_perf.py`` y
``tests/rendimiento/blender/perf_roads.py``): solo numpy y la biblioteca estándar, **sin cargar ``geoblender``**.

Los usan a la vez las pruebas de rendimiento con el Python de Blender (``tests/support/road_perf.py``) y las de dentro de Blender
(``tests/rendimiento/blender/perf_roads.py``, donde no se puede cargar otra copia del paquete con ``import_geoblender``:
``docs/trampas.md`` §4): **una sola fuente** de los ejes de escala y del barranco. ``tests/support/road_data.py`` (T01) trae lo mismo en las clases de la
copia del paquete (``scale_ravine_terrain``, ``scale_axis_2km``…) y ``tests/unit/design/test_road_scale.py`` comprueba que coinciden bit a bit.

- **La rejilla** (:data:`COLS`, :data:`ROWS`, :func:`absolute`): 1.654 × 1.699 celdas de 1 m (2,81 M), la de la 012 y la 013, con las coordenadas
  *locales* (m desde la esquina suroeste, ``x`` al este e ``y`` al norte; la fila 0 es el norte).
- **El barranco** (:func:`ravine_terrain`, :data:`RAVINE_ORIGIN`, :data:`RAVINE_DESTINATION`): un plano del 4 % hacia el este con un barranco de 14 m a medio
  camino (x = 827) de una ruta de 1,5 km de oeste a este.
- **Los ejes** (:func:`axis_2km`, :func:`compact_axis_2km`, :func:`axis_5km`, :func:`chain_axes`): el de 2.035 m con 61 curvas **en diagonal**
  (ventana de grabado de 2,42 M celdas), el **compacto** (1,73 M) y el de 5.013 m con 163 vértices, y los veinte de la revisión de RNF-017-10.
- **La vista previa** (:func:`preview_lines`): veinte pistas de 5.000 vértices ``(x, y, z)`` absolutas (ondas de 1,5 km separadas 70 m).
- **El perfil de pista de referencia** (:data:`PROFILE`): los valores de IMGA de ``spec.md`` §11 (vehículo de 3,5 m, factor 3, arcén 0 m, caballón 1 m, pd 10 %, desmonte a
  60° y terraplén a 35°, R 20 m, Rmín 12 m…), **solo para pruebas** (D-2); los que la referencia no da (estación, pm, alcance) son HIPÓTESIS sencillas y marcadas.
"""

from __future__ import annotations

import numpy as np

from tests.support import constraints_data as cdata

WEST, SOUTH = cdata.WEST, cdata.SOUTH
"""La esquina suroeste de la rejilla de escala (m, absoluta): la de la 012 y la 013."""
COLS, ROWS, STEP_M = cdata.COLS, cdata.ROWS, cdata.STEP_M
"""1.654 × 1.699 celdas de 1 m."""
SCALE_ROADS = 20
SCALE_ROAD_VERTICES = 5_000
"""Veinte pistas de 5.000 vértices para la vista previa de RNF-017-08."""
SCALE_ROUTE_M = 1_500.0
"""La ruta de RNF-017-01 y 02."""
RAMP_Z0_M, RAMP_SLOPE_PCT = 100.0, 4.0
"""El plano del 4 % hacia el este que sube desde 100 m en x = 0."""
RAVINE_DEPTH_M, RAVINE_HALF_WIDTH_M = 14.0, 30.0
"""El fondo y el semiancho del barranco (una V de flancos del 46,7 %)."""
RAVINE_ORIGIN: tuple[float, float] = (77.0, 850.0)
RAVINE_DESTINATION: tuple[float, float] = (77.0 + SCALE_ROUTE_M, 850.0)
RAVINE_X_M = 77.0 + SCALE_ROUTE_M / 2.0
"""La ruta de 1.500 m de oeste a este por la mitad de la rejilla y la x del eje del barranco, a medio camino (827)."""
PROFILE: dict[str, object] = {
    "vehicle_width_m": 3.5, "lane_factor": 3.0, "shoulder_m": 0.0, "berm_m": 1.0, "max_gradient_pct": 10.0, "station_step_m": 1.0, "max_mean_gradient_pct": 10.0,
    "curve_radius_m": 20.0, "min_radius_m": 12.0, "cut_angle_deg": 60.0, "fill_angle_deg": 35.0, "reach_m": 60.0, "class": "Pista de acceso", "mesh_factor": 1.0,
    "metric": "exact"}
"""El perfil de pista de referencia por el nombre de su parámetro (``design.params.RoadProfileParam``; ``class`` es la clase de la pista): ``road_data.PROFILE``,
**solo de las pruebas**."""
CURVE_RADIUS_M, MIN_RADIUS_M = 20.0, 12.0


def absolute(points: np.ndarray) -> np.ndarray:
    """Los puntos locales ``(x, y)`` de la rejilla de escala en coordenadas absolutas, float64 ``(k, 2)``."""
    return np.asarray(points, dtype=np.float64).reshape(-1, 2) + np.array([WEST, SOUTH])


def local_centers() -> tuple[np.ndarray, np.ndarray]:
    """Las coordenadas LOCALES de los centros de celda, de forma ``(ROWS, COLS)`` (fila 0 al norte)."""
    columns = (np.arange(COLS) + 0.5) * STEP_M
    rows = ROWS * STEP_M - (np.arange(ROWS) + 0.5) * STEP_M
    return np.meshgrid(columns, rows)


def ravine_terrain() -> np.ndarray:
    """El plano del 4 % con el barranco de 14 m a medio camino (x = 827) de la ruta, en los centros de celda (m, float64, ≈ 22 MB): no cambia con ``y``."""
    x, _y = local_centers()
    depth = RAVINE_DEPTH_M * np.maximum(0.0, 1.0 - np.abs(x - RAVINE_X_M) / RAVINE_HALF_WIDTH_M)
    return RAMP_Z0_M + RAMP_SLOPE_PCT / 100.0 * x - depth


def zigzag(vertices: int, length_m: float, mean_heading_deg: float, start: tuple[float, float], deviation_deg: float = 10.0) -> np.ndarray:
    """Una poligonal de ``vertices`` vértices y ``length_m`` m cuyos tramos, iguales, alternan el rumbo ``± deviation_deg`` alrededor de ``mean_heading_deg``, absoluta,
    ``(k, 2)``, desde el punto local ``start``."""
    legs = vertices - 1
    leg = length_m / legs
    headings = np.radians(mean_heading_deg + np.where(np.arange(legs) % 2 == 0, deviation_deg, -deviation_deg))
    steps = np.column_stack([leg * np.sin(headings), leg * np.cos(headings)])
    return absolute(np.vstack([[start], np.asarray(start) + np.cumsum(steps, axis=0)]))


def axis_2km() -> np.ndarray:
    """El eje de 2.035 m con 61 curvas (63 vértices; RNF-017-04), en diagonal (rumbo 45° ± 10°) dentro de la rejilla de escala: su ventana de grabado es de 2,42 M celdas."""
    return zigzag(63, 2_035.0, 45.0, (100.0, 100.0))


def compact_axis_2km() -> np.ndarray:
    """El eje **compacto** de 61 curvas (63 vértices, 2.035 m de poligonal; 1.817 m con las curvas de R = 20 m): alterna el rumbo ``45° ± 35°`` (las curvas giran 70°: sus tangentes
    de 14 m caben en los tramos de 32,8 m). Su ventana de grabado (con el alcance de 60 m) es de **1,73 M celdas**: cabe en la caja de ≤ 2 M celdas de RNF-017-04."""
    return zigzag(63, 2_035.0, 45.0, (100.0, 100.0), 35.0)


def axis_5km() -> np.ndarray:
    """El eje de 5.013 m con 163 vértices (161 curvas; RNF-017-03): no cabe en la rejilla de escala (mide 1,65 km); es solo para el eje y la rasante."""
    return zigzag(163, 5_013.0, 90.0, (100.0, 800.0))


def preview_lines() -> np.ndarray:
    """Veinte pistas de 5.000 vértices ``(x, y, z)`` absolutos para la vista previa (RNF-017-08), float64 con forma ``(20, 5000, 3)``: ondas de 1,5 km separadas 70 m."""
    t = np.arange(SCALE_ROAD_VERTICES) / (SCALE_ROAD_VERTICES - 1.0)
    lines = np.empty((SCALE_ROADS, SCALE_ROAD_VERTICES, 3))
    for index in range(SCALE_ROADS):
        local_x = 100.0 + SCALE_ROUTE_M * t
        local_y = 100.0 + 70.0 * index + 20.0 * np.sin(2.0 * np.pi * 6.0 * t)
        lines[index, :, :2] = absolute(np.column_stack([local_x, local_y]))
        lines[index, :, 2] = 150.0 + 40.0 * t
    return lines


def chain_axes() -> tuple[np.ndarray, ...]:
    """Los veinte ejes de la revisión de RNF-017-10 (una pista por eje, en cadena): las ondas de 1,5 km de :func:`preview_lines` con 120 vértices cada una (``(120, 2)``)."""
    return tuple(line[::len(line) // 120, :2].copy() for line in preview_lines())
