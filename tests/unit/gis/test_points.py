# SPDX-License-Identifier: GPL-3.0-or-later
"""Filas de una tabla de texto → puntos y líneas de rotura (spec 006, T15; plan 006 §5.3.2,
``gis.points.points_from_rows``).

- **RF-006-12**: un CSV con «;», coma decimal y en Latin-1 (generado aquí con
  ``.encode("latin-1")``, nunca versionado), leído con ``interop.csv_tables.read_table`` de
  la 005, da los mismos puntos y líneas que su versión UTF-8, con cada coordenada igual
  bit a bit al float64 de su texto (sin alterarla); las filas con ``línea`` forman las
  líneas de rotura (duras o blandas, como declare el usuario) en el orden del fichero; las
  filas erróneas se rechazan con su número (la línea del fichero) y su motivo: Z vacía, X
  no numérica, columnas de menos, una línea de un solo punto y una línea de rotura con un
  vértice sin cota (la línea entera, RF-006-12: nunca una rotura sin cota).
- Los números se leen con el decimal declarado y nada más: ni separadores de miles, ni
  ``nan``/``inf``, ni otros dígitos; el valor es el float64 más próximo al texto.
- **RF-006-10** (de paso): las filas de entrada no cambian.
"""

import tempfile
import unittest
from pathlib import Path

import numpy as np

from tests.support.package import import_geoblender
from tests.support.repo import ROOT

gis = import_geoblender("gis")
points = import_geoblender("gis.points")
messages = import_geoblender("gis.messages")
csv_tables = import_geoblender("interop.csv_tables")

POINTS_DIR = ROOT / "tests" / "data" / "gis" / "points"
TALUDES = POINTS_DIR / "taludes.csv"
ERRORES = POINTS_DIR / "errores.csv"
IRREGULAR = ROOT / "tests" / "data" / "gis" / "xyz" / "irregular.xyz"
ROLES = {"point_id": "P", "x": "X", "y": "Y", "z": "Z", "code": "Código", "line": "Línea"}


def _expected(text: str) -> tuple[list[tuple], dict[str, list[tuple]]]:
    """Puntos y líneas de un CSV como ``taludes.csv``, leídos aquí sin el código de
    Geoblender: (línea del fichero, P, xyz, código) por punto y, por identificador de
    línea, sus vértices en el orden del fichero."""
    found: list[tuple] = []
    lines: dict[str, list[tuple]] = {}
    for number, line in enumerate(text.splitlines()[1:], start=2):
        p, x, y, z, code, line_id = line.split(";")
        xyz = tuple(float(v.replace(",", ".")) for v in (x, y, z))
        if line_id:
            lines.setdefault(line_id, []).append((number, p, xyz, code))
        else:
            found.append((number, p, xyz, code))
    return found, lines


def _table(path: Path, encoding: str = "utf-8", **options) -> object:
    return csv_tables.read_table(path, encoding=encoding, separator=";", **options)


def _convert(table, *, decimal=",", source="taludes.csv", **options):
    mapping = points.ColumnMapping.by_name(table.columns, **ROLES)
    return points.points_from_rows(
        table.columns, table.rows, mapping, decimal, source=source,
        row_numbers=table.lines, **options
    )


def _rows(*values: str) -> list[list[str]]:
    """Filas X, Y, Z de una tabla sin cabecera a partir de líneas «x y z»."""
    return [value.split(" ") for value in values]


class Latin1CsvTest(unittest.TestCase):
    """RF-006-12: el CSV con «;», coma decimal y en Latin-1."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="geoblender-006-t15-")
        cls.text = TALUDES.read_text(encoding="utf-8").replace(";TN;", ";Peñón-TN;")
        cls.path = Path(cls._tmp.name) / "taludes_latin1.csv"
        cls.path.write_bytes(cls.text.encode("latin-1"))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_points_and_lines_bit_exact(self) -> None:
        """RF-006-12: 20 puntos y 4 roturas duras (C1, P1, C2, P2, de 6 vértices) con cada
        coordenada igual bit a bit al float64 de su texto, su P, su código (con «ñ» y
        «ó» del Latin-1), la línea del fichero de cada fila y el informe de 44 filas."""
        table = _table(self.path, encoding="latin-1")
        self.assertEqual(table.columns, ["P", "X", "Y", "Z", "Código", "Línea"])
        point_set, breaklines, report = _convert(table, source=self.path.name)
        expected_points, expected_lines = _expected(self.text)
        self.assertIsInstance(point_set, points.PointSet)
        self.assertEqual(len(point_set), 20)
        self.assertEqual(point_set.xyz.dtype, np.float64)
        self.assertEqual(point_set.xyz.shape, (20, 3))
        want = np.array([xyz for _n, _p, xyz, _c in expected_points])
        self.assertEqual(point_set.xyz.tobytes(), want.tobytes())
        self.assertEqual(point_set.point_ids, tuple(p for _n, p, _x, _c in expected_points))
        self.assertEqual(point_set.codes, tuple(c for _n, _p, _x, c in expected_points))
        self.assertEqual(set(point_set.codes), {"Peñón-TN"})
        self.assertEqual(point_set.source_rows, tuple(n for n, *_ in expected_points))
        self.assertEqual([b.line_id for b in breaklines], ["C1", "P1", "C2", "P2"])
        for breakline in breaklines:
            with self.subTest(linea=breakline.line_id):
                vertices = expected_lines[breakline.line_id]
                self.assertIsInstance(breakline, points.Breakline)
                self.assertTrue(breakline.hard)
                self.assertEqual(breakline.xyz.shape, (6, 3))
                want = np.array([xyz for _n, _p, xyz, _c in vertices])
                self.assertEqual(breakline.xyz.tobytes(), want.tobytes())
                self.assertEqual(breakline.code, vertices[0][3])
                self.assertEqual(breakline.source_rows, tuple(n for n, *_ in vertices))
        self.assertIsInstance(report, gis.TopoReport)
        self.assertEqual(report.source, self.path.name)
        self.assertEqual((report.read, report.points, report.lines), (44, 20, 4))
        self.assertEqual(report.rejected, ())
        self.assertEqual(report.duplicates, 0)

    def test_same_as_utf8(self) -> None:
        """RF-006-12: el mismo levantamiento en UTF-8 (el versionado) y en Latin-1 da las
        mismas coordenadas, bit a bit."""
        utf8_points, utf8_lines, _ = _convert(_table(TALUDES))
        latin_points, latin_lines, _ = _convert(_table(self.path, encoding="latin-1"))
        self.assertEqual(utf8_points.xyz.tobytes(), latin_points.xyz.tobytes())
        for a, b in zip(utf8_lines, latin_lines, strict=True):
            self.assertEqual(a.line_id, b.line_id)
            self.assertEqual(a.xyz.tobytes(), b.xyz.tobytes())

    def test_soft_breaklines(self) -> None:
        """RF-006-12: el papel lo declara el usuario: con líneas blandas, las cuatro
        llegan como blandas."""
        _p, breaklines, _r = _convert(_table(TALUDES), hard=False)
        self.assertEqual(len(breaklines), 4)
        self.assertFalse(any(b.hard for b in breaklines))


class ErrorRowsTest(unittest.TestCase):
    """RF-006-12: las filas de ``errores.csv`` (tabla de casos de su README)."""

    def setUp(self) -> None:
        self.point_set, self.breaklines, self.report = _convert(
            _table(ERRORES), source="errores.csv"
        )

    def test_rejected_rows_with_number_and_reason(self) -> None:
        """RF-006-12: Z vacía (línea 4), X no numérica (5), columnas de menos (6), una
        línea de un solo punto (14) y la línea L3 entera por su vértice sin cota (15–17),
        cada fila con su número y su motivo; el resto se acepta."""
        codes = {r.row: r.code for r in self.report.rejected}
        self.assertEqual(
            codes,
            {
                4: "gis.value_empty",
                5: "gis.value_not_number",
                6: "gis.row_columns",
                14: "gis.line_single_point",
                15: "gis.line_rejected",
                16: "gis.breakline_no_elevation",
                17: "gis.line_rejected",
            },
        )
        self.assertEqual([r.row for r in self.report.rejected], [4, 5, 6, 14, 15, 16, 17])
        self.assertEqual(self.report.rejected_count, 7)
        reasons = {r.row: r.reason for r in self.report.rejected}
        self.assertEqual(
            reasons[5],
            "Puntos «errores.csv», fila 5, columna X («X»): «7OO030,000» no es un número.",
        )
        self.assertEqual(
            reasons[4], "Puntos «errores.csv», fila 4, columna Z («Z»): está vacía."
        )
        self.assertIn("tiene 3 columnas y se esperan 6", reasons[6])
        self.assertIn("«L2» tiene un solo punto", reasons[14])
        self.assertIn("«L3»", reasons[16])
        self.assertIn("sin cota", reasons[16])
        self.assertIn("fila 16", reasons[15])
        self.assertIn("fila 16", reasons[17])
        for rejection in self.report.rejected:
            with self.subTest(fila=rejection.row):
                self.assertEqual(rejection.reason.splitlines(), [rejection.reason])
                self.assertEqual(messages.lookup(rejection.code).severity, "error")

    def test_accepted_points_and_line(self) -> None:
        """RF-006-12: los puntos válidos (P 1, 2, 6, 7, 8 y 9; los duplicados son de la
        T16) y la línea L1 de tres vértices, en el orden del fichero."""
        self.assertEqual(self.point_set.point_ids, ("1", "2", "6", "7", "8", "9"))
        self.assertEqual(self.point_set.source_rows, (2, 3, 7, 8, 9, 10))
        self.assertEqual(self.point_set.xyz[3].tolist(), [700000.0004, 4400010.0003, 810.004])
        self.assertEqual([b.line_id for b in self.breaklines], ["L1"])
        self.assertEqual(self.breaklines[0].source_rows, (11, 12, 13))
        self.assertEqual(self.breaklines[0].code, "PIE")
        self.assertEqual(self.breaklines[0].xyz[:, 2].tolist(), [812.0, 812.5, 813.0])
        self.assertEqual((self.report.read, self.report.points, self.report.lines),
                         (16, 6, 1))


class NumbersTest(unittest.TestCase):
    """RF-006-12: el decimal declarado y nada más; el float64 más próximo al texto."""

    def _read(self, decimal: str, *rows: list[str]):
        mapping = points.ColumnMapping(x=0, y=1, z=2)
        return points.points_from_rows([], rows, mapping, decimal, source="n.txt")

    def test_accepted_texts(self) -> None:
        """Signos, exponentes, «.5», «5.» y blancos alrededor; la coma decimal se lee como
        el punto del mismo texto."""
        texts = ["700000,0004", "+4400000,25", " -0,5 ", "1e3", ",5", "5,", "1,5E-3"]
        rows = [[t, t, t] for t in texts]
        point_set, _lines, report = self._read(",", *rows)
        self.assertEqual(report.rejected, ())
        want = [float(t.strip().replace(",", ".")) for t in texts]
        self.assertEqual(point_set.xyz[:, 0].tolist(), want)
        point_set, _lines, report = self._read(".", ["700000.0004", "1E2", ".25"])
        self.assertEqual(point_set.xyz.tolist(), [[700000.0004, 100.0, 0.25]])

    def test_rejected_texts(self) -> None:
        """Ni el otro decimal, ni miles, ni ``nan``, ``inf``, ``_``, otros dígitos o un
        exponente que no cabe en float64."""
        comma = ["12,3,4", "1.5", "700.000,5", "nan", "inf", "1_000", "١٢", "1e999", "--1",
                 "1 000", "0x10", "e5", ","]
        point_set, _lines, report = self._read(",", *[["1", "2", t] for t in comma])
        self.assertEqual(len(point_set), 0)
        self.assertEqual(len(report.rejected), len(comma))
        self.assertEqual({r.code for r in report.rejected}, {"gis.value_not_number"})
        dot = ["12,5", "1.5.1", "Infinity", "-nan"]
        point_set, _lines, report = self._read(".", *[["1", "2", t] for t in dot])
        self.assertEqual(len(point_set), 0)
        self.assertEqual(len(report.rejected), len(dot))

    def test_first_bad_column_is_reported(self) -> None:
        """La fila rechazada cita la primera columna que falla, en el orden X, Y, Z, con
        el texto tal como está (recortado)."""
        _p, _l, report = self._read(".", ["1", "", "a"], ["b", "1", "1"])
        self.assertEqual(
            [r.reason for r in report.rejected],
            [
                "Puntos «n.txt», fila 1, columna Y («columna 2»): está vacía.",
                "Puntos «n.txt», fila 2, columna X («columna 1»): «b» no es un número.",
            ],
        )


class StructureTest(unittest.TestCase):
    """RF-006-12: columnas por nombre o por posición, sin cabecera, líneas y filas."""

    def test_xyz_without_header(self) -> None:
        """El XYZ disperso (tabulador, sin cabecera): 150 puntos, sin líneas, con la línea
        del fichero de cada uno y sin identificador ni código."""
        table = csv_tables.read_table(IRREGULAR, encoding="utf-8", separator="\t",
                                      header_row=None)
        mapping = points.ColumnMapping(x=0, y=1, z=2)
        point_set, breaklines, report = points.points_from_rows(
            table.columns, table.rows, mapping, ".", source=IRREGULAR.name,
            row_numbers=table.lines
        )
        self.assertEqual((len(point_set), breaklines, report.rejected), (150, [], ()))
        self.assertEqual(point_set.source_rows, tuple(range(1, 151)))
        self.assertEqual(set(point_set.point_ids), {""})
        self.assertEqual(set(point_set.codes), {""})
        first = IRREGULAR.read_text(encoding="utf-8").splitlines()[0].split("\t")
        self.assertEqual(point_set.xyz[0].tolist(), [float(v) for v in first])

    def test_column_count(self) -> None:
        """Con cabecera, una fila con menos columnas se rechaza, y con más, solo si las de
        más tienen algo (Excel deja separadores al final); sin cabecera, basta con las
        columnas que se usan."""
        columns = ["X", "Y", "Z", "Nota"]
        mapping = points.ColumnMapping(x=0, y=1, z=2)
        rows = [["1", "2", "3"], ["1", "2", "3", "a", " ", ""], ["1", "2", "3", "a", "b"]]
        point_set, _l, report = points.points_from_rows(columns, rows, mapping, ".")
        self.assertEqual(point_set.source_rows, (2,))
        self.assertEqual([(r.row, r.code) for r in report.rejected],
                         [(1, "gis.row_columns"), (3, "gis.row_columns")])
        self.assertIn("tiene 5 columnas y se esperan 4", report.rejected[1].reason)
        point_set, _l, report = points.points_from_rows([], rows[:1] + [["1", "2"]],
                                                         mapping, ".")
        self.assertEqual(len(point_set), 1)
        self.assertIn("tiene 2 columnas y se esperan 3", report.rejected[0].reason)

    def test_lines_join_in_file_order(self) -> None:
        """Las filas de una línea forman la línea en el orden del fichero aunque no estén
        seguidas; un vértice con X no válida rechaza la línea entera, citando la primera
        fila que no vale."""
        columns = ["X", "Y", "Z", "L"]
        rows = [
            ["0", "0", "1", "A"], ["5", "5", "5", ""], ["1", "0", "2", "B"],
            ["0", "1", "3", "A"], ["1", "1", "4", "B"], ["x", "2", "5", "B"],
            ["2", "y", "6", "B"],
        ]
        mapping = points.ColumnMapping(x=0, y=1, z=2, line=3)
        point_set, breaklines, report = points.points_from_rows(columns, rows, mapping, ".")
        self.assertEqual(point_set.xyz.tolist(), [[5.0, 5.0, 5.0]])
        self.assertEqual([b.line_id for b in breaklines], ["A"])
        self.assertEqual(breaklines[0].xyz.tolist(), [[0.0, 0.0, 1.0], [0.0, 1.0, 3.0]])
        self.assertEqual(breaklines[0].source_rows, (1, 4))
        self.assertEqual([(r.row, r.code) for r in report.rejected],
                         [(3, "gis.line_rejected"), (5, "gis.line_rejected"),
                          (6, "gis.value_not_number"), (7, "gis.value_not_number")])
        self.assertIn("su fila 6 no es válida", report.rejected[0].reason)
        self.assertIn("su fila 6 no es válida", report.rejected[1].reason)

    def test_rows_not_modified(self) -> None:
        """RF-006-10: las filas y la cabecera de entrada no cambian."""
        columns = ("X", "Y", "Z", "L")
        rows = (("0", "0", "1", "A"), (" 1 ", "0", "2", "A"), ("2", "", "3", ""))
        before = repr((columns, rows))
        mapping = points.ColumnMapping(x=0, y=1, z=2, line=3)
        points.points_from_rows(columns, rows, mapping, ".")
        self.assertEqual(repr((columns, rows)), before)

    def test_mapping(self) -> None:
        """Una columna por papel, distintas y dentro de la cabecera; por nombre, el
        nombre tiene que estar. Un error del programa (el asistente solo ofrece las
        válidas): ``ValueError`` o ``TypeError``."""
        mapping = points.ColumnMapping.by_name(["P", "X", "Y", "Z"], x="X", y="Y", z="Z",
                                               point_id="P")
        self.assertEqual((mapping.x, mapping.y, mapping.z, mapping.point_id), (1, 2, 3, 0))
        self.assertIsNone(mapping.line)
        with self.assertRaises(ValueError):
            points.ColumnMapping.by_name(["X", "Y"], x="X", y="Y", z="Z")
        with self.assertRaises(ValueError):
            points.ColumnMapping(x=0, y=0, z=1)
        with self.assertRaises(ValueError):
            points.ColumnMapping(x=-1, y=0, z=1)
        with self.assertRaises(TypeError):
            points.ColumnMapping(x=True, y=0, z=1)
        mapping = points.ColumnMapping(x=0, y=1, z=4)
        with self.assertRaises(ValueError):
            points.points_from_rows(["X", "Y", "Z"], [], mapping, ".")
        mapping = points.ColumnMapping(x=0, y=1, z=2)
        with self.assertRaises(ValueError):
            points.points_from_rows([], [], mapping, ";")
        with self.assertRaises(ValueError):
            points.points_from_rows([], [["1", "2", "3"]], mapping, ".", row_numbers=[1, 2])

    def test_empty_table(self) -> None:
        """Sin filas: ningún punto ni línea, un informe de 0 filas."""
        point_set, breaklines, report = points.points_from_rows(
            [], [], points.ColumnMapping(x=0, y=1, z=2), "."
        )
        self.assertEqual((point_set.xyz.shape, breaklines, report.read), ((0, 3), [], 0))

    def test_reexported(self) -> None:
        for name in ("ColumnMapping", "PointSet", "Breakline", "points_from_rows"):
            with self.subTest(name=name):
                self.assertIn(name, gis.__all__)
                self.assertIs(getattr(gis, name), getattr(points, name))


if __name__ == "__main__":
    unittest.main()
