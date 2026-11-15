# SPDX-License-Identifier: GPL-3.0-or-later
"""Los datos de escala de las entidades de diseño paramétricas que no necesitan el paquete (spec 015, T33; plan
015 §7.1 y §7.3; RNF-015-01 a RNF-015-09).

Solo numpy y la biblioteca estándar: los usan a la vez las pruebas de rendimiento con el Python de Blender
(``tests/support/entity_perf.py``, que las convierte a las clases de su copia del paquete,
``import_geoblender``) y las de dentro de Blender (``tests/rendimiento/blender/perf_entities.py``, que las
convierte a las clases de la extensión habilitada: allí no se puede cargar otra copia del paquete,
``docs/trampas.md`` §4). No se versionan datos: son los de §2.2 del plan 013 (``design_data``: la rejilla de
1.654 × 1.699 celdas de 1 m, 2,81 M, y su terreno de 145 a 215 m con colinas, un ondulado de metros y ruido de
5 cm) y las geometrías de abajo, sin ningún dato de cliente.

- **La capa de plataformas de escala** (:data:`LAYER`, de líneas, con los campos ``ancho``, ``cota_inicial`` y
  ``pendiente``): una plataforma **grande** (:data:`BIG_NAME`: eje de 500 m y 200 m de ancho, 10 ha, a la cota
  mediana del terreno de su huella, «en corte y relleno», borde a 35° con 150 m de alcance y distancia euclídea
  exacta) para RNF-015-01 y 04, y **veinte** plataformas de ≤ 1 ha en cinco columnas y cuatro filas
  (:func:`chain_name`; eje de 98 m y 100 m de ancho, «en corte» una cota por debajo de lo más bajo del terreno de
  su huella, protegidas con 5 m de resguardo y un borde de 35° con 40 m de alcance) para la cadena de RNF-015-08
  y 09: cada una parte de la superficie de la anterior.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from tests.support import constraints_data as cdata
from tests.support import design_data as ddata

__all__ = [
    "BIG_AXIS_LOCAL", "BIG_NAME", "BIG_REACH_M", "BIG_WIDTH_M", "CHAIN_GUARD_M", "CHAIN_LENGTH",
    "CHAIN_REACH_M", "EDGE_ANGLE_DEG", "FOOTPRINT_LIMIT_CELLS", "LAYER", "LayerArrays",
    "SYNTHETIC_ENTITIES", "absolute", "chain_axis", "chain_name", "layer_arrays",
]

LAYER = "gis_fea_plataformas_escala"
"""La capa de líneas con las plataformas de escala (los campos de un corredor, D-15)."""
BIG_NAME = "Plataforma grande"
"""La plataforma de RNF-015-01 y 04."""
CHAIN_LENGTH = 20
"""Las plataformas de la cadena de RNF-015-08 y 09."""
SYNTHETIC_ENTITIES = 200
"""Las entidades de la versión de RNF-015-02 y 06 (la primera de verdad y 199 que se apoyan en ella)."""

BIG_AXIS_LOCAL = ((550.0, 1150.0), (1050.0, 1150.0))
"""El eje de la plataforma grande (m desde la esquina suroeste de la ventana): 500 m, al norte de la cadena (su
borde, de 150 m, no alcanza la huella de ninguna de las veinte)."""
BIG_WIDTH_M = 200.0
"""Su ancho (m): 500 × 200 = 10 ha."""
BIG_REACH_M = 150.0
"""El alcance de su borde (m)."""
CHAIN_COLUMNS = 5
CHAIN_SPACING_M = 150.0
"""Entre ejes de la cadena (m): un hueco de 50 m entre dos huellas, más que el alcance de su borde."""
CHAIN_ORIGIN_LOCAL = (300.0, 350.0)
"""El primer vértice del eje de la primera de la cadena (m desde la esquina suroeste de la ventana)."""
CHAIN_AXIS_M = 98.0
CHAIN_WIDTH_M = 100.0
"""El eje y el ancho de cada plataforma de la cadena (m): 98 × 100 = 9.800 m², menos de 1 ha."""
CHAIN_REACH_M = 40.0
"""El alcance de su borde (m)."""
CHAIN_GUARD_M = 5.0
"""El resguardo con que protege su huella (m)."""
EDGE_ANGLE_DEG = ddata.GENERAL_DEG
"""El ángulo del borde de todas (°): el del talud de la 013."""
FOOTPRINT_LIMIT_CELLS = 10_000
"""1 ha en celdas de 1 m."""


def absolute(x: float, y: float) -> tuple[float, float]:
    """El punto absoluto (float64) de ``(x, y)`` locales (m desde la esquina suroeste de la ventana)."""
    return cdata.WEST + x, cdata.SOUTH + y


def _terrain_in(left: float, bottom: float, right: float, top: float) -> np.ndarray:
    """Las cotas del terreno de escala dentro de la caja local (celdas de 1 m; la fila 0 al norte)."""
    rows = slice(cdata.ROWS - int(round(top)), cdata.ROWS - int(round(bottom)))
    columns = slice(int(round(left)), int(round(right)))
    return ddata.terrain()[rows, columns]


def chain_axis(index: int) -> tuple[tuple[float, float], tuple[float, float]]:
    """El eje local de la plataforma ``index`` (0 a 19) de la cadena."""
    column, row = index % CHAIN_COLUMNS, index // CHAIN_COLUMNS
    x0 = CHAIN_ORIGIN_LOCAL[0] + CHAIN_SPACING_M * column
    y = CHAIN_ORIGIN_LOCAL[1] + CHAIN_SPACING_M * row
    return (x0, y), (x0 + CHAIN_AXIS_M, y)


def chain_name(index: int) -> str:
    """El nombre de la plataforma ``index`` (0 a 19) de la cadena: «Plataforma 01»…"""
    return f"Plataforma {index + 1:02d}"


@dataclass(frozen=True, slots=True)
class LayerArrays:
    """Lo que lleva la capa :data:`LAYER` por entidad (la grande y, luego, las veinte de la cadena): el
    nombre, el camino absoluto del eje (float64), el ancho (m), la cota inicial (m) y la pendiente (%)."""

    names: tuple[str, ...]
    paths: tuple[np.ndarray, ...]
    widths: tuple[float, ...]
    levels: tuple[float, ...]
    gradients: tuple[float, ...]


def layer_arrays() -> LayerArrays:
    """Las plataformas de escala (arrays nuevos): la cota inicial de la grande es la mediana del terreno de su
    huella (corta y rellena) y la de cada una de la cadena, una cota por debajo de lo más bajo del suyo (corta del
    todo, sin contrapendiente); todas, a 0 %."""
    (x0, y0), (x1, _y1) = BIG_AXIS_LOCAL
    half = BIG_WIDTH_M / 2.0
    names = [BIG_NAME]
    paths = [np.array([absolute(*point) for point in BIG_AXIS_LOCAL], dtype=np.float64)]
    widths = [BIG_WIDTH_M]
    levels = [float(np.median(_terrain_in(x0, y0 - half, x1, y0 + half)))]
    for index in range(CHAIN_LENGTH):
        (left, y), (right, _same) = chain_axis(index)
        lowest = _terrain_in(left, y - CHAIN_WIDTH_M / 2.0, right, y + CHAIN_WIDTH_M / 2.0).min()
        names.append(chain_name(index))
        paths.append(np.array([absolute(*point) for point in chain_axis(index)], dtype=np.float64))
        widths.append(CHAIN_WIDTH_M)
        levels.append(float(np.floor(lowest)) - 1.0)
    return LayerArrays(tuple(names), tuple(paths), tuple(widths), tuple(levels), (0.0,) * len(names))
