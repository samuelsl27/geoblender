# SPDX-License-Identifier: GPL-3.0-or-later
"""Las celdas de una zona (spec 013; RF-013-01, RF-013-02, RF-013-07; plan 013 §5.3.1, A1, D-16).

Una celda es de un polígono si su **centro** está dentro de él (D-16: a diferencia de las
prohibiciones de la 012, que van por el lado seguro, una semilla no prohíbe nada):

- :func:`cells_inside` (A1): el par-impar por **barrido de filas**, sin bucle por celda. De cada
  arista que cruza el centro de una fila ``y = i + ½`` se saca el cruce ``x``; se ordenan por
  (fila, ``x``), se emparejan dentro de cada fila y los centros entre cada pareja están dentro. Los
  anillos van en **unidades de celda** (columna hacia el este, fila hacia el sur, desde la esquina
  noroeste), en float64; varios anillos de un mismo polígono se combinan par-impar (un anillo
  dentro de otro es un hueco). La convención de borde es semiabierta y fija: un centro sobre un
  borde oeste o norte está dentro, y sobre uno este o sur, fuera; así dos polígonos contiguos se
  reparten las celdas de su frontera sin hueco ni doble cuenta.
- :func:`to_cell_units`: los anillos ABSOLUTOS (m, float64) de una rejilla a unidades de celda;
  la resta de la esquina se hace antes de dividir, en float64 (ADR-0005).
- :func:`polygons_cells`: la **unión** de varios polígonos absolutos (cada uno, sus anillos).
- :func:`sector_labels`: la etiqueta de cada celda con el sector al que pertenece (1 a n, por el
  orden de los sectores; 0, ninguno).
- :func:`constraint_cells`: las celdas de la zona de una restricción en las máscaras de la
  versión (``MaskSet.zone``: celda entera, D-1 de la 012, no pasa por A1).
- :func:`layer_polygons` y :func:`layer_cells`: los polígonos y las celdas de una capa de
  polígonos del proyecto (entidades de la 012 o dominios de la 011); :func:`frozen_polygons`, los
  de su copia congelada (al reproducir).

Ninguna entrada se modifica. Python puro (nivel 8), con numpy.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from typing import Protocol

import numpy as np

from ..gis.grid import Grid
from ..gis.masks.access import MaskSet
from ..gis.provenance import DOMAINS, FAMILIES_BY_CODE, FEATURES
from ..gis.store import StoreProject, load_domains, load_features, read_domains, read_features
from ..gis.vector import FeatureLayer
from .messages import DesignError

__all__ = [
    "LABEL_LIMIT",
    "cells_inside",
    "constraint_cells",
    "frozen_polygons",
    "layer_cells",
    "layer_polygons",
    "polygons_cells",
    "sector_labels",
    "to_cell_units",
]

LABEL_LIMIT = int(np.iinfo(np.int16).max)
"""El mayor número de sectores que caben en las etiquetas (``int16``)."""

_KINDS_ES = {"point": "puntos", "line": "líneas", "polygon": "polígonos"}
_LAYER = "Capa de polígonos"
_ZONES = "Zonas de las máscaras"

_Spans = tuple[np.ndarray, np.ndarray, np.ndarray]
"""Tramos de fila: ``(fila, primera columna, columna siguiente a la última)``, int64."""


class SupportsRings(Protocol):
    """Un sector (``core.constraints.model.Sector``) o cualquier cosa con sus anillos absolutos."""

    @property
    def rings(self) -> Sequence[np.ndarray]: ...


# --- A1: el par-impar por barrido de filas -----------------------------------------------------


def _ring(ring: object) -> np.ndarray:
    """``ring`` como array float64 ``(k, 2)`` (sin la Z si la trae) de vértices finitos, sin
    copiar si ya lo es; ``ValueError`` si no es una lista de puntos o no son finitos."""
    array = np.asarray(ring, dtype=np.float64)
    if array.ndim != 2 or array.shape[1] not in (2, 3):
        raise ValueError(f"un anillo es un array (k, 2) o (k, 3), no de forma {array.shape}")
    array = array[:, :2]
    if not np.all(np.isfinite(array)):
        raise ValueError("un anillo tiene coordenadas no finitas")
    return array


def _size(nrows: object, ncols: object) -> tuple[int, int]:
    """El tamaño de una rejilla: dos enteros ≥ 1 (``ValueError`` si no)."""
    rows, cols = int(nrows), int(ncols)  # type: ignore[call-overload]
    if rows < 1 or cols < 1:
        raise ValueError(f"una rejilla tiene al menos una celda, no {rows} × {cols}")
    return rows, cols


def _spans(rings: Iterable[object], nrows: int, ncols: int, *, row0: int = 0, col0: int = 0) -> _Spans:
    """Los tramos de fila de los centros dentro de ``rings`` (unidades de celda, par-impar),
    recortados a la rejilla y sin tramos vacíos. Una fila ``i`` está cruzada por una arista si
    ``ylo ≤ i + ½ < yhi`` (semiabierto: un vértice sobre el centro cuenta una sola vez); una
    columna ``j`` está dentro de una pareja de cruces ``[a, b)`` si ``a ≤ j + ½ < b``; las dos
    cuentas son ``ceil(v − ½)``. ``row0`` y ``col0`` (T46 de la 015) mueven el recorte a la caja de
    ``nrows × ncols`` celdas que empieza en la fila ``row0`` y la columna ``col0`` (pueden ser negativas:
    celdas fuera de la rejilla, para medir lo que ella recorta), sin cambiar las cuentas: las filas y
    las columnas que salen son las mismas, bit a bit, que con la rejilla entera; por defecto, la rejilla."""
    pieces = []
    for ring in rings:
        array = _ring(ring)
        if array.shape[0] >= 2:
            pieces.append(np.column_stack([array, np.roll(array, -1, axis=0)]))
    empty = np.empty(0, dtype=np.int64)
    if not pieces:
        return empty, empty, empty
    ax, ay, bx, by = np.concatenate(pieces).T  # los extremos de cada arista (no el GeoOrigin)
    first = np.clip(np.ceil(np.minimum(ay, by) - 0.5), row0, row0 + nrows).astype(np.int64)
    stop = np.clip(np.ceil(np.maximum(ay, by) - 0.5), row0, row0 + nrows).astype(np.int64)
    count = stop - first
    total = int(count.sum())
    if total == 0:
        return empty, empty, empty
    edge = np.repeat(np.arange(count.size), count)
    row = first[edge] + (np.arange(total) - (np.cumsum(count) - count)[edge])
    # El cruce de cada arista con el centro de cada una de sus filas.
    crossing = ax[edge] + ((row + 0.5) - ay[edge]) * (bx[edge] - ax[edge]) / (by[edge] - ay[edge])
    order = np.lexsort((crossing, row))
    row, crossing = row[order], crossing[order]
    if total % 2:  # un anillo cerrado cruza cada fila un número par de veces
        raise AssertionError("un anillo cruza una fila un número impar de veces")
    begin = np.clip(np.ceil(crossing[0::2] - 0.5), col0, col0 + ncols).astype(np.int64)
    end = np.clip(np.ceil(crossing[1::2] - 0.5), col0, col0 + ncols).astype(np.int64)
    keep = end > begin
    return row[0::2][keep], begin[keep], end[keep]


def _paint(spans: _Spans, nrows: int, ncols: int) -> tuple[int, int, np.ndarray]:
    """Las celdas de ``spans`` (su unión) como máscara de la caja que tocan: ``(primera fila, primera
    columna, bloque booleano)``. Una suma acumulada de diferencias por fila, sin bucle por celda y solo
    sobre las columnas de la caja: antes de la primera columna no hay marca ninguna y desde la última
    cada fila suma cero, así que el bloque es, bit a bit, el de la rejilla entera recortado a su caja
    (un sector estrecho de una rejilla grande cuesta su caja, no la rejilla)."""
    rows, begin, end = spans
    if rows.size == 0:
        return 0, 0, np.zeros((0, ncols), dtype=bool)
    top, bottom = int(rows.min()), int(rows.max()) + 1
    left, right = int(begin.min()), int(end.max())
    width = right - left + 1
    marks = np.zeros((bottom - top) * width, dtype=np.int32)
    base = (rows - top) * width - left
    np.add.at(marks, base + begin, 1)
    np.add.at(marks, base + end, -1)
    block = np.cumsum(marks.reshape(bottom - top, width)[:, :width - 1], axis=1, dtype=np.int32) > 0
    return top, left, block


def _full(spans: _Spans, nrows: int, ncols: int) -> np.ndarray:
    """Las celdas de ``spans`` como máscara de toda la rejilla."""
    top, left, block = _paint(spans, nrows, ncols)
    found = np.zeros((nrows, ncols), dtype=bool)
    found[top:top + block.shape[0], left:left + block.shape[1]] = block
    return found


def cells_inside(rings: Iterable[object], nrows: int, ncols: int) -> np.ndarray:
    """**A1** (RF-013-01, D-16): las celdas de una rejilla de ``nrows × ncols`` cuyo centro está
    dentro de ``rings`` por la regla par-impar, como máscara booleana (fila 0 al norte; una
    matriz nueva cada vez). ``rings``: los anillos de **un** polígono en unidades de celda
    (``(k, 2)``: columna hacia el este y fila hacia el sur desde la esquina noroeste, o ``(k, 3)``
    con una Z que no cuenta), abiertos o cerrados, con la orientación que sea; un anillo dentro de
    otro es un hueco y dos que se cortan dejan fuera su zona común. Lo que se sale de la rejilla
    se recorta. Un anillo de menos de tres vértices o de área nula no da celdas; coordenadas no
    finitas, una forma que no es ``(k, 2)`` ni ``(k, 3)`` o una rejilla sin celdas son errores del
    programa (``ValueError``). Ninguna entrada se modifica."""
    rows, cols = _size(nrows, ncols)
    return _full(_spans(rings, rows, cols), rows, cols)


# --- Absolutas ---------------------------------------------------------------------------------


def to_cell_units(rings: Iterable[object], grid: Grid) -> tuple[np.ndarray, ...]:
    """Los anillos ABSOLUTOS ``rings`` (m, CRS del proyecto, ``(k, 2)`` o ``(k, 3)``) en unidades
    de celda de ``grid`` (``(k, 2)``: columna ``(X − oeste)/dx``, fila ``(norte − Y)/dy``), en
    float64: la esquina se resta antes de dividir, así que un norte de 4,4 Mm no pierde el medio
    centímetro (regla 4, ADR-0005). Arrays nuevos."""
    found = []
    for ring in rings:
        array = _ring(ring)
        found.append(np.column_stack([(array[:, 0] - grid.west) / grid.dx,
                                      (grid.north - array[:, 1]) / grid.dy]))
    return tuple(found)


def _polygon_spans(polygons: Iterable[Iterable[object]], grid: Grid, *,
                   box: tuple[slice, slice] | None = None) -> _Spans:
    """Los tramos de la unión de ``polygons`` absolutos (cada uno, sus anillos par-impar), recortados a la
    rejilla o, con ``box`` (filas y columnas de la rejilla, que pueden salirse de ella: T46 de la 015), a esa
    caja."""
    rows, cols = (slice(0, grid.nrows), slice(0, grid.ncols)) if box is None else box
    parts = [_spans(to_cell_units(polygon, grid), rows.stop - rows.start, cols.stop - cols.start,
                    row0=rows.start, col0=cols.start) for polygon in polygons]
    if not parts:
        empty = np.empty(0, dtype=np.int64)
        return empty, empty, empty
    return (np.concatenate([part[0] for part in parts]),
            np.concatenate([part[1] for part in parts]),
            np.concatenate([part[2] for part in parts]))


def polygons_cells(polygons: Iterable[Iterable[object]], grid: Grid) -> np.ndarray:
    """Las celdas de ``grid`` cuyo centro está dentro de **alguno** de ``polygons`` (RF-013-01,
    D-16): la unión; cada polígono, con sus anillos ABSOLUTOS par-impar (el exterior primero y,
    luego, sus huecos). Una máscara nueva de la forma de la rejilla."""
    return _full(_polygon_spans(polygons, grid), grid.nrows, grid.ncols)


def sector_labels(sectors: Sequence[SupportsRings], grid: Grid) -> np.ndarray:
    """La etiqueta (``int16``) del sector de cada celda de ``grid`` por el centro (RF-013-07;
    D-16): 1 a n por el orden de ``sectors`` y 0 donde no hay ninguno. Los sectores de la 012 no
    se solapan; si alguno lo hiciera, la celda común es del primero. Más sectores de los que caben
    en ``int16`` (:data:`LABEL_LIMIT`) son un error del programa (``ValueError``)."""
    if len(sectors) > LABEL_LIMIT:
        raise ValueError(f"no caben {len(sectors)} sectores en las etiquetas (máximo "
                         f"{LABEL_LIMIT})")
    labels = np.zeros(grid.shape, dtype=np.int16)
    for label, sector in enumerate(sectors, start=1):
        spans = _spans(to_cell_units(sector.rings, grid), grid.nrows, grid.ncols)
        top, left, block = _paint(spans, grid.nrows, grid.ncols)
        window = labels[top:top + block.shape[0], left:left + block.shape[1]]
        window[block & (window == 0)] = label
    return labels


# --- Restricciones y capas del proyecto --------------------------------------------------------


def constraint_cells(masks: MaskSet, code: str) -> np.ndarray:
    """Las celdas de la zona de la restricción ``code`` en las máscaras de la versión
    (``MaskSet.zone``, celda entera: D-1 de la 012), como máscara de la forma de su rejilla,
    nueva cada vez. Una restricción sin zona en ellas es ``des.zone_unknown`` (RF-013-16)."""
    try:
        runs = masks.zone(code)
    except KeyError:
        raise DesignError("des.zone_unknown", obj=_ZONES, field="zona", value=code,
                          zone=code) from None
    return runs.mask(masks.grid.shape)


def _family(name: str) -> str | None:
    for code in (FEATURES, DOMAINS):
        if name.startswith(FAMILIES_BY_CODE[code].prefix):
            return code
    return None


def layer_polygons(project: StoreProject, name: str) -> tuple[tuple[np.ndarray, ...], ...]:
    """Los polígonos de la capa ``name`` del proyecto —entidades de la 012 (``gis_fea_``, de
    polígonos) o dominios de la 011 (``gis_dom_``)—: de cada uno, sus anillos ABSOLUTOS en el CRS
    del proyecto tal como están guardados (el exterior primero), en el orden de la capa. Solo
    lee. Una capa de puntos o de líneas es ``des.layer_not_polygons``; una que no hay,
    ``gis.dataset_unknown`` (``GisError``); un dato que no es una de las dos familias, un error
    del programa (``ValueError``)."""
    family = _family(name)
    if family is None:
        raise ValueError(f"las celdas de una capa salen de una capa «entidades» (gis_fea_) o "
                         f"«dominios» (gis_dom_) del proyecto, no de «{name}»")
    if family == DOMAINS:
        return tuple(tuple(polygon) for item in load_domains(project, name)
                     for polygon in item.polygons)
    layer = load_features(project, name)
    assert isinstance(layer, FeatureLayer)
    if layer.kind != "polygon":
        raise DesignError("des.layer_not_polygons", obj=f"{_LAYER} «{name}»", field="geometría",
                          value=_KINDS_ES.get(layer.kind, layer.kind), layer=name)
    return tuple(tuple(part) for entity in layer.parts for part in entity)


def frozen_polygons(conn: sqlite3.Connection, table: str, name: str
                    ) -> tuple[tuple[np.ndarray, ...], ...]:
    """Lo mismo que :func:`layer_polygons` de la tabla ``table`` de la conexión ``conn`` (la copia
    congelada de la capa ``name``, que es el nombre de su dato), sin el proyecto: al reproducir lo
    congelado. Solo lee."""
    family = _family(name)
    if family is None:
        raise ValueError(f"las celdas de una capa salen de una capa «entidades» (gis_fea_) o "
                         f"«dominios» (gis_dom_) del proyecto, no de «{name}»")
    if family == DOMAINS:
        return tuple(tuple(polygon) for item in read_domains(conn, table)
                     for polygon in item.polygons)
    layer = read_features(conn, table)
    if layer.kind != "polygon":
        raise DesignError("des.layer_not_polygons", obj=f"{_LAYER} «{name}»", field="geometría",
                          value=_KINDS_ES.get(layer.kind, layer.kind), layer=name)
    return tuple(tuple(part) for entity in layer.parts for part in entity)


def layer_cells(project: StoreProject, name: str, grid: Grid) -> np.ndarray:
    """Las celdas de ``grid`` cuyo centro está dentro de algún polígono de la capa ``name`` del
    proyecto (RF-013-01, RF-013-02; D-16): :func:`polygons_cells` de :func:`layer_polygons`, con
    sus mismos errores. La capa no se modifica."""
    return polygons_cells(layer_polygons(project, name), grid)
