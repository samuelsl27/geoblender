# SPDX-License-Identifier: GPL-3.0-or-later
"""La sección tipo de la pista: huella, lados y cotas (spec 017, T12; HU-017-1; RF-017-20 y RF-017-06; CE-017-06; RNF-017-06; plan 017 §5.4 A6 y A7,
§5.3.1, §5.7 P-10 y §5.8 H-3).

Lo que da, todo en el dominio (Python y numpy, sin Blender), con las coordenadas absolutas en float64 (regla 4 de AGENTS.md):

- **La huella** (:func:`section_cells` → :class:`Section`; A6): la sección horizontal de la pista —calzada de *f·A* m con **el eje en su centro** (P-10),
  más el arcén (``shoulder_m``) y el caballón (``berm_m``), cada uno en un lado— sobre :func:`~.quarry.axis_abscissa_units` del **eje denso** (el eje cada
  :data:`DENSE_STEP_M` = 1 m, ``Axis.sample``) con la semianchura máxima ``f·A/2 + máx(arcén, caballón)`` y recortada después por lado (A7). Los **extremos son
  planos y perpendiculares al eje**: la longitud de su huella a lo largo del eje es la del eje con un error ≤ 1 celda (error 20: no los 211,5 m de un *buffer* de
  extremos redondos).
- **Los lados** (A7; D-12): la **distancia lateral con signo** ``d`` de cada celda (positiva **a la derecha** en el sentido de la marcha) es el producto vectorial
  de (celda − punto del eje) por la tangente: ``quarry.axis_abscissa`` da la abscisa σ, **no** la distancia con signo. En cada abscisa, el lado de **mayor cota del
  terreno de partida** (el terreno a ``±f·A/2`` del eje, **por interpolación bilineal** entre los centros de celda) lleva el **arcén** (al pie del talud) y el otro el
  **caballón**; con cotas iguales —o si falta el dato a un lado— el caballón va a la derecha (y el arcén, a la izquierda: D-12, CE-017-06). La calzada es ``|d| ≤
  f·A/2`` y el arcén y el caballón, el resto de su lado hasta su ancho. **El caballón no tiene altura**: es una anchura (su cordón no cabe en la rejilla), y sus celdas
  van a la cota de la rasante como las de la calzada.
- **Las cotas** (:meth:`Section.levels`): la rasante de cada celda es la de su abscisa (``np.interp`` sobre las estaciones del eje, las de ``road_gradient``).

**La abscisa σ es la del eje (longitud de arco)**, no la de la poligonal densa: la abscisa de ``axis_abscissa`` sobre las cuerdas de 1 m es más corta que el arco
(en R = 20 m, 103 µm por metro de arco: 3,2 mm en un cuarto de circunferencia y 6 cm en una pista de 2 km con 600 m de curvas, o 6 mm de cota con el 10 %; con Rmín = 12 m, 290 µm por metro) y se pasa a
las estaciones del eje por interpolación lineal entre los vértices del eje denso: en un tramo recto es exacta. En una curva, la huella y los lados se miden sobre la
**poligonal inscrita** de cuerdas de 1 m (lo que pide A7): la distancia lateral difiere de la del arco como mucho en la flecha de la cuerda (``1/(8R)``: 6 mm con R = 20
m y 10 mm con Rmín = 12 m) y la abscisa de una celda a lado ``d`` de la curva, en ``d/(2R)`` m a lo sumo (lo que difiere el pie de la perpendicular a una cuerda de la
proyección radial).

Por **pasos** (:func:`section_steps`: una unidad cada ``≈ 10 ms``, por teselas de ``axis_abscissa_units`` y por bloques de celdas de la huella; RNF-017-06) y
:func:`section_cells` es esa misma cuenta llevada hasta el final. Cerrar el generador a mitad no deja nada: no escribe nada y no modifica sus entradas
(principio 7). **Perezoso** (RNF-001-03): ni ``design.model`` ni nada del arranque lo importan; lo pide quien calcula una pista.
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Generator
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

import numpy as np

from ..gis.grid import Grid
from .quarry import axis_abscissa_units, corridor_window
from .road_axis import Axis, stations_for

__all__ = [
    "DENSE_STEP_M",
    "LEFT",
    "RIGHT",
    "Section",
    "SectionClass",
    "sample_terrain",
    "section_cells",
    "section_steps",
    "section_window",
]

DENSE_STEP_M = 1.0
"""El paso (m) del eje denso sobre el que se mide la huella (A6): una discretización del cálculo, no una cifra minera. Con 1 m, la flecha de la cuerda de un
arco de 12 m de radio es de 10 mm."""
RIGHT = 1
"""El lado derecho en el sentido de la marcha (el signo de la distancia lateral)."""
LEFT = -1
"""El lado izquierdo en el sentido de la marcha."""
_EDGE_TOL_M = 1e-9
"""Lo que una celda puede pasar del ancho de su lado (m) y seguir dentro (``|d| ≤ ancho``): el redondeo de la última cifra de las cuentas en coma flotante; una celda
cuyo centro cae **justo** en el borde (a 5,25 m con celdas de 0,5 m) cuenta."""
_BLOCK_CELLS = 32_768
"""Las celdas de la huella que se miden en una unidad de trabajo (≈ 5 ms): el recorte por lados y el terreno a ``±f·A/2`` van por bloques para ceder el hilo."""


class SectionClass(IntEnum):
    """La clase de cada celda de la sección: fuera de la huella, calzada, arcén o caballón (``int8`` en :attr:`Section.kind`)."""

    OUTSIDE = 0
    CARRIAGEWAY = 1
    SHOULDER = 2
    BERM = 3


# --- Las entradas -------------------------------------------------------------------------------------------------------


def _width(value: object, what: str, *, zero: bool) -> float:
    """``value`` como un ancho (m): un número real finito, positivo (con ``zero``, no negativo). ``TypeError`` si no es un número real, ``ValueError`` si no es finito o
    no está en su rango (errores del programa: la preparación de la pista rechazó antes, con su perfil, su campo y su valor)."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"{what} es un número real, no {value!r}")
    number = float(value)
    if not math.isfinite(number) or number < 0.0 or (number == 0.0 and not zero):
        raise ValueError(f"{what} es un número finito {'no negativo' if zero else 'positivo'}, no {value!r}")
    return number


def _window(window: object, grid: Grid) -> tuple[slice, slice]:
    """``window`` (filas y columnas de ``grid``, dos ``slice`` de enteros con paso 1) comprobada. ``TypeError`` si no son dos ``slice``, ``ValueError`` si no son de enteros,
    tienen paso o salen de la rejilla."""
    if not (isinstance(window, tuple) and len(window) == 2 and all(isinstance(part, slice) for part in window)):
        raise TypeError(f"la ventana son dos slice (filas, columnas), no {window!r}")
    parts: list[slice] = []
    for name, part, count in (("filas", window[0], grid.nrows), ("columnas", window[1], grid.ncols)):
        if part.step not in (None, 1) or not all(isinstance(bound, numbers.Integral) for bound in (part.start, part.stop)):
            raise ValueError(f"la ventana de {name} es un slice de enteros con paso 1, no {part!r}")
        start, stop = int(part.start), int(part.stop)
        if not 0 <= start <= stop <= count:
            raise ValueError(f"la ventana de {name} ({start}:{stop}) no está dentro de la rejilla (0:{count})")
        parts.append(slice(start, stop))
    return parts[0], parts[1]


def _ground(terrain: object, grid: Grid) -> np.ndarray:
    """El terreno de partida como float64 de la forma de la rejilla (sin copia si ya lo es); ``ValueError`` si no lo es."""
    try:
        array = np.asarray(terrain, dtype=np.float64)
    except (TypeError, ValueError) as error:
        raise ValueError(f"el terreno de partida no es un array de números: {error}") from error
    if array.shape != grid.shape:
        raise ValueError(f"el terreno de partida tiene la forma {array.shape} y la rejilla, {grid.shape}")
    return array


def _frozen(array: np.ndarray) -> np.ndarray:
    """``array`` (propio de quien lo crea) de solo lectura."""
    array.flags.writeable = False
    return array


def _checked(axis: object, carriageway_m: object, shoulder_m: object, berm_m: object, grid: object) -> tuple[float, float, float]:
    """Los tres anchos comprobados (calzada, arcén y caballón, m), tras comprobar el eje y la rejilla."""
    if not isinstance(axis, Axis):
        raise TypeError(f"el eje de la sección es un road_axis.Axis, no {axis!r}")
    if not isinstance(grid, Grid):
        raise TypeError(f"la rejilla de la sección es una gis.Grid, no {grid!r}")
    return (_width(carriageway_m, "la calzada", zero=False), _width(shoulder_m, "el arcén", zero=True), _width(berm_m, "el caballón", zero=True))


# --- El terreno a los lados del eje ---------------------------------------------------------------------------------------


def sample_terrain(terrain: np.ndarray, grid: Grid, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """La cota de ``terrain`` (la superficie de la rejilla entera, m; ``NaN``, sin dato) en los puntos absolutos ``(x, y)`` (float64, de la misma forma), por
    **interpolación bilineal** entre los cuatro centros de celda vecinos (la misma regla que ``gis.raster.sample``): ``NaN`` fuera de los centros de la rejilla o si falta un
    vecino de peso no nulo; un punto en un centro toma su cota. Sin bucles; las entradas no se modifican."""
    fx = (np.asarray(x, dtype=np.float64) - grid.west) / grid.dx - 0.5
    fy = (grid.north - np.asarray(y, dtype=np.float64)) / grid.dy - 0.5
    with np.errstate(invalid="ignore"):
        inside = (fx >= 0.0) & (fx <= grid.ncols - 1) & (fy >= 0.0) & (fy <= grid.nrows - 1)
    fx, fy = np.where(inside, fx, 0.0), np.where(inside, fy, 0.0)
    col0 = np.minimum(np.floor(fx).astype(np.intp), max(grid.ncols - 2, 0))
    row0 = np.minimum(np.floor(fy).astype(np.intp), max(grid.nrows - 2, 0))
    col1, row1 = np.minimum(col0 + 1, grid.ncols - 1), np.minimum(row0 + 1, grid.nrows - 1)
    tx, ty = fx - col0, fy - row0
    with np.errstate(invalid="ignore"):
        upper = np.where(tx > 0.0, (1.0 - tx) * terrain[row0, col0] + tx * terrain[row0, col1], terrain[row0, col0])
        lower = np.where(tx > 0.0, (1.0 - tx) * terrain[row1, col0] + tx * terrain[row1, col1], terrain[row1, col0])
        found = np.where(ty > 0.0, (1.0 - ty) * upper + ty * lower, upper)
    found[~inside] = np.nan
    return found  # type: ignore[no-any-return]


# --- El resultado -------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class Section:
    """La sección de una pista (RF-017-20) en la ventana ``window`` (filas y columnas de la rejilla; todas las rejillas de abajo son de su forma y **de solo lectura**):
    ``cells`` (la huella: calzada, arcén y caballón; booleana), ``kind`` (la clase de cada celda, :class:`SectionClass`, ``int8``; 0 fuera), ``side`` (el lado de cada celda
    en el sentido de la marcha, :data:`RIGHT` o :data:`LEFT`, ``int8``; 0 fuera), ``sigma`` (la abscisa σ de la celda a lo largo del eje, m: **la del eje, de arco**, la de
    las estaciones de la rasante; ``NaN`` fuera) y ``lateral`` (la distancia con signo al eje, m, **positiva a la derecha**; ``NaN`` fuera).

    ``carriageway_m``, ``shoulder_m`` y ``berm_m`` son los anchos con que se calculó; ``length_m``, la longitud medida de la huella (el máximo menos el mínimo de la abscisa
    sin recortar de sus celdas: error 20, la del eje ± 1 celda, no los 211,5 m de un *buffer*; 0 sin celdas); ``axis_length_m``, la del eje y ``cell_area_m2``, el área de
    una celda. :meth:`levels` da la cota de cada celda."""

    window: tuple[slice, slice]
    cells: np.ndarray
    kind: np.ndarray
    side: np.ndarray
    sigma: np.ndarray
    lateral: np.ndarray
    carriageway_m: float
    shoulder_m: float
    berm_m: float
    length_m: float
    axis_length_m: float
    cell_area_m2: float

    @property
    def cell_count(self) -> int:
        """Las celdas de la sección."""
        return int(np.count_nonzero(self.cells))

    @property
    def area_m2(self) -> float:
        """El área de la sección (m²): sus celdas por el área de una."""
        return self.cell_count * self.cell_area_m2

    def count_of(self, kind: SectionClass) -> int:
        """Las celdas de la clase ``kind`` (con ``SectionClass.OUTSIDE``, las de la ventana que no son de la sección)."""
        return int(np.count_nonzero(self.kind == int(kind)))

    def levels(self, stations: np.ndarray, line: np.ndarray) -> np.ndarray:
        """La cota de cada celda de la sección (m, float64 de la forma de la ventana; ``NaN`` fuera): la de la rasante ``line`` (una cota por estación de ``stations``,
        crecientes y de la misma longitud) en su abscisa σ, ``np.interp``. **El caballón no tiene altura**: sus celdas van a la cota de la rasante como las de la calzada.
        ``ValueError`` si las estaciones y la rasante no son dos vectores de la misma longitud (al menos dos)."""
        s, z = np.asarray(stations, dtype=np.float64), np.asarray(line, dtype=np.float64)
        if s.ndim != 1 or s.shape != z.shape or s.size < 2:
            raise ValueError(f"las estaciones y la rasante son dos vectores de la misma longitud (al menos dos): formas {s.shape} y {z.shape}")
        found = np.full(self.cells.shape, np.nan)
        found[self.cells] = np.interp(self.sigma[self.cells], s, z)
        return found


# --- La huella ----------------------------------------------------------------------------------------------------------


def _dense(axis: Axis) -> tuple[np.ndarray, np.ndarray]:
    """El eje denso: sus estaciones cada :data:`DENSE_STEP_M` m (con una última en el extremo) y sus puntos absolutos ``(n, 2)``."""
    stations = stations_for(axis.length_m, DENSE_STEP_M)
    points, _ = axis.sample(stations)
    return points, stations


def section_window(axis: Axis, carriageway_m: float, shoulder_m: float, berm_m: float, grid: Grid) -> tuple[slice, slice]:
    """La caja del corredor de la sección en la rejilla (``quarry.corridor_window``: la del eje denso ampliada en la semianchura máxima ``f·A/2 + máx(arcén, caballón)``,
    recortada a la rejilla): contiene toda la huella; la ventana por defecto de :func:`section_cells`. Quien necesita más (el alcance del borde) la amplía él."""
    carriageway, shoulder, berm = _checked(axis, carriageway_m, shoulder_m, berm_m, grid)
    points, _ = _dense(axis)
    return corridor_window([points], carriageway / 2.0 + max(shoulder, berm), grid)


def section_steps(axis: Axis, carriageway_m: float, shoulder_m: float, berm_m: float, terrain: np.ndarray, grid: Grid,
                  window: tuple[slice, slice] | None) -> Generator[None, None, Section]:
    """**A6 y A7** (RF-017-20): la sección de la pista de eje ``axis`` (un :class:`~.road_axis.Axis`) con la calzada ``carriageway_m`` (*f·A*, m), el arcén ``shoulder_m`` y el
    caballón ``berm_m`` (m, no negativos) sobre el terreno de partida ``terrain`` (la superficie de la rejilla ``grid`` entera, float64 de su forma; ``NaN``, sin dato), **por
    unidades** (cada ``yield``, una; para componerlas con ``pace_units``) y con la :class:`Section` en ``StopIteration.value``. ``window`` (filas y columnas de ``grid``;
    ``None``: la caja del corredor, :func:`section_window`) es donde se mide: lo que cae fuera de ella no está en la sección. :class:`TypeError` o :class:`ValueError` si una
    entrada no es de su forma (errores del programa: la preparación de la pista rechazó antes, con su perfil, su campo y su valor).

    El eje denso se muestrea cada :data:`DENSE_STEP_M` m; ``quarry.axis_abscissa_units`` da la abscisa de las celdas a ≤ la semianchura máxima del eje y de extremos planos; de
    cada una, el tramo del eje denso que empieza en su abscisa o antes (en un vértice, el siguiente) da la tangente, la distancia lateral con signo (positiva a la derecha) y
    el punto del eje, y el terreno a ``±f·A/2`` de él (:func:`sample_terrain`) decide el lado del arcén (a la derecha solo si es **estrictamente** más alto: con cotas iguales o
    sin dato, el caballón va a la derecha). La abscisa σ de la sección es la del eje (longitud de arco: la poligonal densa se pasa a las estaciones del eje por interpolación
    lineal entre sus vértices). Las entradas no se modifican."""
    carriageway, shoulder, berm = _checked(axis, carriageway_m, shoulder_m, berm_m, grid)
    ground = _ground(terrain, grid)
    half = carriageway / 2.0
    points, stations = _dense(axis)
    box = corridor_window([points], half + max(shoulder, berm), grid) if window is None else _window(window, grid)
    step = np.diff(points, axis=0)
    length = np.hypot(step[:, 0], step[:, 1])
    unit = step / length[:, None]
    chord = np.concatenate(([0.0], np.cumsum(length)))
    last = len(length) - 1
    yield
    sigma_chord, reach = yield from axis_abscissa_units([points], half + max(shoulder, berm), grid, box)
    rows, cols = np.nonzero(np.isfinite(sigma_chord))
    shape = sigma_chord.shape
    cells = np.zeros(shape, dtype=bool)
    kind = np.zeros(shape, dtype=np.int8)
    side = np.zeros(shape, dtype=np.int8)
    sigma = np.full(shape, np.nan)
    lateral = np.full(shape, np.nan)
    low, high = math.inf, -math.inf
    yield
    for first in range(0, rows.size, _BLOCK_CELLS):
        r, c = rows[first:first + _BLOCK_CELLS], cols[first:first + _BLOCK_CELLS]
        s = sigma_chord[r, c]
        index = np.clip(np.searchsorted(chord, s, side="right") - 1, 0, last)
        ux, uy = unit[index, 0], unit[index, 1]
        x = grid.west + (c + (box[1].start + 0.5)) * grid.dx
        y = grid.north - (r + (box[0].start + 0.5)) * grid.dy
        offset = (x - points[index, 0]) * uy - (y - points[index, 1]) * ux  # positiva a la derecha: el producto vectorial por la tangente
        along = s - chord[index]  # entre 0 y la longitud del tramo (el último tramo incluye su extremo)
        qx, qy = points[index, 0] + along * ux, points[index, 1] + along * uy  # el punto del eje a la abscisa de la celda
        right_x, right_y = uy * half, -ux * half
        shoulder_right = sample_terrain(ground, grid, qx + right_x, qy + right_y) > sample_terrain(ground, grid, qx - right_x, qy - right_y)
        on_right = offset >= 0.0
        on_shoulder = on_right == shoulder_right
        distance = np.abs(offset)
        keep = distance <= half + np.where(on_shoulder, shoulder, berm) + _EDGE_TOL_M
        classes = np.where(distance <= half + _EDGE_TOL_M, int(SectionClass.CARRIAGEWAY),
                           np.where(on_shoulder, int(SectionClass.SHOULDER), int(SectionClass.BERM)))
        r, c = r[keep], c[keep]
        cells[r, c] = True
        kind[r, c] = classes[keep]
        side[r, c] = np.where(on_right[keep], RIGHT, LEFT)
        sigma[r, c] = np.interp(s[keep], chord, stations)
        lateral[r, c] = offset[keep]
        if r.size:
            found = np.interp(reach[r, c], chord, stations)
            low, high = min(low, float(found.min())), max(high, float(found.max()))
        yield
    return Section(
        window=box, cells=_frozen(cells), kind=_frozen(kind), side=_frozen(side), sigma=_frozen(sigma), lateral=_frozen(lateral), carriageway_m=carriageway,
        shoulder_m=shoulder, berm_m=berm, length_m=high - low if high >= low else 0.0, axis_length_m=axis.length_m, cell_area_m2=grid.cell_area)


def section_cells(axis: Axis, carriageway_m: float, shoulder_m: float, berm_m: float, terrain: np.ndarray, grid: Grid,
                  window: tuple[slice, slice] | None = None) -> Section:
    """:func:`section_steps` llevada hasta el final (RF-017-20): la sección de la pista de eje ``axis`` con sus tres anchos sobre el terreno de partida ``terrain``
    en la ventana ``window`` (``None``: la caja del corredor). El mismo resultado, bit a bit, que por pasos."""
    steps = section_steps(axis, carriageway_m, shoulder_m, berm_m, terrain, grid, window)
    while True:
        try:
            next(steps)
        except StopIteration as done:
            found: Any = done.value
            return found  # type: ignore[no-any-return]
