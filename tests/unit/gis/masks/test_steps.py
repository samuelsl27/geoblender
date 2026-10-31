# SPDX-License-Identifier: GPL-3.0-or-later
"""Compilar por pasos cortos, con lo mismo de siempre (spec 012, T35; RNF-012-01, RNF-012-03 y
RNF-012-06; plan 012 §5.2.3, A3, A5, R4).

La T35 acorta los pasos de ``compile_steps`` (la prueba de escala está en
``tests/rendimiento/gis/test_masks_perf.py``) **sin cambiar ningún resultado**: aquí, lo que lo
fija de forma rápida, cada cosa frente al cálculo de antes escrito en la propia prueba.

- **RF-012-04**: ``check_steps`` da lo mismo que ``check``, con un paso por restricción y por
  polígono, y la geometría ya comprobada no se vuelve a comprobar (se recuerda por su huella).
- **RF-012-13, RF-012-14**: ``combine_steps`` da, por pasos, las máscaras de ``combine`` de
  antes (el cuerpo de entonces va en :func:`combine_at_once`): el caso a mano de la T09 y 14
  casos al azar con los once tipos; los conflictos, los de la matriz celda × causa.
- **RF-012-11, RF-012-12**: las zonas no calculan las bandas de filas que sus aristas no tocan, y
  salen las mismas celdas con el mismo número de pasos que calculándolas todas.
- **RF-012-05**: ``report_steps`` da el informe de ``limits_report`` en cuatro pasos.
- **RF-012-16, RF-012-28**: los hashes de las tablas por tramos (``_digest_steps``) son los de
  una sola vez; ``pace_units`` junta las unidades en pasos y cierra su trabajo al cerrarse.
- Los tramos: ``Runs.mask`` frente a la suma de bordes de antes, ``Runs.between_rows`` y la
  ordenación por clave compuesta frente a ``np.lexsort``.
"""

import sqlite3
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from tests.support.package import import_geoblender
from tests.unit.gis.masks.test_combine import GRID, G, T, make, resolved_for, site

georef = import_geoblender("core.georef")
params = import_geoblender("core.constraints.params")
combine = import_geoblender("gis.masks.combine")
compile_mod = import_geoblender("gis.masks.compile")
overlay_mod = import_geoblender("gis.masks.overlay")
provenance = import_geoblender("gis.masks.provenance")
store = import_geoblender("gis.masks.store")
zones = import_geoblender("gis.masks.zones")
polygons = import_geoblender("gis.polygons")
builtin = import_geoblender("core.content.builtin")
encoder = import_geoblender("core.content.encoder")
datasets_model = import_geoblender("core.datasets.model")
gpkg_base = import_geoblender("core.gpkg.base")
gis_store = import_geoblender("gis.store")

Runs = zones.Runs
CRS = georef.load_catalog().horizontal(25830)
VERTICAL = georef.load_catalog().vertical(5782)


def count_units(steps):
    """(unidades, lo que devuelve) de un generador de pasos."""
    count = 0
    while True:
        try:
            next(steps)
        except StopIteration as stop:
            return count, stop.value
        count += 1


# --- Los tramos ------------------------------------------------------------------------------


def old_mask(runs, shape, offset=(0, 0)):
    """``Runs.mask`` de antes del HITO T35: bordes sumados con ``np.add.at`` en enteros de 64
    bits."""
    height, width = int(shape[0]), int(shape[1])
    row = runs.row - offset[0]
    col0 = np.clip(runs.col0 - offset[1], 0, width)
    col1 = np.clip(runs.col1 - offset[1], 0, width)
    keep = (row >= 0) & (row < height) & (col1 > col0)
    row, col0, col1 = row[keep], col0[keep], col1[keep]
    marks = np.zeros((height, width + 1), dtype=np.int64)
    np.add.at(marks, (row, col0), 1)
    np.add.at(marks, (row, col1), -1)
    return np.cumsum(marks, axis=1)[:, :width] > 0


class RunsTest(unittest.TestCase):
    """Los tramos de fila, más deprisa y lo mismo."""

    def test_mask_equals_the_additive_reference(self) -> None:
        """La máscara de ``Runs.mask`` es la de sumar bordes de antes, también con tramos fuera
        de la ventana, recortados y con ``offset`` (300 casos al azar)."""
        rng = np.random.default_rng(35)
        for case in range(300):
            count = int(rng.integers(0, 50))
            height, width = int(rng.integers(1, 12)), int(rng.integers(1, 30))
            col0 = rng.integers(-10, width + 10, count)
            runs = Runs(rng.integers(-3, height + 3, count), col0,
                        col0 + rng.integers(0, 12, count))
            offset = (int(rng.integers(-3, 4)), int(rng.integers(-5, 6)))
            got = runs.mask((height, width), offset)
            self.assertEqual(got.dtype, np.bool_)
            np.testing.assert_array_equal(got, old_mask(runs, (height, width), offset), str(case))

    def test_between_rows(self) -> None:
        """``between_rows`` da los tramos de esas filas (ambas incluidas) y nada más."""
        rng = np.random.default_rng(36)
        col0 = rng.integers(0, 60, 80)
        runs = Runs(rng.integers(0, 30, 80), col0, col0 + rng.integers(1, 9, 80))
        for first, last in ((0, 29), (5, 5), (7, 12), (-4, 3), (25, 99), (12, 8)):
            part = runs.between_rows(first, last)
            keep = (runs.row >= first) & (runs.row <= last)
            np.testing.assert_array_equal(part.row, runs.row[keep])
            np.testing.assert_array_equal(part.col0, runs.col0[keep])
            np.testing.assert_array_equal(part.col1, runs.col1[keep])
        self.assertEqual(Runs.empty().between_rows(0, 9), Runs.empty())

    def test_order_equals_lexsort(self) -> None:
        """La ordenación por una clave compuesta es la estable de ``np.lexsort`` (empates
        incluidos), y con una clave que no cabe en 62 bits cae en ella."""
        rng = np.random.default_rng(37)
        for size in (1, 7, 300, 5000):
            row = rng.integers(-5, 40, size)
            col = rng.integers(-20, 90, size)
            row[1::2] = row[0::2][:row[1::2].size]  # empates en fila y en columna
            col[1::2] = col[0::2][:col[1::2].size]
            np.testing.assert_array_equal(zones._order(row, col), np.lexsort((col, row)))
        row = np.array([3, 3, 1, 1, 3], dtype=np.int64)
        col = np.array([0, 1 << 61, 1 << 59, 0, 5], dtype=np.int64)
        with mock.patch.object(np, "argsort", side_effect=AssertionError("clave desbordada")):
            np.testing.assert_array_equal(zones._order(row, col), np.lexsort((col, row)))


# --- Comprobar --------------------------------------------------------------------------------


class CheckStepsTest(unittest.TestCase):
    """RF-012-04: ``check_steps`` y la memoria de la geometría ya comprobada."""

    def items(self):
        legal = make("r_concesion", T.LEGAL_LIMIT, (0, 0, 30, 30), fid=1)
        lazo = make("r_lazo", T.NO_CUT, coords=[(2, 2), (6, 6), (6, 2), (2, 6), (2, 2)], fid=2)
        plana = make("r_plana", T.NO_FILL, coords=[(2, 2), (6, 2), (10, 2), (2, 2)], fid=3)
        torre = make("r_torre", T.UNTOUCHABLE, kind=G.POINT, coords=[(8, 8)], fid=4)
        balsa = make("r_balsa", T.NO_FILL, (12, 12, 16, 16), fid=5)
        return [legal, lazo, plana, torre, balsa]

    def test_steps_give_the_same_and_remember_the_geometry(self) -> None:
        """Por pasos sale lo mismo que ``check`` (en frío y con la geometría recordada), con
        más de un paso por restricción, y la segunda vez no se vuelve a comprobar ningún
        polígono."""
        items = self.items()
        resolved = resolved_for(items, extra={params.buffer_out_key("r_torre"): 2.0})
        combine._PROBLEMS_MEMO.clear()
        units, cold = count_units(combine.check_steps(items, resolved))
        self.assertGreater(units, len(items))
        self.assertEqual([(p.code, p.problem) for p in cold],
                         [("r_lazo", "core.constraint_self_intersecting"),
                          ("r_plana", "core.constraint_no_area")])
        with mock.patch.object(combine, "problem_steps",
                               side_effect=AssertionError("ya estaba comprobada")):
            warm = combine.check(items, resolved)
        self.assertEqual(warm, cold)
        combine._PROBLEMS_MEMO.clear()
        self.assertEqual(combine.check(items, resolved), cold)

    def test_a_changed_geometry_is_checked_again(self) -> None:
        """La memoria es por la huella de las coordenadas: la misma restricción con otra
        geometría se comprueba de nuevo."""
        combine._PROBLEMS_MEMO.clear()
        valid = make("r_balsa", T.NO_FILL, (12, 12, 16, 16), fid=5)
        crossed = make("r_balsa", T.NO_FILL, coords=[(2, 2), (6, 6), (6, 2), (2, 6), (2, 2)],
                       fid=5)
        resolved = resolved_for([valid])
        self.assertEqual(combine.check([valid], resolved), ())
        found = combine.check([crossed], resolved)
        self.assertEqual([p.problem for p in found], ["core.constraint_self_intersecting"])
        self.assertEqual(combine.check([valid], resolved), ())


# --- Combinar ---------------------------------------------------------------------------------


def combine_at_once(zones_map, limits, grid):
    """``combine`` de antes del HITO T35: todo de una vez, las máscaras de la rejilla de clases
    una a una con ``np.add.at`` y los conflictos con la matriz celda × causa."""
    from tests.unit.gis.masks.test_combine import _dense_conflicts

    items = [zone for zone in zones_map.values() if not zone.ctype.is_limit]
    perimeter, legal = limits.perimeter, limits.legal
    untouchable = combine._union(items, lambda t: t.removes_from_domain)
    no_cut = combine._union(items, lambda t: t.forbids_cut and not t.removes_from_domain)
    no_fill = combine._union(items, lambda t: t.forbids_fill and not t.removes_from_domain)
    domain = perimeter.intersection(legal.inside).difference(untouchable)
    cut = domain.difference(legal.band).difference(no_cut)
    fill = domain.difference(no_fill)
    strip = perimeter.difference(legal.inside).difference(untouchable).difference(no_fill)
    restoration = combine._union(items, lambda t: t is T.RESTORATION_ONLY)
    access = combine._union(items, lambda t: t is T.REQUIRES_ACCESS)
    avoid_runs = combine._union(items, lambda t: t is T.AVOID)
    blocked = (perimeter.difference(untouchable).difference(cut).difference(fill)
               .difference(strip))
    candidates = [(code, blocked.difference(legal.core)) for code in limits.legal_codes]
    candidates += [(z.code, z.runs) for z in items
                   if (z.ctype.forbids_cut or z.ctype.forbids_fill)
                   and not z.ctype.removes_from_domain]
    conflicts = _dense_conflicts(blocked, candidates, grid, zones_map)
    classes = np.zeros(grid.shape, dtype=np.uint16)
    for bit, runs in ((1, cut), (2, fill), (4, strip), (8, perimeter), (16, legal.inside),
                      (32, legal.band), (64, untouchable), (128, avoid_runs),
                      (256, restoration), (512, access),
                      (1024, Runs.union_all(c.runs for c in conflicts))):
        if len(runs):
            classes[old_mask(runs, grid.shape)] |= np.uint16(bit)
    return untouchable, domain, cut, fill, strip, restoration, access, avoid_runs, conflicts, classes


def assert_masks_same(case, masks, wanted):
    untouchable, domain, cut, fill, strip, restoration, access, avoid_runs, conflicts, classes = (
        wanted)
    for name, runs in (("untouchable", untouchable), ("default_domain", domain),
                       ("cut_allowed", cut), ("fill_allowed", fill), ("fill_strip", strip),
                       ("restoration", restoration), ("access", access)):
        case.assertEqual(getattr(masks, name), runs, name)
    case.assertEqual([(c.causes, c.area_m2) for c in masks.conflicts],
                     [(c.causes, c.area_m2) for c in conflicts])
    for a, b in zip(masks.conflicts, conflicts, strict=True):
        case.assertEqual(a.runs, b.runs)
    np.testing.assert_array_equal(masks.classes, classes)
    case.assertEqual(masks.classes.dtype, classes.dtype)


class CombineStepsTest(unittest.TestCase):
    """RF-012-13, RF-012-14: ``combine_steps`` da lo de antes."""

    def test_the_site_by_steps(self) -> None:
        """El caso a mano de la T09 (712, 584, 708 y 140 celdas): las máscaras y la rejilla de
        clases de ``combine_steps`` son las de antes, en más de 15 pasos."""
        items, resolved = site()
        prepared = combine.prepare(items, resolved, GRID)
        units, masks = count_units(combine.combine_steps(prepared.zones, prepared.limits, GRID))
        self.assertGreater(units, 15)
        assert_masks_same(self, masks, combine_at_once(prepared.zones, prepared.limits, GRID))
        self.assertEqual((masks.default_domain.cells, masks.cut_allowed.cells,
                          masks.fill_allowed.cells, masks.fill_strip.cells),
                         (712, 584, 708, 140))
        again = combine.combine(prepared.zones, prepared.limits, GRID)
        np.testing.assert_array_equal(again.classes, masks.classes)

    def test_random_sites(self) -> None:
        """14 sitios al azar con los once tipos (rectángulos que se pisan, límites partidos
        y tipos repetidos): lo mismo que antes, también los conflictos."""
        rng = np.random.default_rng(350)
        kinds = [t for t in T if not t.is_limit]
        legal_total = 0
        for case in range(14):
            west, south = int(rng.integers(0, 12)), int(rng.integers(0, 10))
            items = [make("r_concesion", T.LEGAL_LIMIT,
                          (west, south, west + int(rng.integers(15, 28)),
                           south + int(rng.integers(12, 20))), fid=1),
                     make("r_perimetro", T.ACTION_PERIMETER,
                          (west + 2, south + 1, west + int(rng.integers(20, 36)),
                           south + int(rng.integers(10, 24))), fid=2)]
            for index in range(int(rng.integers(6, 20))):
                left, bottom = int(rng.integers(2, 32)), int(rng.integers(2, 22))
                items.append(make(f"r_z{index:02d}", kinds[int(rng.integers(len(kinds)))],
                                  (left, bottom, left + int(rng.integers(2, 8)),
                                   bottom + int(rng.integers(2, 8))),
                                  priority=int(rng.integers(0, 3)), fid=3 + index))
            prepared = combine.prepare(items, resolved_for(items, inward=float(case % 3)), GRID)
            masks = combine.combine(prepared.zones, prepared.limits, GRID)
            assert_masks_same(self, masks, combine_at_once(prepared.zones, prepared.limits, GRID))
            legal_total += len(masks.conflicts)
        self.assertGreater(legal_total, 8)

    def test_report_by_steps(self) -> None:
        """RF-012-05: el informe de los límites por pasos (cuatro superposiciones) es el de
        ``limits_report``, con perímetro y sin él."""
        items, resolved = site()
        prepared = combine.prepare(items, resolved, GRID)
        units, report = count_units(overlay_mod.report_steps(prepared, GRID))
        self.assertEqual(units, 3)
        origin = (GRID.west, GRID.extent.ymin)
        legal, perimeter = prepared.legal, prepared.perimeter
        wanted = (polygons.overlay(legal, [], "union", origin=origin).area_m2,
                  polygons.overlay(perimeter, [], "union", origin=origin).area_m2,
                  polygons.overlay(perimeter, legal, "intersection", origin=origin).area_m2,
                  polygons.overlay(perimeter, legal, "difference", origin=origin))
        self.assertEqual((report.legal_m2, report.perimeter_m2, report.intersection_m2),
                         wanted[:3])
        self.assertEqual(report.strip_m2, wanted[3].area_m2)
        self.assertEqual([(p.area_m2, tuple(p.centroid)) for p in report.strip_parts],
                         [(p.area_m2, tuple(p.centroid)) for p in wanted[3].parts])
        again = overlay_mod.report_of(prepared, GRID)
        self.assertEqual((again.legal_m2, again.perimeter_m2, again.intersection_m2,
                          again.strip_m2), (report.legal_m2, report.perimeter_m2,
                                            report.intersection_m2, report.strip_m2))
        only_legal = [make("r_concesion", T.LEGAL_LIMIT, (0, 0, 30, 30), fid=1)]
        prepared = combine.prepare(only_legal, resolved_for(only_legal), GRID)
        units, alone = count_units(overlay_mod.report_steps(prepared, GRID))
        self.assertEqual(units, 1)
        self.assertEqual((alone.perimeter_from_legal, alone.strip_m2, alone.strip_parts),
                         (True, 0.0, ()))


# --- Las zonas --------------------------------------------------------------------------------


class InsideBandsTest(unittest.TestCase):
    """RF-012-11, RF-012-12: las bandas que las aristas no tocan no se calculan."""

    def polygon(self, rng):
        """Un polígono simple (una estrella de nueve vértices) en el medio de ``GRID``."""
        angles = np.sort(rng.uniform(0.0, 2 * np.pi, 9))
        ring = np.column_stack([20.0 + rng.uniform(5, 14) * np.cos(angles),
                                15.0 + rng.uniform(4, 11) * np.sin(angles)])
        return make("r_p", T.NO_CUT, coords=ring, fid=1)

    def test_untouched_bands_give_the_same_zone_in_the_same_units(self) -> None:
        """Con bandas de 1 a 9 filas (y límites enteros dentro): las mismas celdas que
        calculando todas las bandas y el mismo número de pasos (uno por banda)."""
        rng = np.random.default_rng(351)
        skipped = 0
        for case in range(8):
            item = self.polygon(rng)
            edges = zones.edges_of(item, GRID)
            size = int(rng.integers(1, 10))
            for whole in (False, True):
                found: list = []
                units, _ = count_units(zones._inside_steps(edges, GRID, size, whole, found))
                self.assertEqual(units, -(-GRID.nrows // size))
                every = [zones.inside_runs(edges, GRID, whole=whole,
                                           rows=slice(begin, begin + size))
                         for begin in range(0, GRID.nrows, size)]
                self.assertEqual(Runs.union_all(found), Runs.union_all(every), str((case, whole)))
                skipped += len(every) - len(found)
            self.assertEqual(zones.zone_runs(item, GRID, 0.0, rows_per_step=size),
                             zones.zone_runs(item, GRID, 0.0))
        self.assertGreater(skipped, 20)

    def test_every_band_is_computed_when_the_edges_are_not_finite(self) -> None:
        """Con aristas no finitas se calculan todas las bandas, y fallan como siempre."""
        edges = np.array([[[1.0, 1.0], [np.nan, 4.0]], [[np.nan, 4.0], [3.0, 1.0]]])
        with self.assertRaises(ValueError):
            count_units(zones._inside_steps(edges, GRID, 5, False, []))
        found: list = []
        units, _ = count_units(zones._inside_steps(np.zeros((0, 2, 2)), GRID, 5, False, found))
        self.assertEqual((units, found), (6, [zones.Runs.empty()] * 6))


# --- Guardar ----------------------------------------------------------------------------------


def old_digest(family, rows, crs):
    """``_digest`` de antes del HITO T35: todas las filas de una vez."""
    conn = sqlite3.connect(":memory:")
    try:
        gpkg_base.create_base(conn, crs)
        store._create(conn, family, "digest", crs.epsg, "digest")
        gis_store.insert_rows(conn, "digest", store._names(family), rows)
        kind = provenance.FAMILIES_BY_CODE[family].kind
        request = builtin.GPKG_LAYER.request(kind, datasets_model.DATASET_DECLARATIONS,
                                             {"main": Path("digest")}, {"layer": "digest"},
                                             normalizer=encoder.NORMALIZER)
        for _done in builtin.layer_steps(conn, request):
            pass
        return request.hasher.digest()
    finally:
        conn.close()


class SavingTest(unittest.TestCase):
    """RF-012-16, RF-012-28: los hashes de las tablas y los pasos de guardar."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.items, resolved = site()
        request = compile_mod.CompileRequest(tuple(cls.items), resolved, grid=GRID)
        cls.result = None
        for step in compile_mod.compile_steps(request):
            if step.result is not None:
                cls.result = step.result

    def test_digests_by_chunks_equal_the_one_shot_digest(self) -> None:
        """Las cuatro tablas, con trozos de 3 filas (y de 4.000): el hash de ``core.gpkg_layer@1``
        es el de meter todas las filas de una vez, y se hace en más de un paso."""
        for family in (provenance.ZONES, provenance.REPORT, provenance.PARTS, provenance.SHAPES):
            rows = tuple(store._rows(family, self.result, self.items, CRS.epsg))
            self.assertTrue(rows, family)
            wanted = old_digest(family, rows, CRS)
            with self.subTest(family=family):
                units, digest = count_units(store._digest_steps(family, rows, CRS))
                self.assertGreater(units, 1)
                self.assertEqual(digest, wanted)
                with mock.patch.object(store, "_DIGEST_ROWS_PER_UNIT", 3):
                    small, digest = count_units(store._digest_steps(family, rows, CRS))
                self.assertGreaterEqual(small, units)
                self.assertEqual(digest, wanted)


class ScaleDataTest(unittest.TestCase):
    """Los datos de escala de ``plan.md`` §2.2 (``tests/support/constraints_scale.py``)."""

    def test_the_data_of_the_plan_and_the_seed(self) -> None:
        """500 restricciones con 100.518 vértices: el límite legal y el perímetro de 2.000
        vértices, 30 puntos, 30 líneas y 40 polígonos con resguardo de 5 a 50 m y 398 polígonos
        sin él; los mismos, bit a bit, con la misma semilla."""
        from tests.support import constraints_scale as scale

        made = scale.build_constraints()
        rows = made.rows
        self.assertEqual((len(rows), made.vertices), (500, 100_518))
        kinds = {kind: sum(1 for row in rows if row.kind is kind) for kind in G}
        self.assertEqual(kinds, {G.POINT: 30, G.LINE: 30, G.POLYGON: 440})
        self.assertEqual([len(row.parts[0][0]) for row in rows[:2]], [2001, 2001])
        self.assertEqual([row.ctype for row in rows[:2]], [T.LEGAL_LIMIT, T.ACTION_PERIMETER])
        buffers = [made.values[params.buffer_out_key(row.code)] for row in rows[2:102]]
        self.assertTrue(all(5.0 <= value <= 50.0 for value in buffers))
        self.assertEqual(sum(1 for row in rows[102:]
                             if made.values[params.buffer_out_key(row.code)] == 0.0), 398)
        self.assertEqual(len({row.code for row in rows}), 500)
        again = scale.build_constraints()
        self.assertEqual(again.values, made.values)
        for first, second in zip(rows, again.rows, strict=True):
            np.testing.assert_array_equal(first.parts[0][0], second.parts[0][0])


class PaceTest(unittest.TestCase):
    """``pace_units`` junta las unidades de un trabajo en pasos."""

    def test_groups_units_and_returns_the_value(self) -> None:
        """Con un presupuesto enorme todo cabe en un paso y con uno ínfimo cada unidad es un
        paso; en los dos devuelve lo del trabajo."""
        def work(count):
            for _ in range(count):
                yield
            return "listo"

        steps = compile_mod.pace_units(work(10), 1e9)
        self.assertEqual(count_units(steps), (0, "listo"))
        steps = compile_mod.pace_units(work(10), 1e-12)
        self.assertEqual(count_units(steps), (10, "listo"))

    def test_closing_closes_the_work(self) -> None:
        """Cerrar los pasos cierra el trabajo (Esc), que limpia lo suyo."""
        closed = []

        def work():
            try:
                while True:
                    yield
            finally:
                closed.append(True)

        steps = compile_mod.pace_units(work(), 1e-12)
        next(steps)
        steps.close()
        self.assertEqual(closed, [True])


if __name__ == "__main__":
    unittest.main()
