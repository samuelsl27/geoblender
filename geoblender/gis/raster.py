# SPDX-License-Identifier: GPL-3.0-or-later
"""Superficies en rejilla (spec 006; plan 006 §5.3.2; ADR-0005, ADR-0014).

- :class:`Raster`: una superficie en una :class:`~.grid.Grid` del proyecto o importada: sus
  cotas en float64 (m; NaN = sin dato), una por celda, con las filas de norte a sur, y el
  CRS horizontal y la referencia vertical a los que se refieren (``core.georef``, spec
  002), que nunca se suponen (constitución, principio 6).
- :class:`RasterSource`: un MDT leído de un fichero (GeoTIFF, ASC o XYZ en malla) en su
  rejilla de origen, con lo que declara la fuente: tipo de dato, sin dato, *PixelIsPoint*,
  CRS y referencia vertical (``None`` si no los declara: se piden, RF-006-04).
- :func:`sample`: la cota de una superficie en puntos sueltos (el contrato para la 005,
  DH-W05: la cota de boca de un sondeo frente al MDT), con la bilineal de
  ``gis.resample`` (la misma función que la rejilla del proyecto, RF-006-11) o con la celda
  que contiene el punto.

Las coordenadas de la rejilla son **absolutas** (CRS del proyecto, m, float64).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.georef import CrsRef, VerticalRef
from .grid import Grid

__all__ = ["SAMPLE_METHODS", "Raster", "RasterSource", "sample"]

SAMPLE_METHODS = ("bilinear", "nearest")
"""Los métodos de :func:`sample`: la bilineal y la celda que contiene el punto."""


def _check_surface(owner: str, grid: object, values: object) -> None:
    """Rejilla y valores bien formados (``TypeError``/``ValueError``: error del programa)."""
    if not isinstance(grid, Grid):
        raise TypeError(f"{owner}.grid debe ser una Grid, no {type(grid).__name__}")
    if not isinstance(values, np.ndarray) or values.dtype != np.float64:
        found = getattr(values, "dtype", type(values).__name__)
        raise TypeError(f"{owner}.values debe ser un array float64, no {found}")
    if values.shape != grid.shape:
        raise ValueError(
            f"{owner}.values tiene la forma {values.shape} y su rejilla, {grid.shape}"
        )


@dataclass(frozen=True, slots=True, eq=False)
class Raster:
    """Superficie en rejilla: ``grid`` (absoluta), ``values`` (cotas en m, float64, de forma
    ``grid.shape``, fila 0 al norte; NaN = sin dato), ``crs`` y ``vertical``.

    ``values`` no se copia: quien crea el ráster no debe modificarlo después. Uno mal formado
    (otro tipo de datos, otra forma, una rejilla, un CRS o una referencia vertical que no lo
    son) es un error del programa (``TypeError`` o ``ValueError``): los lectores validan antes
    la fuente, con un error para el usuario. La igualdad es la identidad (``eq=False``): dos
    rásteres se comparan por su rejilla y sus valores, explícitamente.
    """

    grid: Grid
    values: np.ndarray
    crs: CrsRef
    vertical: VerticalRef

    def __post_init__(self) -> None:
        _check_surface("Raster", self.grid, self.values)
        if not isinstance(self.crs, CrsRef):
            raise TypeError(f"Raster.crs debe ser un CrsRef, no {type(self.crs).__name__}")
        if not isinstance(self.vertical, VerticalRef):
            raise TypeError(
                f"Raster.vertical debe ser un VerticalRef, no {type(self.vertical).__name__}"
            )


@dataclass(frozen=True, slots=True, eq=False)
class RasterSource:
    """Un MDT leído de un fichero, en su rejilla de origen (RF-006-04, RF-006-08).

    - ``grid`` y ``values``: la rejilla que declara la fuente (absoluta; con
      *PixelIsPoint*, ya desplazada medio paso para que cada celda sea un área) y sus cotas
      en float64, cada una **igual al valor de la fuente** (un Float32 pasa a float64 sin
      cambio), con el sin dato declarado y los bloques que faltan como NaN.
    - ``source_dtype``: el tipo de las muestras en el fichero, con el nombre de numpy
      (``"float32"``, ``"int16"``…).
    - ``nodata_value``: el valor sin dato que declara la fuente (``GDAL_NODATA``,
      ``NODATA_value``; NaN si declara ``nan``), o ``None`` si no declara ninguno.
    - ``pixel_is_point``: la fuente referencia los centros de las celdas.
    - ``declared_crs`` y ``declared_vertical``: el CRS horizontal y la referencia vertical
      que declara la fuente, del catálogo de la 002; ``None`` si no los declara, y entonces
      los declara el usuario antes de importar (RF-006-04): nunca se suponen.
    - ``encoding``: cómo está guardada la fuente, para el informe (formato, tipo,
      compresión y organización de un GeoTIFF; la codificación de un texto).
    - ``notes``: avisos en español para el informe (``gis.pixel_is_point``…).

    El plan (§5.3.2) nombra su primer campo ``raster``; un :class:`Raster` lleva siempre CRS
    y referencia vertical, que la fuente puede no declarar, así que aquí son ``grid`` y
    ``values``, y el ráster se crea cuando están declarados (por la fuente o por el
    usuario): ``Raster(source.grid, source.values, crs, vertical)``. ``values`` no se copia.
    """

    grid: Grid
    values: np.ndarray
    source_dtype: str
    nodata_value: float | None
    pixel_is_point: bool
    declared_crs: CrsRef | None
    declared_vertical: VerticalRef | None
    encoding: str
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _check_surface("RasterSource", self.grid, self.values)
        if self.declared_crs is not None and not isinstance(self.declared_crs, CrsRef):
            raise TypeError(
                "RasterSource.declared_crs debe ser un CrsRef o None, no "
                f"{type(self.declared_crs).__name__}"
            )
        if self.declared_vertical is not None and not isinstance(
            self.declared_vertical, VerticalRef
        ):
            raise TypeError(
                "RasterSource.declared_vertical debe ser un VerticalRef o None, no "
                f"{type(self.declared_vertical).__name__}"
            )
        if not isinstance(self.notes, tuple) or not all(
            isinstance(note, str) for note in self.notes
        ):
            raise TypeError("RasterSource.notes debe ser una tupla de textos")


def sample(raster: Raster, xy: np.ndarray, *, method: str = "bilinear") -> np.ndarray:
    """Las cotas de ``raster`` en los puntos ``xy`` (X e Y ABSOLUTAS del CRS de ``raster``,
    en la última dimensión: forma ``(n, 2)``, o ``(2,)`` para uno solo), en float64 y con la
    forma de ``xy`` sin su última dimensión (plan 006 §5.3.2; para la 005, DH-W05).

    - ``"bilinear"`` (por defecto): la interpolación entre los cuatro centros vecinos, con la
      regla de RF-006-11 y la misma función que ``resample_to_grid`` (``gis.resample``): un
      punto en un centro toma su cota bit a bit; es NaN si le falta un vecino de peso no nulo
      (fuera de los centros de la rejilla, sin dato, ±∞) o si una coordenada no es finita.
    - ``"nearest"``: la cota de la celda que contiene el punto (en un borde entre dos celdas,
      la del este o la del sur; los bordes exteriores son de la rejilla); NaN fuera de la
      rejilla, en una celda sin dato o con una coordenada que no es finita.

    Las entradas no se modifican. Un método que no es de :data:`SAMPLE_METHODS`, unas
    coordenadas sin X e Y en su última dimensión (``ValueError``) o una superficie que no es
    un :class:`Raster` (``TypeError``) son errores del programa."""
    if not isinstance(raster, Raster):
        raise TypeError(f"sample: se esperaba un Raster, no {type(raster).__name__}")
    if not isinstance(method, str) or method not in SAMPLE_METHODS:
        raise ValueError(f"método de muestreo {method!r}: debe ser «bilinear» o «nearest»")
    points = np.asarray(xy, dtype=np.float64)
    if points.ndim == 0 or points.shape[-1] != 2:
        raise ValueError(
            "sample: xy lleva X e Y en su última dimensión (forma (n, 2)), no la forma "
            f"{points.shape}"
        )
    x, y = points[..., 0].ravel(), points[..., 1].ravel()
    if method == "bilinear":
        from .resample import _sample  # aquí: gis.resample importa Raster de este módulo

        found = _sample(raster, x, y)
    else:
        found = _nearest(raster, x, y)
    return found.reshape(points.shape[:-1])


def _nearest(raster: Raster, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """La cota de la celda de ``raster`` que contiene cada punto (``x``, ``y``) ABSOLUTO;
    NaN fuera, sin dato o con una coordenada que no es finita (NaN no pasa las
    comparaciones)."""
    grid = raster.grid
    with np.errstate(invalid="ignore", over="ignore"):
        fx = (x - grid.west) / grid.dx
        fy = (grid.north - y) / grid.dy
        inside = (fx >= 0.0) & (fx <= grid.ncols) & (fy >= 0.0) & (fy <= grid.nrows)
    column = np.clip(np.floor(np.where(inside, fx, 0.0)), 0, grid.ncols - 1).astype(np.int64)
    row = np.clip(np.floor(np.where(inside, fy, 0.0)), 0, grid.nrows - 1).astype(np.int64)
    found = raster.values[row, column]  # indexado por arrays: una copia
    found[~(inside & np.isfinite(found))] = np.nan
    return found
