# SPDX-License-Identifier: GPL-3.0-or-later
"""Verificar por recinto a escala: el mismo resultado, por pasos cortos (spec 012, T36;
RF-012-21, RF-012-22, RF-012-23, RF-012-28, RNF-012-02, RNF-012-03, RNF-012-06; plan 012 §5.2.3,
A7, A10, A11).

La T36 es de rendimiento puro: ningún resultado cambia. Esta prueba lleva **el cálculo de antes**
(``OldChecker``: ``Checker.add``/``result`` y ``label_groups`` tal como eran, con la matriz de
celdas por recinto, ``np.lexsort`` y ``np.add.at``) y exige el mismo resultado bit a bit:

- **RF-012-21, RF-012-22 (A7, A9)**: por recinto, el corte, el relleno, el área con movimiento,
  el área sin dato, lo que cuenta, el peso y el veredicto, **iguales** (``==``, no «casi») que los
  de antes en 50 casos al azar (los tres modos de contar, «preferible no afectar», «requiere
  acceso», un límite con su banda hacia dentro, celdas sin dato, umbral 0 y mayor, cotas
  constantes, bandas de 1, 2, 7 y 256 filas).
- **RF-012-23 (A10, D-41)**: los grupos, iguales a los de antes: recinto, orden, celdas (sus
  filas y columnas), área, volumen, espesor máximo, centro y caja; y la rejilla de
  incumplimientos (``FinalCheck.violations``: ``final − partida`` donde algún recinto incumple, NaN
  en las demás celdas) igual a la que se hacía con las filas, columnas y espesores de cada celda
  de cada recinto.
- **RF-012-28 (RNF-012-06)**: ``Checker.result_steps`` y ``check_zones_steps`` dan sus unidades por
  pasos y devuelven lo mismo que de una vez; cerrar a mitad no deja nada.
- ``label_groups`` sigue dando la partición de la inundación celda a celda.
- **RF-012-24 (A11)**: el hash de las dos tablas por tramos (``_digest_steps``, en unidades
  de 2.000 filas y trozos de 256 KiB) es el de antes, de una vez, y ``CheckWriter.prepare``
  (que recorre ``prepare_steps``) da los mismos datos.
"""

from __future__ import annotations

import math
import sqlite3
import unittest
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np

from tests.support.package import import_geoblender

gis = import_geoblender("gis")
model = import_geoblender("core.constraints.model")
combine = import_geoblender("gis.masks.combine")
zones_mod = import_geoblender("gis.masks.zones")
compliance = import_geoblender("reserves.compliance")
cstore = import_geoblender("reserves.compliance_store")
core_builtin = import_geoblender("core.content.builtin")
encoder = import_geoblender("core.content.encoder")
datasets_model = import_geoblender("core.datasets.model")
gpkg_base = import_geoblender("core.gpkg.base")
gpkg_wkb = import_geoblender("core.gpkg.wkb")
gis_store = import_geoblender("gis.store")
georef = import_geoblender("core.georef")

T = model.ConstraintType
Bit = combine.ClassBit
Runs = zones_mod.Runs
C = compliance.Counts

NAN = math.nan


# --- El cálculo de antes (la referencia) --------------------------------------------------------


def old_label_groups(rows: Any, cols: Any) -> tuple[np.ndarray, int]:
    """``label_groups`` de antes de la T36: tramos de fila de las celdas, parejas de tramos de
    filas seguidas que se solapan y etiquetas por saltos de puntero con ``np.minimum.at`` sobre
    todas las parejas en cada vuelta."""
    rows = np.asarray(rows, dtype=np.int64).ravel()
    cols = np.asarray(cols, dtype=np.int64).ravel()
    if rows.size == 0:
        return np.zeros(0, np.int64), 0
    order = np.lexsort((cols, rows))
    r, c = rows[order], cols[order]
    starts = np.r_[True, (r[1:] != r[:-1]) | (c[1:] != c[:-1] + 1)]
    run_of_cell = np.cumsum(starts) - 1
    first = np.flatnonzero(starts)
    run_row = r[first]
    run_col0 = c[first]
    run_col1 = np.r_[c[np.flatnonzero(starts)[1:] - 1], c[-1]] + 1
    runs = first.size
    width = int(max(int(run_col1.max()), 1)) + 1
    key_end = run_row * width + run_col1
    key_start = run_row * width + run_col0
    low = np.searchsorted(key_end, (run_row + 1) * width + run_col0, side="right")
    high = np.searchsorted(key_start, (run_row + 1) * width + run_col1, side="left")
    many = np.maximum(high - low, 0)
    left = np.repeat(np.arange(runs), many)
    offsets = np.arange(int(many.sum())) - np.repeat(np.cumsum(many) - many, many)
    right = np.repeat(low, many) + offsets
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


@dataclass(frozen=True)
class OldFinal:
    """Lo que daba ``Checker.result`` de antes, sin los tipos de ahora."""

    totals: list[tuple[Any, ...]]
    groups: list[tuple[Any, ...]]
    same: bool
    violations: np.ndarray | None


class OldChecker:
    """``Checker`` de antes de la T36 (A7 por bandas con una máscara por recinto y banda, A10 con
    ``np.lexsort`` por recinto): la referencia bit a bit."""

    def __init__(self, grid: Any, zones: Any, min_thickness_m: float) -> None:
        zones = tuple(zones)
        self.grid = grid
        self.zones = zones
        self.threshold = float(min_thickness_m)
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

    def add(self, top: int, start: Any, final: Any) -> None:
        grid = self.grid
        shapes = [np.shape(v) for v in (start, final) if np.ndim(v) == 2]
        rows = int(shapes[0][0])

        def band(value: Any) -> np.ndarray:
            if isinstance(value, int | float):
                return np.full((rows, grid.ncols), float(value), dtype=np.float64)
            return np.asarray(value, dtype=np.float64)

        start_band, final_band = band(start), band(final)
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
            wanted = None
            if zone.counts is C.CUT and per_zone_cut[position] > 0:
                wanted = cut
            elif zone.counts is C.FILL and per_zone_fill[position] > 0:
                wanted = fill
            elif zone.counts is C.ANY and per_zone_cut[position] + per_zone_fill[position] > 0:
                wanted = cut | fill
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

    def result(self) -> OldFinal:
        area = self.grid.cell_area
        totals: list[tuple[Any, ...]] = []
        groups: list[tuple[Any, ...]] = []
        for position, zone in enumerate(self.zones):
            cut = float(self._cut[position]) * area
            fill = float(self._fill[position]) * area
            counted_cells = {C.CUT: int(self._cut_cells[position]),
                             C.FILL: int(self._fill_cells[position]),
                             C.ANY: int(self._moved[position])}.get(zone.counts, 0)
            counted = {C.CUT: cut, C.FILL: fill, C.ANY: cut + fill}.get(zone.counts, 0.0)
            weighted = None
            if zone.counts is C.AVOID:
                counted = cut + fill
                weighted = counted * float(zone.weight if zone.weight is not None else 0.0)
            totals.append((zone.code, cut, fill, int(self._moved[position]) * area,
                           int(self._nodata[position]) * area, counted, zone.weight, weighted,
                           compliance.verdict(zone, counted_cells)))
            if self._violations[position]:
                groups.extend(self._groups(zone.code, self._violations[position]))
        parts = [part for found in self._violations for part in found]
        violations = None
        if parts:
            cells = np.full(self.grid.shape, np.nan, dtype=np.float64)
            cells[np.concatenate([part[0] for part in parts]),
                  np.concatenate([part[1] for part in parts])] = -np.concatenate(
                      [part[2] for part in parts])
            violations = cells
        return OldFinal(totals, groups, self._same, violations)

    def _groups(self, code: str, parts: list[Any]) -> list[tuple[Any, ...]]:
        grid = self.grid
        rows = np.concatenate([part[0] for part in parts])
        cols = np.concatenate([part[1] for part in parts])
        values = np.abs(np.concatenate([part[2] for part in parts]))
        labels, count = old_label_groups(rows, cols)
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
            found.append((code, cells, cells * grid.cell_area,
                          math.fsum(values[begin:end].tolist()) * grid.cell_area,
                          float(values[begin:end].max()), center, box, mine_rows.tolist(),
                          mine_cols.tolist()))
        assert len(found) == count
        return found


# --- Los casos al azar --------------------------------------------------------------------------

CTYPES = (T.UNTOUCHABLE, T.EXCLUSION, T.NO_CUT, T.FILL_ONLY, T.RESTORATION_ONLY, T.SETBACK,
          T.NO_FILL, T.AVOID, T.REQUIRES_ACCESS, T.LEGAL_LIMIT, T.ACTION_PERIMETER)


def random_case(seed: int) -> dict[str, Any]:
    """Una rejilla pequeña, recintos de todos los tipos (algunos solapados, un límite con su banda
    hacia dentro), una partida y una final con huecos sin dato y un umbral."""
    rng = np.random.default_rng(seed)
    rows, cols = int(rng.integers(4, 40)), int(rng.integers(4, 45))
    grid = gis.Grid(699_000.0 + 3.25, 4_399_000.0 + 11.5, float(rng.choice([1.0, 2.5])),
                    float(rng.choice([1.0, 2.0])), cols, rows)
    classes = np.zeros((rows, cols), np.uint16)
    classes |= np.where(rng.random((rows, cols)) < 0.8, np.uint16(Bit.PERIMETER), np.uint16(0))
    classes |= np.where(rng.random((rows, cols)) < 0.7, np.uint16(Bit.LEGAL), np.uint16(0))
    zones: dict[str, Any] = {}
    ctypes: dict[str, Any] = {}
    weights: dict[str, float] = {}
    for index, ctype in enumerate(CTYPES * int(rng.integers(1, 4))):
        code = f"r{index:02d}"
        mask = rng.random((rows, cols)) < rng.uniform(0.05, 0.6)
        if rng.random() < 0.5:  # una mancha en vez de ruido
            top, left = int(rng.integers(0, rows)), int(rng.integers(0, cols))
            mask = np.zeros((rows, cols), bool)
            mask[top:top + int(rng.integers(1, rows)), left:left + int(rng.integers(1, cols))] = 1
        zones[code] = Runs.from_mask(mask)
        ctypes[code] = ctype
        if ctype is T.AVOID:
            weights[code] = float(rng.choice([1.0, 2.0, 3.5]))
        if ctype is T.LEGAL_LIMIT:
            inner = mask & (rng.random((rows, cols)) < 0.5)
            zones[f"{code}:inner"] = Runs.from_mask(inner)
    base = rng.uniform(600.0, 700.0, (rows, cols))
    start = base + rng.normal(0, 0.03, (rows, cols))
    final = base + rng.normal(0, 0.05, (rows, cols))
    for grid_values in (start, final):
        holes = rng.random((rows, cols)) < rng.choice([0.0, 0.05, 0.3])
        grid_values[holes] = NAN
    if rng.random() < 0.15:
        final = start.copy()
    return {"grid": grid, "classes": classes, "zones": zones, "ctypes": ctypes,
            "weights": weights, "start": start, "final": final,
            "threshold": float(rng.choice([0.0, 0.02, 0.05, 0.1])),
            "band_rows": int(rng.choice([1, 2, 7, 256]))}


def new_zones(case: dict[str, Any]) -> tuple[Any, ...]:
    return compliance.check_zones(case["classes"], case["zones"], case["ctypes"],
                                  case["weights"])


def run_both(case: dict[str, Any]) -> tuple[OldFinal, Any]:
    grid, zones = case["grid"], new_zones(case)
    old = OldChecker(grid, zones, case["threshold"])
    new = compliance.Checker(grid, zones, case["threshold"])
    step = case["band_rows"]
    for top in range(0, grid.nrows, step):
        stop = min(top + step, grid.nrows)
        old.add(top, case["start"][top:stop], case["final"][top:stop])
        new.add(top, case["start"][top:stop], case["final"][top:stop])
    return old.result(), new.result()


def violating_case() -> dict[str, Any]:
    """El primer caso al azar con cinco o más grupos que incumplen."""
    for seed in range(200):
        case = random_case(seed)
        grid, zones = case["grid"], new_zones(case)
        found = compliance.check(grid, zones, case["start"], case["final"], case["threshold"])
        if len(found.groups) >= 5:
            return case
    raise AssertionError("ningún caso al azar con grupos")


def group_tuple(group: Any) -> tuple[Any, ...]:
    return (group.zone, group.cells, group.area_m2, group.volume_m3, group.max_m, group.center,
            group.box, group.rows.tolist(), group.cols.tolist())


def total_tuple(item: Any) -> tuple[Any, ...]:
    return (item.code, item.cut_m3, item.fill_m3, item.moved_m2, item.nodata_m2, item.counted_m3,
            item.weight, item.weighted_m3, item.verdict)


class SameAsBeforeTest(unittest.TestCase):
    """RF-012-21 a RF-012-23: bit a bit lo que daba antes de la T36."""

    def test_random_cases_are_equal_to_the_old_result(self) -> None:
        """RF-012-21, RF-012-22, RF-012-23: totales, grupos y rejilla de incumplimientos, ``==``
        con lo de antes en 50 casos al azar."""
        kinds: set[Any] = set()
        groups = failing = 0
        for seed in range(50):
            case = random_case(seed)
            old, new = run_both(case)
            with self.subTest(seed=seed):
                self.assertEqual([total_tuple(item) for item in new.totals], old.totals)
                self.assertEqual([group_tuple(group) for group in new.groups], old.groups)
                self.assertIs(new.same_surface, old.same)
                if old.violations is None:
                    self.assertIsNone(new.violations)
                else:
                    self.assertIsNotNone(new.violations)
                    np.testing.assert_array_equal(new.violations, old.violations)
            kinds.update(item.counts for item in new.totals)
            groups += len(new.groups)
            failing += int(new.fails)
        self.assertEqual(kinds, set(C))  # los seis modos de contar se vieron
        self.assertGreater(groups, 5000)  # y había grupos que comparar
        self.assertGreater(failing, 25)

    def test_units_of_a_few_cells_give_the_same(self) -> None:
        """RF-012-23: con unidades diminutas (7 celdas o 3 tramos de grupo, 5 tramos de recinto,
        3 filas), los grupos que cruzan varias unidades salen enteros y los mismos que antes."""
        crossing = 0
        with (mock.patch.object(compliance, "_CELLS_PER_UNIT", 7),
              mock.patch.object(compliance, "_GROUP_RUNS_PER_UNIT", 3),
              mock.patch.object(compliance, "_RUNS_PER_UNIT", 5),
              mock.patch.object(compliance, "_CHUNK_ROWS", 3),
              mock.patch.object(compliance, "_INDEX_ROWS", 4)):
            for seed in range(12):
                case = random_case(seed)
                old, new = run_both(case)
                with self.subTest(seed=seed):
                    self.assertEqual([total_tuple(item) for item in new.totals], old.totals)
                    self.assertEqual([group_tuple(group) for group in new.groups], old.groups)
                    if old.violations is not None:
                        np.testing.assert_array_equal(new.violations, old.violations)
                crossing += sum(1 for group in new.groups if group.cells > 7)
        self.assertGreater(crossing, 15)  # había grupos más grandes que una unidad

    def test_label_groups_keeps_its_partition(self) -> None:
        """RF-012-23: ``label_groups`` da las mismas etiquetas que la versión de antes."""
        rng = np.random.default_rng(7)
        for case in range(150):
            shape = (int(rng.integers(1, 30)), int(rng.integers(1, 30)))
            mask = rng.random(shape) < rng.uniform(0.2, 0.8)
            rows, cols = np.nonzero(mask)
            permutation = rng.permutation(rows.size)
            rows, cols = rows[permutation], cols[permutation]
            with self.subTest(case=case):
                labels, count = compliance.label_groups(rows, cols)
                expected, expected_count = old_label_groups(rows, cols)
                self.assertEqual(count, expected_count)
                np.testing.assert_array_equal(labels, expected)

    def test_a_constant_start_and_a_final_without_violations(self) -> None:
        """RF-012-21: una cota constante como partida da lo mismo que su rejilla; si nada
        incumple, ``violations`` es ``None`` y no hay grupos."""
        case = random_case(3)
        grid, zones = case["grid"], new_zones(case)
        final = np.full(grid.shape, 640.0)
        new = compliance.check(grid, zones, 640.0, final, 0.02)
        old = OldChecker(grid, zones, 0.02)
        old.add(0, np.full(grid.shape, 640.0), final)
        expected = old.result()
        self.assertEqual([total_tuple(item) for item in new.totals], expected.totals)
        self.assertIsNone(new.violations)
        self.assertEqual(new.groups, ())
        self.assertTrue(new.same_surface)


class StepsTest(unittest.TestCase):
    """RF-012-28, RNF-012-06: por pasos, lo mismo que de una vez; cerrar no deja nada."""

    def test_result_steps_gives_the_same_in_several_units(self) -> None:
        """``result_steps`` cede varias unidades y devuelve lo mismo que ``result``."""
        case = violating_case()
        grid, zones = case["grid"], new_zones(case)
        checkers = [compliance.Checker(grid, zones, 0.02) for _ in range(2)]
        for checker in checkers:
            checker.add(0, case["start"], case["final"])
        steps = checkers[0].result_steps(start_name="Partida")
        units = 0
        while True:
            try:
                next(steps)
                units += 1
            except StopIteration as stop:
                stepped = stop.value
                break
        whole = checkers[1].result(start_name="Partida")
        self.assertGreater(units, 8)
        self.assertGreater(len(whole.groups), 3)
        self.assertEqual([total_tuple(item) for item in stepped.totals],
                         [total_tuple(item) for item in whole.totals])
        self.assertEqual([group_tuple(group) for group in stepped.groups],
                         [group_tuple(group) for group in whole.groups])
        np.testing.assert_array_equal(stepped.violations, whole.violations)

    def test_closing_the_steps_stops_them(self) -> None:
        """Cerrar ``result_steps`` a mitad lo detiene sin error."""
        case = violating_case()
        checker = compliance.Checker(case["grid"], new_zones(case), 0.02)
        checker.add(0, case["start"], case["final"])
        steps = checker.result_steps()
        next(steps)
        steps.close()
        with self.assertRaises(StopIteration):
            next(steps)

    def test_zone_steps_equal_check_zones(self) -> None:
        """``check_zones_steps`` (los dos recintos de fuera por bandas de filas) da los mismos
        recintos que ``check_zones``."""
        for seed in (1, 5, 9):
            case = random_case(seed)
            args = (case["classes"], case["zones"], case["ctypes"], case["weights"])
            steps = compliance.check_zones_steps(*args)
            units = 0
            while True:
                try:
                    next(steps)
                    units += 1
                except StopIteration as stop:
                    stepped = stop.value
                    break
            whole = compliance.check_zones(*args)
            self.assertGreaterEqual(units, 1)
            self.assertEqual([(z.code, z.ctype, z.counts, z.weight, z.runs) for z in stepped],
                             [(z.code, z.ctype, z.counts, z.weight, z.runs) for z in whole])

    def test_mask_runs_are_those_of_from_mask(self) -> None:
        """Los tramos de una máscara (``_mask_runs``, con un solo ``flatnonzero``) son los de
        ``Runs.from_mask``, también sin celdas, con filas enteras y con una sola columna."""
        rng = np.random.default_rng(4)
        masks = [np.zeros((5, 7), bool), np.ones((5, 7), bool), np.ones((4, 1), bool),
                 np.zeros((3, 1), bool), np.array([[True, False, True, True, False]]),
                 np.array([[False], [True], [True], [False]])]
        masks += [rng.random((int(rng.integers(1, 20)), int(rng.integers(1, 30)))) < p
                  for p in (0.1, 0.5, 0.9) for _ in range(20)]
        for index, mask in enumerate(masks):
            with self.subTest(case=index):
                row, begin, end = compliance._mask_runs(mask)
                self.assertEqual(Runs(row, begin, end), Runs.from_mask(mask))
                self.assertEqual(len(row), len(Runs.from_mask(mask)))

    def test_a_shared_index_serves_every_final(self) -> None:
        """Una ``ZoneIndex`` hecha una vez la comparten las finales: el mismo resultado que
        cada una con la suya."""
        case = random_case(21)
        grid, zones = case["grid"], new_zones(case)
        index = compliance.zone_index(grid, zones)
        shared = compliance.Checker(grid, zones, 0.05, index=index)
        alone = compliance.Checker(grid, zones, 0.05)
        for checker in (shared, alone):
            checker.add(0, case["start"], case["final"])
        a, b = shared.result(), alone.result()
        self.assertEqual([group_tuple(g) for g in a.groups], [group_tuple(g) for g in b.groups])
        self.assertEqual([total_tuple(i) for i in a.totals], [total_tuple(i) for i in b.totals])

    def test_the_unit_is_small(self) -> None:
        """Ninguna unidad de ``result_steps`` hace el trabajo de toda una final: en un caso de
        2.000 grupos cede muchas unidades."""
        rng = np.random.default_rng(2)
        grid = gis.Grid(699_000.0, 4_399_900.0, 1.0, 1.0, 300, 300)
        mask = np.ones(grid.shape, bool)
        zones = compliance.check_zones(
            np.full(grid.shape, Bit.PERIMETER | Bit.LEGAL, np.uint16),
            {"r_torre": Runs.from_mask(mask)}, {"r_torre": T.UNTOUCHABLE})
        start = np.zeros(grid.shape)
        final = np.where(rng.random(grid.shape) < 0.35, -1.0, 0.0)
        checker = compliance.Checker(grid, zones, 0.02)
        checker.add(0, start, final)
        units = sum(1 for _ in _units(checker.result_steps()))
        self.assertGreater(units, 8)


def old_digest(family: str, rows: Any, crs: Any) -> Any:
    """``_digest`` de antes de la T36: todas las filas de una vez y el hash con los trozos por
    defecto."""
    conn = sqlite3.connect(":memory:")
    try:
        gpkg_base.create_base(conn, crs)
        cstore._create(conn, family, "digest", crs.epsg, "digest")
        gis_store.insert_rows(conn, "digest", cstore._names(family), rows)
        request = cstore.GPKG_LAYER.request(
            cstore._family(family).kind, datasets_model.DATASET_DECLARATIONS,
            {"main": Path("digest")}, {"layer": "digest"}, normalizer=encoder.NORMALIZER)
        steps = core_builtin.layer_steps(conn, request)
        for _done in steps:
            pass
        return request.hasher.digest()
    finally:
        conn.close()


class DigestTest(unittest.TestCase):
    """RF-012-24 (A11): el hash de las tablas por tramos es el de antes."""

    def test_the_digest_by_steps_is_the_old_one(self) -> None:
        """``_digest_steps`` de la tabla en formato largo y de la capa de grupos (con sus puntos
        absolutos) da, en varias unidades, el mismo hash que de una vez; y ``_digest`` (que lo
        recorre) también."""
        crs = georef.load_catalog().horizontal(25830)
        rng = np.random.default_rng(5)
        table = [(f"recinto_{i % 500}", 1 + i % 3, "cut_m3", float(rng.random() * 1e4), "m3",
                  None) for i in range(4500)]
        table += [("", 1, "verdict", None, None, "fails"), ("", 2, "notice", None, None, "x")]
        points = [(gpkg_wkb.encode_geometry("POINT", np.array([705_000.0 + i * 0.37,
                                                              4_401_000.0 - i * 0.11]), 25830,
                                            False), 1 + i % 3, f"recinto_{i % 500}", 1 + i,
                   float(i + 1), float((i + 1) * 3.3), float(i % 7)) for i in range(3300)]
        for family, rows in ((cstore.TABLE, tuple(table)), (cstore.GROUPS, tuple(points))):
            with self.subTest(family=family):
                steps = cstore._digest_steps(family, rows, crs)
                units = sum(1 for _ in _units(steps))
                self.assertGreater(units, 5)
                self.assertEqual(cstore._digest(family, rows, crs), old_digest(family, rows, crs))


def _units(steps: Iterator[None]) -> Iterator[None]:
    while True:
        try:
            yield next(steps)
        except StopIteration:
            return


if __name__ == "__main__":
    unittest.main()
