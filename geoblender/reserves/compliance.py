# SPDX-License-Identifier: GPL-3.0-or-later
"""El núcleo de la verificación en m³ por recinto (spec 012; RF-012-21, RF-012-22, RF-012-23;
plan 012 §5.3.1, A7–A10, D-6, D-41).

Una superficie final frente a la de partida, celda a celda, en la rejilla de las máscaras:

- :class:`CheckZone` y :func:`check_zones`: los recintos que se verifican, en su orden: «fuera
  del perímetro» (:data:`OUTSIDE_PERIMETER`, las celdas sin el bit del perímetro de la rejilla de
  clases), «fuera del límite legal» (:data:`OUTSIDE_LEGAL`, sin el bit del límite legal: las que
  no están enteras dentro, D-1) y la zona de cada restricción por su código (sus tramos de
  ``gis_mskz_``; ``<código>:inner``, la banda hacia dentro de un límite legal), cada uno con lo
  que cuenta en él (:class:`Counts`, A8): el corte, el relleno, cualquier movimiento, nada (un
  límite por dentro), su afección («preferible no afectar») o nada que comprobar («requiere
  acceso», R-40).
- :class:`Checker`: **A7**, por bandas de filas (las de ``reserves.surfaces.lockstep_bands``):
  ``d = partida − final`` donde las dos tienen dato; corte donde ``d > e`` y relleno donde
  ``−d > e`` (``e``, el espesor mínimo de verificación, D-6), **con todo su espesor** (lo que no
  pasa el umbral no cuenta; lo que pasa, entero); por recinto, el corte y el relleno (m³), el
  área con movimiento (m²) y el área sin dato (m²), con los tramos de fila de cada recinto (sumas
  acumuladas por fila: ningún par celda-recinto). Una celda en dos recintos cuenta en los dos: la
  tabla es por recinto, no una partición.
- :func:`verdict`: **A9** (CA-2, CA-13; D-6): «no cumple» si lo que cuenta pasa de 0 m³
  (tolerancia 0 con el umbral ``e``: basta una celda), «cumple» si no; «preferible no afectar»,
  sin juicio (su afección en m², m³ y m³ × peso); «requiere acceso», «sin comprobar (R-40)».
- :func:`label_groups`: **A10** (D-41): las celdas que incumplen, agrupadas por contigüidad de
  lado (4-conexión) con tramos de fila, parejas de tramos de filas seguidas que se solapan
  (búsqueda binaria) y etiquetas por saltos de puntero (Shiloach–Vishkin, 1982). Cada grupo
  (:class:`Group`) con su recinto, su área (m²), su volumen (m³), su espesor máximo (m), su centro
  absoluto (media de los centros de sus celdas, de igual área) y su caja, para «Ir a».
- :func:`check`: una final de una vez (:class:`FinalCheck`, con las celdas que incumplen y su
  ``final − partida``, D-42); la misma superficie como partida y final da ceros y el aviso
  ``res.same_surface``.
- :class:`ComplianceRequest`: lo que pide una verificación (la partida, de 1 a
  :data:`MAX_FINALS` finales, las máscaras de la versión y el espesor mínimo); la lee la
  operación ``res.verify_constraints`` (``reserves.compliance_store``, T17).

Volúmenes y áreas con el área exacta de la celda de la rejilla (``Grid.cell_area``), en float64.
Python puro (nivel 9).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np

from ..core.constraints.model import ConstraintType
from ..gis.grid import Grid
from ..gis.masks.access import MaskSet
from ..gis.masks.combine import ClassBit
from ..gis.masks.zones import Runs
from .surfaces import BAND_ROWS, SurfaceRef
from .volumes import Notice

__all__ = [
    "INNER_SUFFIX",
    "MAX_FINALS",
    "OUTSIDE_LEGAL",
    "OUTSIDE_PERIMETER",
    "CheckZone",
    "Checker",
    "ComplianceRequest",
    "Counts",
    "FinalCheck",
    "Group",
    "Verdict",
    "ZoneTotals",
    "check",
    "check_zones",
    "counts_of",
    "label_groups",
    "verdict",
]

OUTSIDE_PERIMETER = "outside_perimeter"
"""El código del recinto «fuera del perímetro» (cualquier movimiento incumple)."""
OUTSIDE_LEGAL = "outside_legal"
"""El código del recinto «fuera del límite legal» (el corte incumple; el relleno, no)."""
INNER_SUFFIX = ":inner"
"""El sufijo de la banda hacia dentro de un límite legal (``<código>:inner``, de ``gis_mskz_``)."""
MAX_FINALS = 10
"""Finales de una verificación, como mucho (D-40)."""
_MAX_THICKNESS_M = 10.0


class Counts(StrEnum):
    """Lo que cuenta en un recinto (A8; RF-012-22)."""

    CUT = "cut"  # el corte: fuera del límite legal, banda hacia dentro, sin corte, solo relleno…
    FILL = "fill"  # el relleno: sin relleno
    ANY = "any"  # cualquier movimiento: fuera del perímetro, intocable, exclusión
    NOTHING = "nothing"  # nada: un límite por dentro
    AVOID = "avoid"  # su afección, sin juicio: preferible no afectar
    ACCESS = "access"  # sin comprobar (R-40): requiere acceso


class Verdict(StrEnum):
    """El veredicto de un recinto (A9)."""

    COMPLIES = "complies"  # cumple
    FAILS = "fails"  # no cumple
    NOT_JUDGED = "not_judged"  # preferible no afectar: su afección, sin juicio
    UNCHECKED = "unchecked"  # requiere acceso: sin comprobar (R-40)


_CUT_TYPES = (ConstraintType.NO_CUT, ConstraintType.FILL_ONLY, ConstraintType.RESTORATION_ONLY,
              ConstraintType.SETBACK)
_ANY_TYPES = (ConstraintType.UNTOUCHABLE, ConstraintType.EXCLUSION)


def counts_of(code: str, ctype: ConstraintType | None) -> Counts:
    """Lo que cuenta en el recinto ``code`` de tipo ``ctype`` (A8; ``None`` en los dos recintos
    de los límites, :data:`OUTSIDE_PERIMETER` y :data:`OUTSIDE_LEGAL`)."""
    if code == OUTSIDE_PERIMETER:
        return Counts.ANY
    if code == OUTSIDE_LEGAL:
        return Counts.CUT
    if ctype is None:
        raise ValueError(f"el recinto «{code}» no tiene tipo de restricción")
    ctype = ConstraintType(ctype)
    if code.endswith(INNER_SUFFIX):
        if ctype is not ConstraintType.LEGAL_LIMIT:
            raise ValueError(f"«{code}»: solo un límite legal tiene banda hacia dentro")
        return Counts.CUT
    if ctype in _ANY_TYPES:
        return Counts.ANY
    if ctype in _CUT_TYPES:
        return Counts.CUT
    if ctype is ConstraintType.NO_FILL:
        return Counts.FILL
    if ctype is ConstraintType.AVOID:
        return Counts.AVOID
    if ctype is ConstraintType.REQUIRES_ACCESS:
        return Counts.ACCESS
    return Counts.NOTHING  # un límite (legal o perímetro): prohíbe fuera, no dentro


@dataclass(frozen=True, slots=True, eq=False)
class CheckZone:
    """Un recinto que se verifica: su código, su tipo (``None`` en los dos de los límites), lo
    que cuenta en él, sus celdas (tramos de fila) y su peso («preferible no afectar»)."""

    code: str
    ctype: ConstraintType | None
    counts: Counts
    runs: Runs = field(repr=False)
    weight: float | None = None


def check_zones(classes: np.ndarray, zones: Mapping[str, Runs],
                ctypes: Mapping[str, ConstraintType],
                weights: Mapping[str, float] | None = None) -> tuple[CheckZone, ...]:
    """Los recintos de una verificación (A7, A8): «fuera del perímetro» y «fuera del límite
    legal» por los bits de la rejilla de clases ``classes`` (D-25) y cada zona de ``zones``
    (código → tramos, en su orden; ``<código>:inner`` con el tipo de su límite legal), con su
    tipo de ``ctypes`` y, la «preferible no afectar», su peso de ``weights``."""
    classes = np.asarray(classes)
    if classes.ndim != 2:
        raise ValueError(f"la rejilla de clases es 2D, no de forma {classes.shape}")
    weights = weights or {}
    bits = classes.astype(np.uint16, copy=False)
    found = [
        CheckZone(OUTSIDE_PERIMETER, None, Counts.ANY,
                  Runs.from_mask((bits & np.uint16(ClassBit.PERIMETER)) == 0)),
        CheckZone(OUTSIDE_LEGAL, None, Counts.CUT,
                  Runs.from_mask((bits & np.uint16(ClassBit.LEGAL)) == 0)),
    ]
    for code, runs in zones.items():
        base = code.removesuffix(INNER_SUFFIX)
        if base not in ctypes:
            raise ValueError(f"la zona «{code}» no tiene tipo de restricción")
        ctype = ConstraintType(ctypes[base])
        counts = counts_of(code, ctype)
        weight = None
        if counts is Counts.AVOID:
            if code not in weights:
                raise ValueError(f"la zona «{code}» (preferible no afectar) no tiene peso")
            weight = float(weights[code])
        found.append(CheckZone(code, ctype, counts, runs, weight))
    return tuple(found)


def verdict(zone: CheckZone, counted_cells: int) -> Verdict:
    """**A9** (CA-2, CA-13; D-6): el veredicto de ``zone`` con ``counted_cells`` celdas cuyo
    movimiento cuenta en ella (las que pasan el espesor mínimo; cada una, > 0 m³)."""
    if zone.counts is Counts.AVOID:
        return Verdict.NOT_JUDGED
    if zone.counts is Counts.ACCESS:
        return Verdict.UNCHECKED
    if zone.counts is Counts.NOTHING:
        return Verdict.COMPLIES
    return Verdict.FAILS if counted_cells > 0 else Verdict.COMPLIES


@dataclass(frozen=True, slots=True)
class ZoneTotals:
    """Lo verificado en un recinto (RF-012-21, RF-012-22): su código y su tipo, lo que cuenta,
    el corte y el relleno (m³) y el área con movimiento (m²) de las celdas que pasan el espesor
    mínimo, el área sin dato (m²), lo que cuenta (m³; el corte, el relleno o los dos), su peso y
    el volumen por el peso («preferible no afectar»; si no, ``None``), y el veredicto."""

    code: str
    ctype: ConstraintType | None
    counts: Counts
    cut_m3: float
    fill_m3: float
    moved_m2: float
    nodata_m2: float
    counted_m3: float
    weight: float | None
    weighted_m3: float | None
    verdict: Verdict


@dataclass(frozen=True, slots=True, eq=False)
class Group:
    """Un grupo de celdas contiguas (4-conexión) que incumple en un recinto (RF-012-23): el
    recinto, sus celdas (número, y sus filas y columnas en la rejilla), su área (m²), su volumen
    (m³), su espesor máximo (m), su centro ABSOLUTO (x, y) y su caja ABSOLUTA (oeste, sur, este,
    norte)."""

    zone: str
    cells: int
    area_m2: float
    volume_m3: float
    max_m: float
    center: tuple[float, float]
    box: tuple[float, float, float, float]
    rows: np.ndarray = field(repr=False)
    cols: np.ndarray = field(repr=False)


@dataclass(frozen=True, slots=True, eq=False)
class FinalCheck:
    """La verificación de una final: lo de cada recinto en su orden, los grupos que incumplen
    (por recinto y, en cada uno, por su primera celda de norte a sur y de oeste a este), si la
    final es la misma superficie que la partida, los avisos y las celdas que incumplen con su
    espesor con signo (:attr:`violations`)."""

    totals: tuple[ZoneTotals, ...]
    groups: tuple[Group, ...]
    same_surface: bool
    notices: tuple[Notice, ...]
    violations: tuple[np.ndarray, np.ndarray, np.ndarray] | None = field(default=None,
                                                                          repr=False)
    """Las celdas que incumplen en algún recinto (filas, columnas y ``final − partida``, m; una
    celda en dos recintos sale dos veces con el mismo valor): la rejilla de incumplimientos
    (D-42). ``None`` si ninguna incumple."""

    @property
    def fails(self) -> bool:
        """Si algún recinto no cumple."""
        return any(item.verdict is Verdict.FAILS for item in self.totals)

    def zone(self, code: str) -> ZoneTotals:
        """Lo del recinto ``code`` (``KeyError`` si no lo hay)."""
        for item in self.totals:
            if item.code == code:
                return item
        raise KeyError(code)

    def groups_of(self, code: str) -> tuple[Group, ...]:
        """Los grupos que incumplen en el recinto ``code``."""
        return tuple(group for group in self.groups if group.zone == code)


# --- A7: por bandas ----------------------------------------------------------------------------


def _thickness(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float | np.integer | np.floating):
        raise ValueError(f"el espesor mínimo de verificación es un número, no {value!r}")
    value = float(value)
    if not (math.isfinite(value) and 0.0 <= value <= _MAX_THICKNESS_M):
        raise ValueError("el espesor mínimo de verificación está entre 0 y "
                         f"{_MAX_THICKNESS_M:g} m, no {value!r}")
    return value


def _band(value: np.ndarray | float, rows: int, ncols: int) -> np.ndarray:
    if isinstance(value, int | float | np.integer | np.floating):
        return np.full((rows, ncols), float(value), dtype=np.float64)
    band = np.asarray(value, dtype=np.float64)
    if band.shape != (rows, ncols):
        raise ValueError(f"una banda de {rows} × {ncols} celdas, no de forma {band.shape}")
    return band


class Checker:
    """**A7**: una final frente a la partida, por bandas de filas (:meth:`add`, de norte a sur o
    en cualquier orden, cada fila una vez) y el resultado (:meth:`result`)."""

    def __init__(self, grid: Grid, zones: Sequence[CheckZone], min_thickness_m: float) -> None:
        if not isinstance(grid, Grid):
            raise TypeError(f"se esperaba una Grid, no {type(grid).__name__}")
        zones = tuple(zones)
        codes = [zone.code for zone in zones]
        if len(set(codes)) != len(codes):
            raise ValueError(f"códigos de recinto repetidos: {codes}")
        self.grid = grid
        self.zones = zones
        self.threshold = _thickness(min_thickness_m)
        count = len(zones)
        index = np.concatenate([np.full(len(z.runs), i, np.int64) for i, z in enumerate(zones)]
                               or [np.zeros(0, np.int64)])
        row = np.concatenate([z.runs.row for z in zones] or [np.zeros(0, np.int64)])
        col0 = np.concatenate([z.runs.col0 for z in zones] or [np.zeros(0, np.int64)])
        col1 = np.concatenate([z.runs.col1 for z in zones] or [np.zeros(0, np.int64)])
        inside = (row >= 0) & (row < grid.nrows)
        col0, col1 = np.clip(col0, 0, grid.ncols), np.clip(col1, 0, grid.ncols)
        inside &= col1 > col0
        order = np.argsort(row[inside], kind="stable")
        self._index = index[inside][order]
        self._row = row[inside][order]
        self._col0 = col0[inside][order]
        self._col1 = col1[inside][order]
        self._cut = np.zeros(count, np.float64)
        self._fill = np.zeros(count, np.float64)
        self._cut_cells = np.zeros(count, np.int64)
        self._fill_cells = np.zeros(count, np.int64)
        self._moved = np.zeros(count, np.int64)
        self._nodata = np.zeros(count, np.int64)
        self._violations: list[list[tuple[np.ndarray, np.ndarray, np.ndarray]]] = [
            [] for _ in zones]
        self._same = True

    def add(self, top: int, start: np.ndarray | float, final: np.ndarray | float) -> None:
        """Acumula la banda de filas desde ``top`` de la partida y de la final (float64, NaN sin
        dato; o una cota constante)."""
        grid = self.grid
        shapes = [np.shape(v) for v in (start, final) if np.ndim(v) == 2]
        if not shapes:
            raise ValueError("al menos una de las dos superficies es una rejilla")
        rows = int(shapes[0][0])
        if not (0 <= top and top + rows <= grid.nrows):
            raise ValueError(f"la banda de las filas {top}–{top + rows} no está en la rejilla")
        start_band = _band(start, rows, grid.ncols)
        final_band = _band(final, rows, grid.ncols)
        if self._same and not np.array_equal(start_band, final_band, equal_nan=True):
            self._same = False
        valid = np.isfinite(start_band) & np.isfinite(final_band)
        with np.errstate(invalid="ignore"):
            difference = np.where(valid, start_band - final_band, 0.0)
        cut = valid & (difference > self.threshold)
        fill = valid & (-difference > self.threshold)
        first = int(np.searchsorted(self._row, top, side="left"))
        last = int(np.searchsorted(self._row, top + rows, side="left"))
        if first == last:
            return
        index = self._index[first:last]
        local = self._row[first:last] - top
        col0, col1 = self._col0[first:last], self._col1[first:last]
        count = len(self.zones)

        def run_sums(values: np.ndarray) -> np.ndarray:
            sums = np.zeros((rows, grid.ncols + 1), dtype=values.dtype)
            np.cumsum(values, axis=1, out=sums[:, 1:])
            return sums[local, col1] - sums[local, col0]

        def add_to(target: np.ndarray, values: np.ndarray) -> None:
            target += np.bincount(index, weights=values, minlength=count).astype(target.dtype)

        add_to(self._cut, run_sums(np.where(cut, difference, 0.0)))
        add_to(self._fill, run_sums(np.where(fill, -difference, 0.0)))
        cut_cells = run_sums(cut.astype(np.int64))
        fill_cells = run_sums(fill.astype(np.int64))
        add_to(self._cut_cells, cut_cells)
        add_to(self._fill_cells, fill_cells)
        add_to(self._moved, run_sums((cut | fill).astype(np.int64)))
        add_to(self._nodata, run_sums((~valid).astype(np.int64)))
        per_zone_cut = np.bincount(index, weights=cut_cells, minlength=count)
        per_zone_fill = np.bincount(index, weights=fill_cells, minlength=count)
        for position, zone in enumerate(self.zones):
            wanted = _counted(zone.counts, cut, fill, per_zone_cut[position],
                              per_zone_fill[position])
            if wanted is None:
                continue
            mine = index == position
            mask = np.zeros((rows, grid.ncols + 1), dtype=np.int64)
            np.add.at(mask, (local[mine], col0[mine]), 1)
            np.add.at(mask, (local[mine], col1[mine]), -1)
            inside = (np.cumsum(mask, axis=1)[:, :grid.ncols] > 0) & wanted
            cell_rows, cell_cols = np.nonzero(inside)
            self._violations[position].append(
                (cell_rows + top, cell_cols, difference[cell_rows, cell_cols]))

    def result(self, *, start_name: str = "") -> FinalCheck:
        """Lo de cada recinto y los grupos que incumplen (:class:`FinalCheck`)."""
        area = self.grid.cell_area
        totals = []
        groups: list[Group] = []
        for position, zone in enumerate(self.zones):
            cut = float(self._cut[position]) * area
            fill = float(self._fill[position]) * area
            counted_cells = {Counts.CUT: int(self._cut_cells[position]),
                             Counts.FILL: int(self._fill_cells[position]),
                             Counts.ANY: int(self._moved[position])}.get(zone.counts, 0)
            counted = {Counts.CUT: cut, Counts.FILL: fill,
                       Counts.ANY: cut + fill}.get(zone.counts, 0.0)
            weighted = None
            if zone.counts is Counts.AVOID:
                counted = cut + fill
                weighted = counted * float(zone.weight if zone.weight is not None else 0.0)
            totals.append(ZoneTotals(
                zone.code, zone.ctype, zone.counts, cut, fill,
                int(self._moved[position]) * area, int(self._nodata[position]) * area,
                counted, zone.weight, weighted, verdict(zone, counted_cells)))
            if self._violations[position]:
                groups.extend(self._groups(zone.code, self._violations[position]))
        notices = (Notice("res.same_surface", {"surface": start_name}),) if self._same else ()
        parts = [part for found in self._violations for part in found]
        violations = None
        if parts:  # final − partida = −d
            violations = (_readonly(np.concatenate([part[0] for part in parts])),
                          _readonly(np.concatenate([part[1] for part in parts])),
                          _frozen(-np.concatenate([part[2] for part in parts])))
        return FinalCheck(tuple(totals), tuple(groups), self._same, notices, violations)

    def _groups(self, code: str, parts: list[tuple[np.ndarray, np.ndarray, np.ndarray]]
                ) -> list[Group]:
        grid = self.grid
        rows = np.concatenate([part[0] for part in parts])
        cols = np.concatenate([part[1] for part in parts])
        values = np.abs(np.concatenate([part[2] for part in parts]))
        labels, count = label_groups(rows, cols)
        order = np.lexsort((cols, rows, labels))
        rows, cols, values, labels = rows[order], cols[order], values[order], labels[order]
        starts = np.flatnonzero(np.r_[True, labels[1:] != labels[:-1]])
        stops = np.r_[starts[1:], labels.size]
        found = []
        for begin, end in zip(starts.tolist(), stops.tolist(), strict=True):
            mine_rows, mine_cols = rows[begin:end], cols[begin:end]
            cells = end - begin
            mean_col = math.fsum(mine_cols.tolist()) / cells
            mean_row = math.fsum(mine_rows.tolist()) / cells
            center = (grid.west + (mean_col + 0.5) * grid.dx,
                      grid.north - (mean_row + 0.5) * grid.dy)
            box = (grid.west + int(mine_cols.min()) * grid.dx,
                   grid.north - (int(mine_rows.max()) + 1) * grid.dy,
                   grid.west + (int(mine_cols.max()) + 1) * grid.dx,
                   grid.north - int(mine_rows.min()) * grid.dy)
            found.append(Group(
                code, cells, cells * grid.cell_area,
                math.fsum(values[begin:end].tolist()) * grid.cell_area,
                float(values[begin:end].max()), center, box,
                _readonly(mine_rows), _readonly(mine_cols)))
        assert len(found) == count
        return found


def _counted(counts: Counts, cut: np.ndarray, fill: np.ndarray, cut_cells: float,
             fill_cells: float) -> np.ndarray | None:
    """Las celdas de la banda cuyo movimiento cuenta en un recinto que lo cuenta, si alguna de
    las suyas lo tiene (si no, ``None``: nada que agrupar)."""
    if counts is Counts.CUT and cut_cells > 0:
        return cut
    if counts is Counts.FILL and fill_cells > 0:
        return fill
    if counts is Counts.ANY and cut_cells + fill_cells > 0:
        return cut | fill
    return None


def _readonly(values: np.ndarray) -> np.ndarray:
    values = np.ascontiguousarray(values, dtype=np.int64)
    values.flags.writeable = False
    return values


def _frozen(values: np.ndarray) -> np.ndarray:
    values = np.ascontiguousarray(values, dtype=np.float64)
    values.flags.writeable = False
    return values


def check(grid: Grid, zones: Sequence[CheckZone], start: np.ndarray | float,
          final: np.ndarray | float, min_thickness_m: float, *, band_rows: int = BAND_ROWS,
          start_name: str = "") -> FinalCheck:
    """Una final frente a la partida de una vez (:class:`Checker` por bandas de ``band_rows``
    filas); ``start`` y ``final``, rejillas de forma ``grid.shape`` o cotas constantes."""
    if band_rows < 1:
        raise ValueError(f"una banda tiene al menos una fila, no {band_rows}")
    checker = Checker(grid, zones, min_thickness_m)
    for top in range(0, grid.nrows, band_rows):
        stop = min(top + band_rows, grid.nrows)
        checker.add(top, _rows_of(start, top, stop), _rows_of(final, top, stop))
    return checker.result(start_name=start_name)


def _rows_of(value: np.ndarray | float, top: int, stop: int) -> np.ndarray | float:
    if np.ndim(value) == 0:
        return float(value)  # type: ignore[arg-type]
    return np.asarray(value, dtype=np.float64)[top:stop]


# --- A10: grupos -------------------------------------------------------------------------------


def label_groups(rows: np.ndarray, cols: np.ndarray) -> tuple[np.ndarray, int]:
    """**A10** (D-41): las celdas ``(rows[i], cols[i])`` (distintas, índices ≥ 0) agrupadas por
    contigüidad de lado (4-conexión). Devuelve la etiqueta de cada celda (0…n−1, numeradas por
    su primera celda de norte a sur y de oeste a este) y el número de grupos ``n``."""
    rows = np.asarray(rows, dtype=np.int64).ravel()
    cols = np.asarray(cols, dtype=np.int64).ravel()
    if rows.shape != cols.shape:
        raise ValueError("tantas filas como columnas")
    if rows.size == 0:
        return np.zeros(0, np.int64), 0
    if rows.min() < 0 or cols.min() < 0:
        raise ValueError("los índices de celda no son negativos")
    order = np.lexsort((cols, rows))
    r, c = rows[order], cols[order]
    if np.any((r[1:] == r[:-1]) & (c[1:] == c[:-1])):
        raise ValueError("celdas repetidas")
    # Tramos de fila: una celda empieza tramo si cambia la fila o salta la columna.
    starts = np.r_[True, (r[1:] != r[:-1]) | (c[1:] != c[:-1] + 1)]
    run_of_cell = np.cumsum(starts) - 1
    first = np.flatnonzero(starts)
    run_row = r[first]
    run_col0 = c[first]
    run_col1 = np.r_[c[np.flatnonzero(starts)[1:] - 1], c[-1]] + 1
    runs = first.size
    # Parejas de tramos de filas seguidas que se solapan: búsqueda binaria en claves (fila, col).
    width = int(max(int(run_col1.max()), 1)) + 1
    key_end = run_row * width + run_col1
    key_start = run_row * width + run_col0
    low = np.searchsorted(key_end, (run_row + 1) * width + run_col0, side="right")
    high = np.searchsorted(key_start, (run_row + 1) * width + run_col1, side="left")
    many = np.maximum(high - low, 0)
    left = np.repeat(np.arange(runs), many)
    offsets = np.arange(int(many.sum())) - np.repeat(np.cumsum(many) - many, many)
    right = np.repeat(low, many) + offsets
    # Saltos de puntero: cada par une sus raíces en la menor, hasta que no cambia nada.
    label = np.arange(runs)
    while True:
        a, b = label[left], label[right]
        if np.array_equal(a, b):
            break
        least = np.minimum(a, b)
        np.minimum.at(label, a, least)
        np.minimum.at(label, b, least)
        while True:
            jumped = label[label]
            if np.array_equal(jumped, label):
                break
            label = jumped
    roots, run_label = np.unique(label, return_inverse=True)
    result = np.empty(rows.size, np.int64)
    result[order] = run_label[run_of_cell]
    return result, int(roots.size)


# --- La petición -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ComplianceRequest:
    """Lo que pide una verificación (RF-012-21; D-28, D-40): su nombre, la superficie de
    partida, las finales (de 1 a :data:`MAX_FINALS`, distintas), las máscaras de la versión (al
    día, ``gis.masks.access``) y el espesor mínimo de verificación (m, D-6). Una petición
    incoherente es un error del programa (:class:`ValueError`)."""

    name: str
    start: SurfaceRef
    finals: tuple[SurfaceRef, ...]
    masks: MaskSet
    min_thickness_m: float

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError(f"una verificación tiene nombre, no {self.name!r}")
        finals = tuple(self.finals)
        if not 1 <= len(finals) <= MAX_FINALS:
            raise ValueError(f"de 1 a {MAX_FINALS} superficies finales, no {len(finals)}")
        if len(set(finals)) != len(finals):
            raise ValueError("una superficie final repetida")
        if not all(isinstance(item, SurfaceRef) for item in (self.start, *finals)):
            raise ValueError("las superficies son SurfaceRef")
        if not isinstance(self.masks, MaskSet):
            raise ValueError(f"las máscaras son un MaskSet, no {type(self.masks).__name__}")
        object.__setattr__(self, "finals", finals)
        object.__setattr__(self, "min_thickness_m", _thickness(self.min_thickness_m))

    def same_as_start(self, position: int) -> bool:
        """Si la final ``position`` es la misma superficie que la partida."""
        return self.finals[position] == self.start
