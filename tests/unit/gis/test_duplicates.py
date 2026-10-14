# SPDX-License-Identifier: GPL-3.0-or-later
"""Puntos duplicados y su resolución (spec 006, T16; plan 006 §5.3.2 y §5.4 A7,
``gis.points.find_duplicates`` y ``resolve_duplicates``).

- **RF-006-14**: dos puntos que coinciden en planta a ≤ 1 mm (``gis.points.dup_xy_tol_m``)
  con cotas que difieren ≤ 0,01 m (``gis.points.dup_z_tol_m``, D-5) se funden: se conserva
  el primero, con sus coordenadas exactas, y se cuentan. Si las cotas difieren más, es un
  conflicto con los dos identificadores, la posición X, Y y las dos cotas; el TIN no se crea
  hasta que el usuario elige cómo resolverlo: media, mínima, máxima, primero o cancelar
  («preguntar», por defecto, lanza el error con la lista para que elija).
- A7: cubetas de lado ``tol_xy`` y las 9 vecinas; los grupos son las componentes de «a ≤
  ``tol_xy`` en planta». Se comprueba frente a la fuerza bruta en nubes aleatorias con
  duplicados a uno y otro lado de los bordes de las cubetas.
- **RF-006-12** (de paso): el informe de la importación cuenta los duplicados de
  ``points/errores.csv`` (P 7, fundido con P 6, y P 9, en conflicto con P 8).

Las entradas no se modifican (arrays de solo lectura).
"""

import dataclasses
import math
import unittest

import numpy as np

from tests.support.package import import_geoblender
from tests.support.repo import ROOT

gis = import_geoblender("gis")
points = import_geoblender("gis.points")
reports = import_geoblender("gis.reports")
messages = import_geoblender("gis.messages")
ParamError = import_geoblender("core.params").ParamError
csv_tables = import_geoblender("interop.csv_tables")

ERRORES = ROOT / "tests" / "data" / "gis" / "points" / "errores.csv"
ROLES = {"point_id": "P", "x": "X", "y": "Y", "z": "Z", "code": "Código", "line": "Línea"}
E0, N0 = 700_000.0, 4_400_000.0
XY_KEY = "gis.points.dup_xy_tol_m"
Z_KEY = "gis.points.dup_z_tol_m"


def _frozen(array: np.ndarray) -> np.ndarray:
    array = np.array(array, dtype=np.float64)
    array.flags.writeable = False  # una entrada nunca se modifica
    return array


def _point_set(*rows: tuple) -> object:
    """Un ``PointSet`` de filas (P, x, y, z) con x, y relativos a (E0, N0)."""
    xyz = _frozen([(E0 + x, N0 + y, z) for _p, x, y, z in rows]).reshape(-1, 3)
    ids = tuple(str(p) for p, *_ in rows)
    return points.PointSet(xyz, ids, ("TN",) * len(rows), tuple(range(2, 2 + len(rows))))


def _errores():
    """``points/errores.csv`` como lo importa la T15: 6 puntos (P 1, 2, 6, 7, 8 y 9)."""
    table = csv_tables.read_table(ERRORES, encoding="utf-8", separator=";")
    mapping = points.ColumnMapping.by_name(table.columns, **ROLES)
    point_set, _lines, report = points.points_from_rows(
        table.columns, table.rows, mapping, ",", source="errores.csv",
        row_numbers=table.lines,
    )
    frozen = points.PointSet(_frozen(point_set.xyz), point_set.point_ids, point_set.codes,
                             point_set.source_rows)
    return frozen, report


def _find(point_set, **options):
    return points.find_duplicates(point_set.xyz, ids=point_set.point_ids, **options)


def _brute_groups(xyz: np.ndarray, tol_xy: float) -> list[tuple[int, ...]]:
    """Componentes de «a ≤ tol_xy en planta» por fuerza bruta (todas las parejas)."""
    delta = xyz[:, None, :2] - xyz[None, :, :2]
    near = np.hypot(delta[..., 0], delta[..., 1]) <= tol_xy
    seen = np.zeros(len(xyz), dtype=bool)
    groups = []
    for start in range(len(xyz)):
        if seen[start]:
            continue
        stack, members = [start], []
        seen[start] = True
        while stack:
            node = stack.pop()
            members.append(node)
            for other in np.flatnonzero(near[node] & ~seen):
                seen[other] = True
                stack.append(int(other))
        if len(members) > 1:
            groups.append(tuple(sorted(members)))
    return sorted(groups)


class ErroresCsvTest(unittest.TestCase):
    """RF-006-14 y RF-006-12 con ``points/errores.csv``."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.points, cls.import_report = _errores()

    def test_merged_and_conflict(self) -> None:
        """RF-006-14: P 7 (a 0,5 mm de P 6, Δz 0,004 m) se funde y se cuenta; P 9 (a 0,64 mm
        de P 8, Δz 0,25 m) es un conflicto con sus identificadores, la posición de P 8 y
        las dos cotas."""
        self.assertEqual(self.points.point_ids, ("1", "2", "6", "7", "8", "9"))
        report = _find(self.points)
        self.assertIsInstance(report, points.DuplicateReport)
        self.assertEqual(report.count, 6)
        self.assertEqual((report.tol_xy, report.tol_z), (0.001, 0.01))
        self.assertEqual(report.groups, (points.DuplicateGroup((2, 3), False),
                                         points.DuplicateGroup((4, 5), True)))
        self.assertEqual((report.merged, report.duplicates), (1, 2))
        self.assertEqual(report.conflicts, (gis.Conflict(
            gis.ConflictKind.DUPLICATE_POINTS, ("8", "9"), 700_010.0, 4_400_010.0,
            (811.0, 811.25)),))
        self.assertAlmostEqual(report.conflicts[0].dz, 0.25, places=12)

    def test_import_report_counts_duplicates(self) -> None:
        """RF-006-12: el informe de la importación lleva los 2 duplicados (fundido y en
        conflicto) además de sus 7 filas rechazadas."""
        report = _find(self.points)
        counted = dataclasses.replace(self.import_report, duplicates=report.duplicates)
        self.assertEqual((counted.points, counted.duplicates, counted.rejected_count),
                         (6, 2, 7))

    def test_policies(self) -> None:
        """RF-006-14: las cinco políticas. Media, mínima, máxima y primero dan 4 puntos (P 7
        siempre fundido con P 6): la media deja P 8 en su sitio con 811,125 m; la mínima y
        «primero», P 8 tal cual; la máxima, P 9 tal cual (sus coordenadas exactas). Cancelar
        lanza el error con la lista y no da puntos."""
        report = _find(self.points)
        xyz = self.points.xyz
        base = [xyz[0], xyz[1], xyz[2]]
        cases = {
            points.DuplicatePolicy.MEAN: ([*base, (xyz[4, 0], xyz[4, 1], 811.125)],
                                          ("1", "2", "6", "8"), (2, 3, 7, 9)),
            points.DuplicatePolicy.MIN: ([*base, xyz[4]], ("1", "2", "6", "8"), (2, 3, 7, 9)),
            points.DuplicatePolicy.MAX: ([*base, xyz[5]], ("1", "2", "6", "9"), (2, 3, 7, 10)),
            points.DuplicatePolicy.FIRST: ([*base, xyz[4]], ("1", "2", "6", "8"),
                                           (2, 3, 7, 9)),
        }
        for policy, (want, ids, rows) in cases.items():
            with self.subTest(politica=policy.value):
                result = points.resolve_duplicates(self.points, report, policy)
                self.assertIsInstance(result, points.PointSet)
                self.assertEqual(result.xyz.tobytes(), np.array(want).tobytes())
                self.assertEqual(result.point_ids, ids)
                self.assertEqual(result.source_rows, rows)
                self.assertEqual(result.codes, ("TN",) * 4)
        with self.assertRaises(gis.ConflictError) as caught:
            points.resolve_duplicates(self.points, report, "cancel", name="topo")
        self.assertEqual(caught.exception.code, "gis.duplicates_cancelled")
        self.assertEqual(caught.exception.conflicts, report.conflicts)

    def test_ask_lists_the_conflicts(self) -> None:
        """RF-006-14: con «preguntar» (por defecto) el TIN no se crea: el error lista cada
        conflicto con sus identificadores, su posición y sus dos cotas, y pide elegir."""
        report = _find(self.points)
        for policy in (points.DuplicatePolicy.ASK, "ask"):
            with self.assertRaises(gis.ConflictError) as caught:
                points.resolve_duplicates(self.points, report, policy, name="topo_2026")
            error = caught.exception
            self.assertIsInstance(error, messages.GisError)
            self.assertEqual(error.code, "gis.duplicate_conflicts")
            self.assertEqual(error.value, 1)
            self.assertEqual(error.text, messages.render(
                "gis.duplicate_conflicts", tin="topo_2026", value=1, tol_xy=0.001, tol_z=0.01))
            self.assertIn("media, mínima, máxima, primero o cancelar", error.text)
            self.assertEqual(error.texts(), [
                "TIN «topo_2026»: los puntos «8» y «9» coinciden en planta en "
                "(700 010,000; 4 400 010,000) con cotas 811,000 m y 811,250 m."
            ])

    def test_policy_text_and_unknown(self) -> None:
        """Las políticas también por su texto; una desconocida es un error del programa."""
        self.assertEqual([p.value for p in points.DuplicatePolicy],
                         ["ask", "mean", "min", "max", "first", "cancel"])
        report = _find(self.points)
        self.assertEqual(len(points.resolve_duplicates(self.points, report, "mean")), 4)
        with self.assertRaises(ValueError):
            points.resolve_duplicates(self.points, report, "median")
        other = _point_set(("A", 0, 0, 1))
        with self.assertRaises(ValueError):
            points.resolve_duplicates(other, report, "first")


class ToleranceTest(unittest.TestCase):
    """RF-006-14: los límites de las tolerancias (1 mm y 0,01 m, incluidos) y su origen."""

    def test_limits(self) -> None:
        """A 0,9 mm se juntan y a 1,1 mm no; Δz de 0,01 m se funde y de 0,0101 m es
        conflicto. La resolución sin conflictos no depende de la política."""
        cases = (
            ((0.0009, 0.0, 800.0), 1, 0),
            ((0.0011, 0.0, 800.0), 0, 0),
            ((0.0006, 0.0006, 800.01), 1, 0),
            ((0.0, 0.0009, 800.0101), 0, 1),
        )
        for (x, y, z), merged, conflicts in cases:
            with self.subTest(x=x, y=y, z=z):
                point_set = _point_set(("A", 0.0, 0.0, 800.0), ("B", x, y, z))
                report = _find(point_set)
                self.assertEqual((report.merged, len(report.conflicts)), (merged, conflicts))
                if not conflicts:
                    result = points.resolve_duplicates(point_set, report, "ask")
                    self.assertEqual(len(result), 2 - merged)
                    self.assertEqual(result.xyz[0].tobytes(), point_set.xyz[0].tobytes())

    def test_explicit_tolerances_and_defaults(self) -> None:
        """Las tolerancias por defecto salen de ``gis/params.py``; las explícitas se validan
        (``ParamError`` ``core.param_*`` con la clave como campo; RF-006-14)."""
        self.assertEqual(points.duplicate_tolerances(None, None), (
            gis.param(XY_KEY).default, gis.param(Z_KEY).default))
        point_set = _point_set(("A", 0.0, 0.0, 800.0), ("B", 0.004, 0.0, 800.3))
        self.assertEqual(_find(point_set).duplicates, 0)
        wide = _find(point_set, tol_xy=0.005, tol_z=0.5)
        self.assertEqual((wide.tol_xy, wide.tol_z, wide.merged), (0.005, 0.5, 1))
        for key, options in ((XY_KEY, {"tol_xy": 0.0}), (XY_KEY, {"tol_xy": 2.0}),
                             (Z_KEY, {"tol_z": -0.01}), (Z_KEY, {"tol_z": "0,01"})):
            with self.subTest(**options):
                with self.assertRaises(ParamError) as caught:
                    _find(point_set, **options)
                self.assertTrue(caught.exception.code.startswith("core.param_"))
                self.assertEqual(caught.exception.field, key)
        with self.assertRaises(ParamError) as caught:
            points.duplicate_tolerances(2.0, None)
        self.assertEqual((caught.exception.code, caught.exception.field),
                         ("core.param_out_of_range", XY_KEY))

    def test_identifiers_and_inputs(self) -> None:
        """Sin identificadores, cada punto se nombra por su posición («#1»…); coordenadas no
        finitas o con otra forma son un error del programa."""
        xyz = _frozen([(E0, N0, 800.0), (E0 + 0.0003, N0, 801.0)])
        report = points.find_duplicates(xyz)
        self.assertEqual(report.conflicts[0].ids, ("#1", "#2"))
        self.assertEqual(points.find_duplicates(np.empty((0, 3))).groups, ())
        for bad in (np.array([[E0, N0, math.nan]]), np.zeros((2, 2)),
                    np.zeros((2, 3), dtype=np.float32)):
            with self.subTest(forma=bad.shape, tipo=str(bad.dtype)):
                with self.assertRaises((TypeError, ValueError)):
                    points.find_duplicates(bad)
        with self.assertRaises(ValueError):
            points.find_duplicates(xyz, ids=("A",))


class GroupsTest(unittest.TestCase):
    """A7: grupos y conflictos frente a la fuerza bruta."""

    def test_cell_borders(self) -> None:
        """Parejas a 0,2 µm a uno y otro lado de un borde de cubeta, en las direcciones
        horizontal, diagonal y antidiagonal, se encuentran."""
        e = 1e-7
        point_set = _point_set(
            ("A", 0.0, 0.0, 800.0),
            ("B", 0.5 - e, 0.3, 800.0), ("C", 0.5 + e, 0.3, 800.0),
            ("D", 0.7 - e, 0.7 - e, 800.0), ("E", 0.7 + e, 0.7 + e, 800.0),
            ("F", 0.9 - e, 0.9 + e, 800.0), ("G", 0.9 + e, 0.9 - e, 800.0),
        )
        report = _find(point_set)
        self.assertEqual([g.indices for g in report.groups], [(1, 2), (3, 4), (5, 6)])

    def test_chains_and_conflict_pairs(self) -> None:
        """Un grupo de tres en cadena (A–B y B–C a ≤ 1 mm, A–C a 1,6 mm): un solo grupo que
        conserva A. Sus parejas con Δz > 0,01 m se listan; si ninguna pareja vecina pasa
        de 0,01 m pero el grupo sí (0,006 + 0,006), se lista la de la mínima y la máxima."""
        point_set = _point_set(("A", 0.0, 0.0, 800.0), ("B", 0.0008, 0.0, 800.5),
                               ("C", 0.0016, 0.0, 800.0))
        report = _find(point_set)
        self.assertEqual(report.groups, (points.DuplicateGroup((0, 1, 2), True),))
        self.assertEqual([c.ids for c in report.conflicts], [("A", "B"), ("B", "C")])
        self.assertEqual(report.conflicts[1].z, (800.5, 800.0))
        chain = _point_set(("A", 0.0, 0.0, 800.0), ("B", 0.0008, 0.0, 800.006),
                           ("C", 0.0016, 0.0, 800.012))
        report = _find(chain)
        self.assertEqual(report.groups, (points.DuplicateGroup((0, 1, 2), True),))
        self.assertEqual([c.ids for c in report.conflicts], [("A", "C")])
        mean = points.resolve_duplicates(chain, report, "mean")
        self.assertEqual(len(mean), 1)
        self.assertAlmostEqual(float(mean.xyz[0, 2]), 800.006, places=9)
        self.assertEqual(mean.xyz[0, :2].tobytes(), chain.xyz[0, :2].tobytes())

    def test_random_clouds_match_brute_force(self) -> None:
        """En 6 nubes aleatorias de 600 puntos con 200 casi duplicados (desplazados hasta
        1,2 mm, con Δz de hasta 0,03 m), los grupos y sus conflictos son los de la fuerza
        bruta, y la resolución conserva el primero de cada grupo."""
        for seed in range(6):
            with self.subTest(semilla=seed):
                rng = np.random.default_rng(seed)
                base = np.column_stack([E0 + rng.uniform(0, 3, 400), N0 + rng.uniform(0, 3, 400),
                                        800 + rng.uniform(0, 5, 400)])
                pick = rng.integers(0, 400, 200)
                near = base[pick] + np.column_stack([rng.uniform(-0.0012, 0.0012, (200, 2)),
                                                     rng.uniform(-0.03, 0.03, 200)])
                xyz = _frozen(np.concatenate([base, near])[rng.permutation(600)])
                report = points.find_duplicates(xyz)
                want = _brute_groups(xyz, 0.001)
                self.assertEqual([g.indices for g in report.groups], want)
                for group in report.groups:
                    z = xyz[list(group.indices), 2]
                    self.assertEqual(group.conflict, bool(z.max() - z.min() > 0.01))
                in_conflict = {i for g in report.groups if g.conflict for i in g.indices}
                listed = {int(i[1:]) - 1 for c in report.conflicts for i in c.ids}
                self.assertEqual(listed - in_conflict, set())
                for conflict in report.conflicts:
                    self.assertGreater(conflict.dz, 0.01)
                point_set = points.PointSet(xyz, tuple(f"#{i + 1}" for i in range(600)),
                                            ("",) * 600, tuple(range(600)))
                result = points.resolve_duplicates(point_set, report, "first")
                self.assertEqual(len(result), 600 - report.duplicates)
                firsts = sorted({i for i in range(600)} - {i for g in report.groups
                                                           for i in g.indices[1:]})
                self.assertEqual(result.xyz.tobytes(), xyz[firsts].tobytes())

    def test_package_reexports(self) -> None:
        """``gis`` reexporta la API de la tarea (plan §5.1)."""
        for name in ("DuplicatePolicy", "DuplicateReport", "DuplicateGroup",
                     "find_duplicates", "resolve_duplicates", "ConflictError"):
            with self.subTest(nombre=name):
                self.assertIn(name, gis.__all__)
                self.assertTrue(hasattr(gis, name))


if __name__ == "__main__":
    unittest.main()
