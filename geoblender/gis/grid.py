# SPDX-License-Identifier: GPL-3.0-or-later
"""Rejillas de paso exacto (spec 006; RF-006-01, RF-006-02; plan 006 §5.3.2 y §5.4 A1;
ADR-0014).

Todas las coordenadas de este módulo son **absolutas** (CRS del proyecto, m, float64).

- :class:`Grid`: la geometría de una rejilla orientada al norte (oeste, norte, pasos y
  número de columnas y filas, filas de norte a sur), con su área de celda **exacta**
  (|dx·dy|: el cuadrado del paso en las del proyecto, el producto de los dos pasos de su
  georreferencia en las importadas; nunca un valor nominal, RF-006-02), su georreferencia,
  su extensión, los centros de celda y la comparación bit a bit.
- :func:`validate_step`: el paso de una rejilla del proyecto, múltiplo de 0,5 m entre 0,5
  y 5 m, o ``gis.step_invalid`` con el valor.
- :func:`aligned_grid`: la rejilla del proyecto que cubre una extensión, ampliada hacia fuera
  a múltiplos de la unidad de alineación del paso (RF-006-01).
- :func:`project_grid`: la rejilla de la ventana de trabajo, que ya viene alineada
  (RF-002-24); una ventana sin alinear es ``gis.window_not_aligned``.
- :func:`volume_between` y :class:`VolumeResult`: el volumen entre dos superficies en la
  misma rejilla, celda a celda con su área exacta, en corte, relleno y neto, con el área
  con y sin dato (RF-006-03; plan §5.4 A2).

La ventana (``Window``), la unidad de alineación (``alignment_unit``) y la alineación de una
ventana (``align_window``) son de ``core.georef`` (spec 002) y no se redefinen aquí: así la
rejilla del proyecto coincide celda a celda con la ventana de trabajo.
"""

from __future__ import annotations

import math
import operator
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from ..core.errors import ValidationError
from ..core.georef import VerticalRef, Window, align_window, alignment_unit, check_grid_step
from .messages import GisError, format_value

if TYPE_CHECKING:
    from .raster import Raster

__all__ = [
    "Grid",
    "VolumeResult",
    "aligned_grid",
    "project_grid",
    "validate_step",
    "volume_between",
]

_GRID = "Rejilla del proyecto"
_STEP_FIELD = "paso de rejilla"
_WINDOW = "Ventana de trabajo"
_EDGES = ("xmin", "ymin", "xmax", "ymax")
_VOLUME = "Volumen entre superficies"
# Atributo de la rejilla → cómo se nombra en el detalle de gis.grid_mismatch.
_GEOMETRY = {
    "west": "oeste",
    "north": "norte",
    "dx": "paso en X",
    "dy": "paso en Y",
    "ncols": "columnas",
    "nrows": "filas",
}


def _real(value: object, name: str) -> float:
    """``value`` como float de Python (float64) si es un número real finito."""
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise TypeError(f"Grid.{name} debe ser un número, no {type(value).__name__}")
    number = float(value) + 0.0  # + 0,0: −0,0 pasa a 0,0 (comparación bit a bit)
    if not math.isfinite(number):
        raise ValueError(f"Grid.{name} debe ser un número finito, no {number!r}")
    return number


def _count(value: object, name: str) -> int:
    """``value`` como entero de Python si es un entero ≥ 1."""
    if isinstance(value, bool | np.bool_):
        raise TypeError(f"Grid.{name} debe ser un número entero, no {value!r}")
    try:
        count = operator.index(value)  # type: ignore[arg-type]
    except TypeError:
        raise TypeError(
            f"Grid.{name} debe ser un número entero, no {type(value).__name__}"
        ) from None
    if count < 1:
        raise ValueError(f"Grid.{name} debe ser al menos 1, no {count}")
    return count


@dataclass(frozen=True, slots=True)
class Grid:
    """Rejilla orientada al norte, en coordenadas **absolutas** (m, float64): esquina
    noroeste (``west``, ``north``), paso en X (``dx``) y en Y (``dy``), ambos positivos, y
    ``ncols`` × ``nrows`` celdas; la fila 0 es la del norte.

    Una rejilla mal formada (sin celdas, con un paso nulo, negativo o no finito, o con
    coordenadas no finitas) es un error del programa (``ValueError`` o ``TypeError``): quien
    lee un fichero la valida antes, con un error para el usuario.
    """

    west: float
    north: float
    dx: float
    dy: float
    ncols: int
    nrows: int

    def __post_init__(self) -> None:
        for name in ("west", "north", "dx", "dy"):
            object.__setattr__(self, name, _real(getattr(self, name), name))
        for name in ("dx", "dy"):
            if getattr(self, name) <= 0.0:
                raise ValueError(
                    f"Grid.{name} debe ser positivo (filas de norte a sur), no "
                    f"{getattr(self, name)!r}"
                )
        for name in ("ncols", "nrows"):
            object.__setattr__(self, name, _count(getattr(self, name), name))

    @property
    def cell_area(self) -> float:
        """Área de una celda (m²): |dx·dy|, exacta (RF-006-02)."""
        return abs(self.dx * self.dy)

    @property
    def transform(self) -> tuple[float, float, float, float, float, float]:
        """Georreferencia afín ``(a, b, c, d, e, f)`` = ``(dx, 0, oeste, 0, −dy, norte)``:
        x = a·columna + b·fila + c, y = d·columna + e·fila + f (esquinas de celda)."""
        return (self.dx, 0.0, self.west, 0.0, -self.dy, self.north)

    @property
    def shape(self) -> tuple[int, int]:
        """``(nrows, ncols)``: la forma del array de valores."""
        return (self.nrows, self.ncols)

    @property
    def extent(self) -> Window:
        """La extensión absoluta (m) que cubren las celdas, como ``core.georef.Window``."""
        return Window(
            self.west,
            self.north - self.nrows * self.dy,
            self.west + self.ncols * self.dx,
            self.north,
        )

    def centers(self, rows: slice | None = None) -> tuple[np.ndarray, np.ndarray]:
        """Centros de celda ``(x, y)`` absolutos en float64, dos arrays de forma
        ``(filas, ncols)`` con las filas de norte a sur; ``rows`` elige una banda de filas
        (todas si es ``None``), para recorrer una rejilla grande por partes."""
        selected = range(self.nrows) if rows is None else range(self.nrows)[rows]
        x = self.west + (np.arange(self.ncols, dtype=np.float64) + 0.5) * self.dx
        y = self.north - (np.asarray(selected, dtype=np.float64) + 0.5) * self.dy
        xx, yy = np.meshgrid(x, y)
        return xx, yy

    def same_geometry(self, other: object) -> bool:
        """``True`` si ``other`` es una :class:`Grid` con la misma esquina, los mismos pasos
        y el mismo número de columnas y filas, bit a bit (sin tolerancia)."""
        if not isinstance(other, Grid):
            return False
        return (
            self.west == other.west
            and self.north == other.north
            and self.dx == other.dx
            and self.dy == other.dy
            and self.ncols == other.ncols
            and self.nrows == other.nrows
        )


def validate_step(step_m: float) -> None:
    """Comprueba que ``step_m`` sea un paso de rejilla del proyecto: múltiplo de 0,5 m entre
    0,5 y 5 m (RF-006-01; la regla es la de ``core.georef.check_grid_step``, RF-002-03).
    Si no, :class:`GisError` ``gis.step_invalid`` con el valor."""
    try:
        check_grid_step(step_m)
    except ValidationError:
        raise GisError("gis.step_invalid", obj=_GRID, field=_STEP_FIELD, value=step_m) from None


def _cells(length: float, step_m: float) -> int:
    """Número de celdas de paso ``step_m`` en ``length`` m, exacto: ``length`` es múltiplo
    de la unidad de alineación, que lo es del paso (plan §5.4 A1)."""
    halves = round(step_m * 2)  # paso = halves / 2, exacto
    doubled = round(length * 2)
    if doubled != length * 2 or doubled % halves:  # inalcanzable con bordes alineados
        raise ValueError(f"{length!r} m no es múltiplo del paso {step_m!r} m")
    return doubled // halves


def project_grid(window: Window, step_m: float) -> Grid:
    """La rejilla del proyecto que cubre exactamente ``window``, la ventana de trabajo, que ya
    viene alineada a ``alignment_unit(step_m)`` (RF-002-24), con celdas de ``step_m`` ×
    ``step_m`` m (RF-006-01). Errores: ``gis.step_invalid`` (paso) y
    ``gis.window_not_aligned`` (un borde que no es múltiplo de la unidad de alineación)."""
    validate_step(step_m)
    step = float(step_m)
    unit = alignment_unit(step)
    for edge in _EDGES:
        value = getattr(window, edge)
        if math.fmod(value, unit) != 0.0:
            raise GisError(
                "gis.window_not_aligned",
                obj=_WINDOW,
                field=edge,
                value=value,
                edge=edge,
                step=step,
                unit=unit,
            )
    return Grid(
        west=window.xmin,
        north=window.ymax,
        dx=step,
        dy=step,
        ncols=_cells(window.xmax - window.xmin, step),
        nrows=_cells(window.ymax - window.ymin, step),
    )


def aligned_grid(extent: Window, step_m: float) -> Grid:
    """La rejilla del proyecto de paso ``step_m`` que cubre ``extent``: sus bordes se amplían
    hacia fuera a múltiplos de ``alignment_unit(step_m)`` (oeste y sur, hacia abajo; este y
    norte, hacia arriba; plan §5.4 A1), igual que la ventana de trabajo (RF-006-01,
    RF-002-24). Error: ``gis.step_invalid``."""
    validate_step(step_m)
    return project_grid(align_window(extent, step_m), step_m)


@dataclass(frozen=True, slots=True)
class VolumeResult:
    """Volumen entre dos superficies (RF-006-03): corte (``upper`` por encima de ``lower``),
    relleno y neto (corte − relleno) en m³; área con dato en las dos superficies y área sin
    dato en alguna de ellas, dentro de la máscara si la hay, en m²; y el área de celda
    exacta con la que se calcularon (|dx·dy|, RF-006-02)."""

    cut_m3: float
    fill_m3: float
    net_m3: float
    area_m2: float
    nodata_area_m2: float
    cell_area_m2: float


def _vertical_label(vertical: VerticalRef) -> str:
    """Una referencia vertical como la lee una persona: «EPSG:5782» o «Referencia local
    (NP-0 del plano 3)»."""
    if vertical.epsg is not None:
        return f"EPSG:{vertical.epsg}"
    return f"{vertical.name} ({vertical.note})" if vertical.note else vertical.name


def _mismatch(upper: Raster, lower: Raster) -> tuple[str, object, str] | None:
    """La primera diferencia entre las dos superficies que impide cubicarlas celda a celda
    (campo, valor de ``lower`` y detalle en español), o ``None`` si están en la misma
    rejilla (bit a bit), el mismo CRS y la misma referencia vertical."""
    if not upper.grid.same_geometry(lower.grid):
        for field, label in _GEOMETRY.items():
            first, second = getattr(upper.grid, field), getattr(lower.grid, field)
            if first != second:
                detail = f"{label} {format_value(first)} frente a {format_value(second)}"
                return field, second, detail
    if upper.crs != lower.crs:
        detail = f"CRS EPSG:{upper.crs.epsg} frente a EPSG:{lower.crs.epsg}"
        return "crs", lower.crs.epsg, detail
    if upper.vertical != lower.vertical:
        first, second = _vertical_label(upper.vertical), _vertical_label(lower.vertical)
        return "vertical", second, f"referencia vertical {first} frente a {second}"
    return None


def _min_thickness(value: object) -> float:
    """El espesor mínimo (m) como float: un número finito ≥ 0 (si no, error del programa)."""
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise TypeError(f"min_thickness_m debe ser un número, no {type(value).__name__}")
    thickness = float(value)
    if not math.isfinite(thickness) or thickness < 0.0:
        raise ValueError(f"min_thickness_m debe ser un número finito ≥ 0, no {thickness!r}")
    return thickness


def volume_between(
    upper: Raster,
    lower: Raster,
    *,
    mask: np.ndarray | None = None,
    min_thickness_m: float = 0.0,
    names: tuple[str, str] = ("superior", "inferior"),
) -> VolumeResult:
    """Volumen entre ``upper`` y ``lower``, dos superficies en la misma rejilla, celda a
    celda con su área exacta |dx·dy| (RF-006-03, RF-006-02; plan §5.4 A2).

    Con d = upper − lower y e = ``min_thickness_m``: corte = Σ max(d − e, 0)·A y relleno =
    Σ max(−d − e, 0)·A (lo que no pasa de e no cuenta), sumados con ``numpy.sum`` en float64
    (por pares) sobre las celdas con dato en las dos superficies y, si hay ``mask`` (booleana,
    de la forma de la rejilla), dentro de ella; neto = corte − relleno. Una cota no finita
    (NaN = sin dato) en cualquiera de las dos deja la celda fuera del volumen y la cuenta en
    el área sin dato (si está dentro de la máscara). ``names`` son los nombres de las dos
    superficies en el mensaje de error. Las entradas no se modifican.

    Error: ``gis.grid_mismatch`` si las rejillas no tienen la misma geometría, bit a bit, o
    las superficies no están en el mismo CRS o la misma referencia vertical. Un espesor
    negativo o no finito, o una máscara que no es booleana o tiene otra forma, son errores
    del programa (``ValueError``, ``TypeError``).
    """
    from .raster import Raster  # aquí: gis.raster importa Grid de este módulo

    for surface in (upper, lower):
        if not isinstance(surface, Raster):
            raise TypeError(f"se esperaba un Raster, no {type(surface).__name__}")
    thickness = _min_thickness(min_thickness_m)
    different = _mismatch(upper, lower)
    if different is not None:
        field, value, detail = different
        raise GisError(
            "gis.grid_mismatch",
            obj=_VOLUME,
            field=field,
            value=value,
            upper=names[0],
            lower=names[1],
            detail=detail,
        )
    valid = np.isfinite(upper.values) & np.isfinite(lower.values)
    if mask is None:
        considered = valid.size
    else:
        if not isinstance(mask, np.ndarray) or mask.dtype != np.bool_:
            found = getattr(mask, "dtype", type(mask).__name__)
            raise TypeError(f"la máscara debe ser un array booleano, no {found}")
        if mask.shape != valid.shape:
            raise ValueError(
                f"la máscara tiene la forma {mask.shape} y la rejilla, {valid.shape}"
            )
        valid &= mask
        considered = int(np.count_nonzero(mask))
    with_data = int(np.count_nonzero(valid))
    difference = upper.values[valid] - lower.values[valid]  # 1-D, float64
    cut = float(np.sum(np.maximum(difference - thickness, 0.0)))
    fill = float(np.sum(np.maximum(-difference - thickness, 0.0)))
    area = upper.grid.cell_area
    cut_m3 = cut * area
    fill_m3 = fill * area
    return VolumeResult(
        cut_m3=cut_m3,
        fill_m3=fill_m3,
        net_m3=cut_m3 - fill_m3,
        area_m2=with_data * area,
        nodata_area_m2=(considered - with_data) * area,
        cell_area_m2=area,
    )
