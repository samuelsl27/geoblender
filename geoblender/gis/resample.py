# SPDX-License-Identifier: GPL-3.0-or-later
"""Remuestreo de una superficie a la rejilla del proyecto (spec 006; RF-006-05, RF-006-11,
RF-006-30; plan 006 §5.3.2, §5.4 A6 y §6 D6 y D7; ADR-0014).

Todas las coordenadas de este módulo son **absolutas** (m, float64). En el remuestreo, la
fuente y la rejilla destino están en el mismo CRS; en la reproyección
(:func:`reproject_to_grid`, RF-006-05), la fuente está en el suyo y la rejilla en el del
proyecto, y las transformaciones llevan los puntos de uno a otro.

- :func:`choose_method`: el método por defecto (RF-006-11; plan §6 D6): la media ponderada
  por área si el paso de la fuente es menor o igual que el de la rejilla en X y en Y (bajar
  o mantener la resolución conserva el volumen), y la bilineal si alguno es mayor (subir la
  resolución con la media daría escalones).
- :func:`resample_to_grid`: las cotas de cada celda destino con el método declarado.

  *Media por área* (separable y exacta, A6): en cada eje, los bordes de las celdas de origen
  y de destino parten el solape en tramos con su longitud, su celda de origen y su celda de
  destino; S = Σ z·w y W = Σ w sobre las celdas de origen con dato, primero en columnas y
  luego en filas, con w el área de solape en fracción de la celda destino. La celda vale S/W
  si W, el área cubierta por celdas válidas, alcanza la fracción mínima
  (``gis.resample.min_valid_fraction``, 1 por defecto: toda la celda, D-4); si no, queda sin
  dato (NaN). Nunca se rellena: con una fracción menor que 1, la cota es la media de lo
  cubierto. Una celda idéntica a una de origen tiene un solo tramo de peso 1 y sale con la
  misma cota, bit a bit. Sobre la zona totalmente cubierta conserva el volumen.

  *Bilineal*: cada centro destino en índices fraccionarios de la fuente
  (desplazamiento + (i + ½)·razón de pasos − ½), y la interpolación entre los 4 centros
  vecinos. La celda queda sin dato si le falta un vecino de peso no nulo (fuera de la fuente
  o sin dato); la que cae en un centro de origen toma su cota, bit a bit, sin necesitar a sus
  vecinos. La fracción mínima es de la media: en la bilineal manda la regla de los vecinos
  (RF-006-11).
- :func:`resample_classes_to_grid`: una rejilla de clases (códigos enteros) con la moda por
  área (RF-006-30): los mismos tramos que la media; el área de cada código en cada celda
  destino (``numpy.bincount`` sobre celda y código) y la clase de mayor área, con empate el
  código menor; nunca un código que no esté en la fuente. Misma regla de cobertura que la
  media.
- :func:`reproject_to_grid`: una superficie de otro CRS o de otro datum vertical,
  directamente en la rejilla del proyecto (RF-006-05; A6 y D7). Con la media, s × s
  subcentros por celda destino (s = ``gis.reproject.supersample``, 4) se llevan a la fuente
  con la transformación **inversa**, se interpolan allí con la bilineal (sin dato si les
  falta un vecino) y, si el datum vertical difiere, su cota pasa al del proyecto con la
  transformación **directa**; la celda vale la media de los subcentros válidos si estos son
  al menos la fracción mínima de los s²; si no, queda sin dato. Con la bilineal, un solo
  punto: el centro (s = 1). Solo con transformaciones de precisión conocida
  (``gis.transform_unknown_accuracy``, con los dos CRS); el informe cita la transformación
  directa y el submuestreo. Un punto que una transformación no puede llevar (∞: fuera de
  su rejilla) es sin dato.

Las cotas de la fuente que no son finitas (NaN, ±∞) son sin dato. Las entradas no se
modifican. Se calcula por bloques de filas destino (como mucho :data:`BLOCK_ITEMS` elementos
intermedios), con avance y cancelación tras cada bloque (RF-006-28); el reparto en bloques
no cambia el resultado.

:data:`CELL_TOLERANCE` (10⁻⁹ de celda) absorbe el redondeo de los bordes en float64 al
comparar la cobertura con la fracción mínima, al decidir un empate de la moda y al ver si un
centro destino cae en un centro de origen: no es un parámetro del método, sino el redondeo
de la aritmética (los bordes se calculan con un error del orden de 10⁻¹¹ celdas).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from ..core.georef import CrsRef, VerticalRef
from ..jobs.worker_api import JobCancelled
from . import params
from .crs import unknown_accuracy_error
from .grid import Grid
from .messages import GisError
from .ports import Cancelled, Progress, Transform, TransformInfo
from .raster import Raster
from .reports import ResampleReport

__all__ = [
    "BLOCK_ITEMS",
    "CELL_TOLERANCE",
    "PAIR_TOLERANCE_M",
    "ResampleMethod",
    "choose_method",
    "reproject_to_grid",
    "resample_classes_to_grid",
    "resample_to_grid",
]

BLOCK_ITEMS = 1 << 20
"""Tope de elementos intermedios de un bloque de filas destino (8 MiB por array en
float64); un bloque tiene al menos una fila. Las pruebas lo bajan para trocear."""

CELL_TOLERANCE = 1e-9
"""Redondeo admitido, en fracción de celda (véase el docstring del módulo)."""

PAIR_TOLERANCE_M = 0.001
"""Lo que puede separarse un punto de sí mismo al pasar por la transformación inversa y la
directa de una reproyección: una pareja de verdad lo devuelve con el redondeo de PROJ
(≪ 1 mm); una equivocada, desplazado por la transformación entera (decenas de metros)."""

MIN_VALID_FRACTION_KEY = "gis.resample.min_valid_fraction"
SUPERSAMPLE_KEY = "gis.reproject.supersample"
_CLASSES_FIELD = "código"


class ResampleMethod(StrEnum):
    """Método de remuestreo, con el nombre que lleva ``ResampleReport.method``."""

    AREA_MEAN = "area_mean"
    """Media ponderada por área (cotas)."""
    BILINEAR = "bilinear"
    """Interpolación bilineal (cotas)."""
    MODE = "mode"
    """Moda por área (clases, :func:`resample_classes_to_grid`)."""


def choose_method(source: Grid, target: Grid) -> ResampleMethod:
    """El método por defecto para llevar una superficie de la rejilla ``source`` a
    ``target`` (RF-006-11): la media ponderada por área si los dos pasos de la fuente son
    menores o iguales que los del destino; si no, la bilineal (5 m → 1 m)."""
    if source.dx <= target.dx and source.dy <= target.dy:
        return ResampleMethod.AREA_MEAN
    return ResampleMethod.BILINEAR


@dataclass(frozen=True, slots=True)
class _Axis:
    """Tramos de solape de un eje, en orden: celda de origen, celda de destino (no
    decreciente) y longitud del tramo en fracción de la celda destino."""

    source: np.ndarray
    target: np.ndarray
    weight: np.ndarray

    @property
    def size(self) -> int:
        return int(self.target.size)


def _axis(offset: float, ratio: float, n_source: int, n_target: int) -> _Axis:
    """Los tramos de un eje medido en celdas destino (sus bordes son los enteros 0 …
    ``n_target``): los bordes de origen están en ``offset + k·ratio``, k = 0 … ``n_source``.
    Cada tramo se asigna por su inicio, que es un borde exacto, para no depender del
    redondeo de su punto medio."""
    edges = offset + np.arange(n_source + 1, dtype=np.float64) * ratio
    low = max(float(edges[0]), 0.0)
    high = min(float(edges[-1]), float(n_target))
    if not high > low:
        none = np.empty(0, dtype=np.int64)
        return _Axis(none, none, np.empty(0, dtype=np.float64))
    inner = edges[(edges > low) & (edges < high)]
    whole = np.arange(math.floor(low) + 1, math.ceil(high), dtype=np.float64)
    breaks = np.unique(np.concatenate(([low], inner, whole, [high])))
    starts = breaks[:-1]
    return _Axis(
        source=np.searchsorted(edges, starts, side="right") - 1,
        target=np.floor(starts).astype(np.int64),
        weight=np.diff(breaks),
    )


def _axes(source: Grid, target: Grid) -> tuple[_Axis, _Axis]:
    """Los tramos en X (de oeste a este) y en Y (de norte a sur)."""
    x = _axis((source.west - target.west) / target.dx, source.dx / target.dx,
              source.ncols, target.ncols)
    y = _axis((target.north - source.north) / target.dy, source.dy / target.dy,
              source.nrows, target.nrows)
    return x, y


def _runs(targets: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Dónde empieza cada celda destino en una lista de tramos (para ``reduceat``) y cuál
    es: las celdas destino de una lista no decreciente, sin repetir."""
    starts = np.flatnonzero(np.r_[True, targets[1:] != targets[:-1]])
    return starts, targets[starts]


def _blocks(
    targets: np.ndarray, segment_items: int, row_items: int = 0
) -> list[tuple[int, int]]:
    """Los tramos ``targets`` (filas destino, no decrecientes) en bloques de filas destino
    enteras con a lo sumo :data:`BLOCK_ITEMS` elementos (``segment_items`` por tramo y
    ``row_items`` por fila), o una sola fila: pares (primer tramo, fin)."""
    if targets.size == 0:
        return []
    starts, _ = _runs(targets)
    bounds = np.append(starts, targets.size)
    blocks: list[tuple[int, int]] = []
    first = 0
    items = 0
    for row in range(starts.size):
        cost = int(bounds[row + 1] - bounds[row]) * segment_items + row_items
        if row > first and items + cost > BLOCK_ITEMS:
            blocks.append((int(bounds[first]), int(bounds[row])))
            first, items = row, 0
        items += cost
    blocks.append((int(bounds[first]), int(bounds[-1])))
    return blocks


def _cancel_point(cancelled: Cancelled | None, index: int, total: int) -> None:
    if cancelled is not None and cancelled():
        raise JobCancelled(
            f"Cancelado al remuestrear a la rejilla del proyecto en el bloque {index + 1} de "
            f"{total}"
        )


def _advance(progress: Progress | None, index: int, total: int) -> None:
    if progress is not None:
        progress((index + 1) / total,
                 f"Remuestreando a la rejilla del proyecto: bloque {index + 1} de {total}")


def _fraction(value: object) -> float:
    """La fracción mínima: la de ``gis.resample.min_valid_fraction`` si es ``None``; si no,
    comprobada en (0; 1] (``ParamError`` ``core.param_*`` con la clave)."""
    definition = params.param(MIN_VALID_FRACTION_KEY)
    if value is None:
        return float(definition.default)  # type: ignore[arg-type]
    return float(definition.check(value))  # type: ignore[arg-type]


def _supersample(value: object) -> int:
    """Los subcentros por lado de la reproyección: los de ``gis.reproject.supersample`` si
    es ``None``; si no, comprobados en [1; 16] (``ParamError`` ``core.param_*`` con la
    clave)."""
    definition = params.param(SUPERSAMPLE_KEY)
    if value is None:
        return int(definition.default)  # type: ignore[arg-type]
    return int(definition.check(value))  # type: ignore[arg-type]


def _check_inputs(src: object, target: object) -> None:
    if not isinstance(src, Raster):
        raise TypeError(f"se esperaba un Raster, no {type(src).__name__}")
    if not isinstance(target, Grid):
        raise TypeError(f"se esperaba una Grid de destino, no {type(target).__name__}")


def _height_method(method: object) -> ResampleMethod:
    """El método de cotas declarado (media o bilineal); otro es un error del programa."""
    try:
        chosen = ResampleMethod(method)
    except ValueError:
        chosen = None
    if chosen not in (ResampleMethod.AREA_MEAN, ResampleMethod.BILINEAR):
        raise ValueError(
            f"método de remuestreo de cotas {method!r}: debe ser «area_mean» o «bilinear» "
            "(las clases, con resample_classes_to_grid)"
        )
    return chosen


def _covered(cover: np.ndarray, fraction: float) -> np.ndarray:
    """Celdas cuya área cubierta por celdas válidas alcanza la fracción mínima."""
    return (cover >= fraction - CELL_TOLERANCE) & (cover > 0.0)


def _area_mean(src: Raster, target: Grid, fraction: float, progress: Progress | None,
               cancelled: Cancelled | None) -> np.ndarray:
    out = np.full(target.shape, np.nan)
    x, y = _axes(src.grid, target)
    blocks = _blocks(y.target, x.size) if x.size else []
    if not blocks:
        _advance(progress, 0, 1)
        return out
    col_starts, cols = _runs(x.target)
    columns = slice(int(cols[0]), int(cols[-1]) + 1)
    for index, (begin, end) in enumerate(blocks):
        _cancel_point(cancelled, index, len(blocks))
        source_rows = y.source[begin:end]
        first = int(source_rows[0])
        # Las filas de origen del bloque, solo en las columnas de los tramos en X.
        band = src.values[first:int(source_rows[-1]) + 1][:, x.source]
        valid = np.isfinite(band)
        # Primero en columnas: Σ z·w y Σ w de cada fila de origen en cada columna destino.
        z_cols = np.add.reduceat(np.where(valid, band, 0.0) * x.weight, col_starts, axis=1)
        w_cols = np.add.reduceat(valid * x.weight, col_starts, axis=1)
        # Luego en filas.
        row_starts, rows = _runs(y.target[begin:end])
        local = source_rows - first
        weight = y.weight[begin:end, None]
        total = np.add.reduceat(z_cols[local] * weight, row_starts, axis=0)
        cover = np.add.reduceat(w_cols[local] * weight, row_starts, axis=0)
        values = np.full(total.shape, np.nan)
        np.divide(total, cover, out=values, where=_covered(cover, fraction))
        out[int(rows[0]):int(rows[-1]) + 1, columns] = values
        _advance(progress, index, len(blocks))
    return out


def _neighbours(position: np.ndarray, count: int) -> tuple[np.ndarray, np.ndarray,
                                                            np.ndarray, np.ndarray]:
    """Para posiciones fraccionarias en índices de origen: el vecino anterior y el
    siguiente (el mismo si el peso del siguiente es 0), el peso del siguiente y si los dos
    están dentro de la fuente. Una posición a menos de :data:`CELL_TOLERANCE` de un centro
    cae en él."""
    base = np.floor(position)
    weight = position - base
    up = weight > 1.0 - CELL_TOLERANCE
    base[up] += 1.0
    weight[up | (weight < CELL_TOLERANCE)] = 0.0
    before = base.astype(np.int64)
    after = np.where(weight > 0.0, before + 1, before)
    inside = (before >= 0) & (after <= count - 1)
    return (np.clip(before, 0, count - 1), np.clip(after, 0, count - 1), weight, inside)


def _bilinear(src: Raster, target: Grid, progress: Progress | None,
              cancelled: Cancelled | None) -> np.ndarray:
    grid = src.grid
    out = np.full(target.shape, np.nan)
    # Centro destino i en índices de origen: desplazamiento + (i + ½)·razón − ½.
    fx = ((target.west - grid.west) / grid.dx
          + (np.arange(target.ncols, dtype=np.float64) + 0.5) * (target.dx / grid.dx) - 0.5)
    fy = ((grid.north - target.north) / grid.dy
          + (np.arange(target.nrows, dtype=np.float64) + 0.5) * (target.dy / grid.dy) - 0.5)
    left, right, tx, inside_x = _neighbours(fx, grid.ncols)
    top, bottom, ty, inside_y = _neighbours(fy, grid.nrows)
    rows = np.flatnonzero(inside_y)
    blocks = _blocks(rows, target.ncols) if inside_x.any() else []
    if not blocks:
        _advance(progress, 0, 1)
        return out
    values = src.values
    for index, (begin, end) in enumerate(blocks):
        _cancel_point(cancelled, index, len(blocks))
        r = rows[begin:end]
        # Con peso 0, el «siguiente» es el mismo vecino: (1 − 0)·z + 0·z = z, bit a bit.
        z00 = values[np.ix_(top[r], left)]
        z10 = values[np.ix_(top[r], right)]
        z01 = values[np.ix_(bottom[r], left)]
        z11 = values[np.ix_(bottom[r], right)]
        wy = ty[r, None]
        with np.errstate(invalid="ignore"):
            upper = (1.0 - tx) * z00 + tx * z10
            lower = (1.0 - tx) * z01 + tx * z11
            result = (1.0 - wy) * upper + wy * lower
        ok = (inside_x & np.isfinite(z00) & np.isfinite(z10) & np.isfinite(z01)
              & np.isfinite(z11))
        result[~ok] = np.nan
        out[r] = result
        _advance(progress, index, len(blocks))
    return out


def _report(method: ResampleMethod, fraction: float, out: np.ndarray, target: Grid, *,
            transform: TransformInfo | None = None,
            supersample: int | None = None) -> ResampleReport:
    return ResampleReport(
        method=method.value,
        min_valid_fraction=fraction,
        cells=target.ncols * target.nrows,
        valid_cells=int(np.count_nonzero(np.isfinite(out))),
        cell_area_m2=target.cell_area,
        transform=transform,
        supersample=supersample,
    )


def resample_to_grid(
    src: Raster,
    target: Grid,
    *,
    method: ResampleMethod | str,
    min_valid_fraction: float | None = None,
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> tuple[Raster, ResampleReport]:
    """Las cotas de ``src`` en la rejilla ``target`` (RF-006-11): media ponderada por área
    (``"area_mean"``) o interpolación bilineal (``"bilinear"``), el que se declare
    (:func:`choose_method` da el de por defecto), con el CRS y la referencia vertical de la
    fuente, y el informe con el método, la fracción mínima, las celdas con dato y el área de
    celda exacta de ``target``.

    ``min_valid_fraction`` (de 0, excluido, a 1; ``None``: ``gis.resample.min_valid_fraction``,
    1) es el área de la celda destino que deben cubrir celdas de origen con dato para que la
    media valga; si no, la celda queda sin dato. En la bilineal, una celda queda sin dato si
    le falta un vecino. Errores: ``core.param_*`` (fracción); un método que no es de cotas o
    argumentos de otro tipo son errores del programa (``ValueError``, ``TypeError``).
    ``JobCancelled`` si ``cancelled()`` pide parar."""
    _check_inputs(src, target)
    chosen = _height_method(method)
    fraction = _fraction(min_valid_fraction)
    if chosen is ResampleMethod.AREA_MEAN:
        out = _area_mean(src, target, fraction, progress, cancelled)
    else:
        out = _bilinear(src, target, progress, cancelled)
    return Raster(target, out, src.crs, src.vertical), _report(chosen, fraction, out, target)


def _apply(transform: Transform, xyz: np.ndarray) -> np.ndarray:
    """``transform.apply`` en float64, con la forma de la entrada (si no, ``ValueError``)."""
    result = np.asarray(transform.apply(xyz), dtype=np.float64)
    if result.shape != xyz.shape:
        raise ValueError(
            f"la transformación «{transform.info.description}» devolvió {result.shape} "
            f"para {xyz.shape} puntos"
        )
    return result


def _check_transforms(transform: object, inverse: object, target_crs: object,
                      target_vertical: object) -> None:
    for label, item in (("transform", transform), ("inverse", inverse)):
        if not isinstance(item, Transform):
            raise TypeError(f"{label}: se esperaba una Transform, no {type(item).__name__}")
    if not isinstance(target_crs, CrsRef):
        raise TypeError(f"target_crs: se esperaba un CrsRef, no {type(target_crs).__name__}")
    if not isinstance(target_vertical, VerticalRef):
        raise TypeError(
            f"target_vertical: se esperaba un VerticalRef, no {type(target_vertical).__name__}"
        )


def _check_pair(transform: Transform, inverse: Transform, target: Grid) -> None:
    """Las esquinas y el centro de ``target``, llevados a la fuente con ``inverse`` y
    devueltos con ``transform``, vuelven a su sitio (≤ :data:`PAIR_TOLERANCE_M` en planta);
    si no, ``ValueError``: no son una transformación y su inversa. Los puntos que alguna
    no puede llevar (∞) no cuentan."""
    west, north = target.west, target.north
    east, south = west + target.ncols * target.dx, north - target.nrows * target.dy
    points = np.array([[west, north, 0.0], [east, north, 0.0], [west, south, 0.0],
                       [east, south, 0.0], [(west + east) / 2, (north + south) / 2, 0.0]])
    there = _apply(inverse, points)
    keep = np.isfinite(there).all(axis=1)
    if not keep.any():
        return
    back = _apply(transform, there[keep])
    error = np.hypot(back[:, 0] - points[keep, 0], back[:, 1] - points[keep, 1])
    error = error[np.isfinite(error)]
    if error.size and float(error.max()) > PAIR_TOLERANCE_M:
        raise ValueError(
            f"«{inverse.info.description}» no es la inversa de "
            f"«{transform.info.description}»: "
            f"un punto de la rejilla vuelve a {float(error.max()):.3f} m de su sitio"
        )


def _subcenters(target: Grid, first: int, stop: int,
                supersample: int) -> tuple[np.ndarray, np.ndarray]:
    """X e Y ABSOLUTAS de los s × s subcentros de las celdas de las filas ``first`` …
    ``stop`` − 1, en el orden (fila, subfila, columna, subcolumna); con s = 1, los centros."""
    offsets = (np.arange(supersample, dtype=np.float64) + 0.5) / supersample
    columns = np.arange(target.ncols, dtype=np.float64)[:, None] + offsets
    rows = np.arange(first, stop, dtype=np.float64)[:, None] + offsets
    x, y = np.meshgrid(target.west + columns.ravel() * target.dx,
                       target.north - rows.ravel() * target.dy)
    return x.ravel(), y.ravel()


def _sample(src: Raster, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """La bilineal de ``src`` en los puntos (``x``, ``y``) ABSOLUTOS de su CRS, con los
    vecinos de :func:`_neighbours` (como la de ``resample_to_grid``): NaN si al punto le
    falta un vecino de peso no nulo (fuera de los centros de la fuente o sin dato) o si no
    es finito."""
    grid = src.grid
    finite = np.isfinite(x) & np.isfinite(y)
    # Un punto no finito queda sin vecinos; los lejanos se acotan para que pasar a enteros
    # no desborde.
    fx = np.where(finite, (x - grid.west) / grid.dx - 0.5, -1.0)
    fy = np.where(finite, (grid.north - y) / grid.dy - 0.5, -1.0)
    np.clip(fx, -1.0, float(grid.ncols), out=fx)
    np.clip(fy, -1.0, float(grid.nrows), out=fy)
    left, right, tx, inside_x = _neighbours(fx, grid.ncols)
    top, bottom, ty, inside_y = _neighbours(fy, grid.nrows)
    values = src.values
    z00, z10 = values[top, left], values[top, right]
    z01, z11 = values[bottom, left], values[bottom, right]
    with np.errstate(invalid="ignore"):
        upper = (1.0 - tx) * z00 + tx * z10
        lower = (1.0 - tx) * z01 + tx * z11
        result = (1.0 - ty) * upper + ty * lower
    ok = (finite & inside_x & inside_y & np.isfinite(z00) & np.isfinite(z10)
          & np.isfinite(z01) & np.isfinite(z11))
    result[~ok] = np.nan
    return result


def _reproject(src: Raster, target: Grid, transform: Transform, inverse: Transform, *,
               vertical: bool, supersample: int, fraction: float,
               progress: Progress | None, cancelled: Cancelled | None) -> np.ndarray:
    out = np.full(target.shape, np.nan)
    count = supersample * supersample
    blocks = _blocks(np.arange(target.nrows), target.ncols * count)
    for index, (first, stop) in enumerate(blocks):
        _cancel_point(cancelled, index, len(blocks))
        x, y = _subcenters(target, first, stop, supersample)
        there = _apply(inverse, np.column_stack((x, y, np.zeros_like(x))))
        z = _sample(src, there[:, 0], there[:, 1])
        if vertical:
            keep = np.flatnonzero(np.isfinite(z))
            if keep.size:
                moved = _apply(transform, np.column_stack(
                    (there[keep, 0], there[keep, 1], z[keep])))
                z[keep] = moved[:, 2]
        cells = z.reshape(stop - first, supersample, target.ncols, supersample)
        valid = np.isfinite(cells)
        hits = valid.sum(axis=(1, 3))
        total = np.where(valid, cells, 0.0).sum(axis=(1, 3))
        values = np.full(hits.shape, np.nan)
        np.divide(total, hits, out=values, where=_covered(hits / count, fraction))
        out[first:stop] = values
        _advance(progress, index, len(blocks))
    return out


def reproject_to_grid(
    src: Raster,
    target: Grid,
    *,
    transform: Transform,
    inverse: Transform,
    target_crs: CrsRef,
    target_vertical: VerticalRef,
    method: ResampleMethod | str,
    min_valid_fraction: float | None = None,
    supersample: int | None = None,
    name: str = "MDT",
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> tuple[Raster, ResampleReport]:
    """Las cotas de ``src`` (en su CRS y su datum vertical) en la rejilla ``target`` del
    proyecto (``target_crs`` + ``target_vertical``), directamente, sin pasar por una
    rejilla intermedia (RF-006-05; plan 006 §5.4 A6 y §6 D7).

    ``transform`` es la transformación directa (de la fuente al proyecto, la de
    ``gis.crs.transformation_for``): su ``info`` va al informe, y convierte la cota de cada
    punto si la referencia vertical difiere. ``inverse`` es su inversa (del proyecto a la
    fuente: ``CrsService.transformer`` con los CRS al revés), que lleva los puntos de la
    rejilla a la fuente; las dos deben ser de precisión conocida (si no,
    ``gis.transform_unknown_accuracy`` con los dos CRS y ``name``, la fuente) y una la
    inversa de la otra (si no, ``ValueError``).

    ``method``: ``"area_mean"`` (la media, para bajar o mantener la resolución, como
    :func:`choose_method`): s × s subcentros por celda (s = ``supersample``; ``None``:
    ``gis.reproject.supersample``, 4) interpolados con la bilineal en la fuente; la celda
    vale la media de los válidos si son al menos ``min_valid_fraction`` (``None``:
    ``gis.resample.min_valid_fraction``, 1) de los s²; si no, queda sin dato.
    ``"bilinear"``: la bilineal en el centro de la celda (s = 1), sin dato si le falta un
    vecino. El informe lleva el método, la fracción, las celdas con dato, el área de celda
    exacta, la transformación directa y el submuestreo usado.

    Errores: ``gis.transform_unknown_accuracy``, ``core.param_*`` (fracción y submuestreo);
    un método que no es de cotas o una pareja que no es inversa, ``ValueError``; argumentos
    de otro tipo, ``TypeError``. ``JobCancelled`` si ``cancelled()`` pide parar. La fuente
    no se modifica."""
    _check_inputs(src, target)
    _check_transforms(transform, inverse, target_crs, target_vertical)
    chosen = _height_method(method)
    fraction = _fraction(min_valid_fraction)
    supersample = _supersample(supersample)
    if chosen is ResampleMethod.BILINEAR:
        supersample = 1
    if transform.info.accuracy_m is None or inverse.info.accuracy_m is None:
        raise unknown_accuracy_error(name, src.crs, src.vertical, target_crs, target_vertical)
    _check_pair(transform, inverse, target)
    out = _reproject(src, target, transform, inverse,
                     vertical=src.vertical != target_vertical, supersample=supersample,
                     fraction=fraction, progress=progress, cancelled=cancelled)
    report = _report(chosen, fraction, out, target, transform=transform.info,
                     supersample=supersample)
    return Raster(target, out, target_crs, target_vertical), report


def _class_index(values: np.ndarray, name: str) -> tuple[np.ndarray, np.ndarray]:
    """Los códigos distintos de ``values`` (ordenados) y, por celda, el índice de su código
    (−1 sin dato); ``gis.classes_not_integer`` si un valor no es entero."""
    valid = np.isfinite(values)
    codes = values[valid]
    fractional = codes != np.floor(codes)
    if fractional.any():
        bad = float(codes[fractional][0])
        raise GisError("gis.classes_not_integer", obj=name, field=_CLASSES_FIELD, value=bad,
                       source=name)
    unique, inverse = np.unique(codes, return_inverse=True)
    index = np.full(values.shape, -1, dtype=np.int64)
    index[valid] = inverse
    return unique, index


def _mode(src: Raster, target: Grid, fraction: float, name: str,
          progress: Progress | None, cancelled: Cancelled | None) -> np.ndarray:
    out = np.full(target.shape, np.nan)
    x, y = _axes(src.grid, target)
    if not (x.size and y.size):
        _advance(progress, 0, 1)
        return out
    # Solo la parte de la fuente que solapa la rejilla (los tramos van en orden).
    row_first, col_first = int(y.source[0]), int(x.source[0])
    unique, index = _class_index(
        src.values[row_first:int(y.source[-1]) + 1, col_first:int(x.source[-1]) + 1], name
    )
    if unique.size == 0:
        _advance(progress, 0, 1)
        return out
    count = unique.size
    _, cols = _runs(x.target)
    width = int(cols[-1] - cols[0]) + 1
    columns = slice(int(cols[0]), int(cols[-1]) + 1)
    blocks = _blocks(y.target, x.size, width * count)
    for number, (begin, end) in enumerate(blocks):
        _cancel_point(cancelled, number, len(blocks))
        row_targets = y.target[begin:end]
        row0 = int(row_targets[0])
        height = int(row_targets[-1]) - row0 + 1
        code = index[np.ix_(y.source[begin:end] - row_first, x.source - col_first)]
        weight = y.weight[begin:end, None] * x.weight
        cell = (row_targets[:, None] - row0) * width + (x.target - cols[0])
        keep = code >= 0
        areas = np.bincount(cell[keep] * count + code[keep], weights=weight[keep],
                            minlength=height * width * count).reshape(height * width, count)
        best = areas.max(axis=1)
        # El primer código (el menor) con el área máxima, salvo el redondeo.
        choice = np.argmax(areas >= (best - CELL_TOLERANCE)[:, None], axis=1)
        values = unique[choice]
        values[~_covered(areas.sum(axis=1), fraction)] = np.nan
        out[row0:row0 + height, columns] = values.reshape(height, width)
        _advance(progress, number, len(blocks))
    return out


def resample_classes_to_grid(
    src: Raster,
    target: Grid,
    *,
    min_valid_fraction: float | None = None,
    name: str = "clases",
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> tuple[Raster, ResampleReport]:
    """Una rejilla de clases (``src``: códigos enteros guardados en float64, NaN sin dato) en
    la rejilla ``target`` con la moda por área (RF-006-30): cada celda toma el código que
    cubre más área (con empate, el menor), nunca un código intermedio, y queda sin dato si
    el área cubierta por celdas con código no alcanza ``min_valid_fraction`` (como en
    :func:`resample_to_grid`). El informe lleva ``method = "mode"``.

    ``name`` es el nombre de la rejilla en los mensajes. Errores: ``gis.classes_not_integer``
    (un valor no entero en la parte de la fuente que solapa la rejilla, con el primero que se
    encuentra) y ``core.param_*`` (fracción); argumentos de otro tipo, ``TypeError``.
    ``JobCancelled`` si ``cancelled()`` pide parar."""
    _check_inputs(src, target)
    fraction = _fraction(min_valid_fraction)
    out = _mode(src, target, fraction, name, progress, cancelled)
    report = _report(ResampleMethod.MODE, fraction, out, target)
    return Raster(target, out, src.crs, src.vertical), report
