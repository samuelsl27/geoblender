# SPDX-License-Identifier: GPL-3.0-or-later
"""Tablas CSV (spec 005, T12; plan 005 §5.3.2, ``interop.csv_tables``).

- **RF-005-05** (asistente con las 20 primeras filas tal como se van a interpretar): el
  separador declarado («;», coma, tabulador o espacios), las comillas (con el separador o
  comillas dentro), CRLF o LF, las líneas en blanco, la cabecera en otra fila o sin
  cabecera y la codificación declarada (UTF-8 con y sin BOM, Windows-1252, OEM 850 e
  ISO-8859-1) dan la misma tabla de textos, sin tocar los valores, con la línea del fichero
  de cada fila; la vista previa son las 20 primeras filas y no lee más allá. Una
  codificación que no es la del fichero, un BOM con otra codificación, UTF-16, un fichero
  que no es texto o unas comillas sin cerrar → ``TableError`` con el fichero, la línea y
  qué hacer.
- **RF-005-03** (la fuente no cambia): leer, también la vista previa y las lecturas que
  fallan, deja el sha256 del fichero y el listado de su carpeta (nombres, tamaños y
  fechas) como estaban, con el fichero en solo lectura.

Los ficheros en otras codificaciones se escriben en la carpeta temporal con
``texto.encode(codificación)``: nunca se versionan.
"""

import hashlib
import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path

from tests.support.package import import_geoblender

csv_tables = import_geoblender("interop.csv_tables")
errors = import_geoblender("core.errors")

HEADER = ["Sondeo", "Desde", "Hasta", "Litología", "Observación"]
ROWS = [
    ["S-01", "0,00", "2,50", "Pizarra", "Óxidos de hierro; muestra «A»"],
    ["S-01", "2,50", "7,25", "Cuarcita", 'Señal "débil"'],
    ["S-02", "0,00", "12,00", "Pizarra", "Ángulo 45º"],
    ["S-03", "0,00", "3,10", "Arcilla", ""],
]
# Las mismas filas escritas a mano, como las guarda Excel («;», CRLF, comillas dobladas).
BASE_TEXT = (
    "Sondeo;Desde;Hasta;Litología;Observación\r\n"
    'S-01;0,00;2,50;Pizarra;"Óxidos de hierro; muestra «A»"\r\n'
    'S-01;2,50;7,25;Cuarcita;"Señal ""débil"""\r\n'
    "S-02;0,00;12,00;Pizarra;Ángulo 45º\r\n"
    "S-03;0,00;3,10;Arcilla;\r\n"
)
BASE_LINES = [2, 3, 4, 5]


def _join(fields: list[str], separator: str) -> str:
    """Una línea CSV: entre comillas (dobladas dentro) el campo que lleva el separador,
    comillas o un salto de línea."""
    shown = []
    for field in fields:
        if separator in field or '"' in field or "\n" in field:
            field = '"' + field.replace('"', '""') + '"'
        shown.append(field)
    return separator.join(shown)


def _text(rows: list[list[str]], separator: str, newline: str = "\r\n") -> str:
    return "".join(_join(row, separator) + newline for row in rows)


def _fingerprint(folder: Path) -> dict[str, tuple[int, int, str]]:
    """Nombre → (tamaño, fecha de modificación en ns, sha256) de cada fichero de la carpeta."""
    found = {}
    for entry in os.scandir(folder):
        info = entry.stat()
        digest = hashlib.sha256(Path(entry.path).read_bytes()).hexdigest()
        found[entry.name] = (info.st_size, info.st_mtime_ns, digest)
    return found


class _FolderTest(unittest.TestCase):
    """Con una carpeta temporal propia (en ``%TEMP%``), que se borra al terminar."""

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="gb-csv-"))
        self.addCleanup(shutil.rmtree, self.folder, True)

    def _write(self, data: str | bytes, name: str = "t.csv", encoding: str = "utf-8") -> Path:
        path = self.folder / name
        path.write_bytes(data.encode(encoding) if isinstance(data, str) else data)
        return path

    def _read(self, data: str | bytes, *, encoding: str = "utf-8", separator: str = ";",
              written: str = "utf-8", **options: object) -> object:
        path = self._write(data, encoding=written)
        return csv_tables.read_table(path, encoding=encoding, separator=separator, **options)

    def _rejected(self, data: str | bytes, code: str, **options: object) -> object:
        with self.assertRaises(csv_tables.TableError) as caught:
            self._read(data, **options)
        error = caught.exception
        self.assertIsInstance(error, errors.GeoblenderError)
        self.assertEqual(error.code, code)
        self.assertEqual(error.obj, "t.csv")
        return error

    def _assert_base(self, table: object) -> None:
        self.assertEqual(table.columns, HEADER)
        self.assertEqual(table.rows, ROWS)
        self.assertEqual(table.lines, BASE_LINES)


class SeparatorTest(_FolderTest):
    def test_semicolon_quotes_and_crlf_as_excel_writes_them(self) -> None:
        """RF-005-05: el CSV de Excel en español («;», CRLF, un campo con «;» entre
        comillas y comillas dobladas dentro) da las cabeceras, los textos de cada campo y
        la línea del fichero de cada fila."""
        table = self._read(BASE_TEXT)
        self._assert_base(table)
        self.assertIsInstance(table, csv_tables.Table)

    def test_each_separator_gives_the_same_table(self) -> None:
        """RF-005-05: «;», coma (con los decimales con coma entre comillas) y tabulador
        dan la misma tabla."""
        for separator in (";", ",", "\t"):
            with self.subTest(separator=repr(separator)):
                self.assertIn(separator, csv_tables.SEPARATORS)
                self._assert_base(self._read(_text([HEADER, *ROWS], separator),
                                             separator=separator))

    def test_space_separator_is_a_run_of_blanks(self) -> None:
        """RF-005-05: con «espacio», uno o varios espacios o tabuladores separan, también
        al principio y al final de la línea (XYZ disperso)."""
        text = "X Y Z\n 700005.844   4400006.579\t803.501 \n700019.403\t4400004.197  809.736\n"
        table = self._read(text, separator=" ")
        self.assertEqual(table.columns, ["X", "Y", "Z"])
        self.assertEqual(table.rows, [["700005.844", "4400006.579", "803.501"],
                                      ["700019.403", "4400004.197", "809.736"]])
        self.assertEqual(table.lines, [2, 3])

    def test_line_endings_and_blank_lines(self) -> None:
        """RF-005-05: LF o CRLF, sin fin de línea al final, con líneas en blanco o solo con
        separadores (filas vacías de Excel): la misma tabla, con la línea de cada fila."""
        lf = BASE_TEXT.replace("\r\n", "\n")
        self._assert_base(self._read(lf))
        self._assert_base(self._read(lf.rstrip("\n")))
        lines = BASE_TEXT.split("\r\n")
        spaced = "\r\n".join([lines[0], lines[1], "", ";;;;", lines[2], "  ", lines[3],
                              lines[4], ";;;;", ""])
        table = self._read(spaced)
        self.assertEqual(table.columns, HEADER)
        self.assertEqual(table.rows, ROWS)
        self.assertEqual(table.lines, [2, 5, 7, 8])

    def test_values_are_kept_as_written(self) -> None:
        """RF-005-05: los valores no se tocan (espacios, filas con menos o más campos, que
        el lector de la tabla rechaza con su fila); solo se quitan los espacios de los
        nombres de las columnas."""
        text = " Sondeo ; Desde\r\n  S-01 ; 1,5 \r\nS-02\r\nS-03;2;sobra\r\n"
        table = self._read(text)
        self.assertEqual(table.columns, ["Sondeo", "Desde"])
        self.assertEqual(table.rows, [["  S-01 ", " 1,5 "], ["S-02"], ["S-03", "2", "sobra"]])
        self.assertEqual(table.lines, [2, 3, 4])

    def test_quoted_line_break_counts_from_its_first_line(self) -> None:
        """RF-005-05: un campo entre comillas con un salto de línea es un solo valor, y la
        fila siguiente lleva su línea del fichero."""
        text = 'Sondeo;Nota\r\nS-01;"dos\r\nlíneas"\r\nS-02;una\r\n'
        table = self._read(text)
        self.assertEqual(table.rows, [["S-01", "dos\r\nlíneas"], ["S-02", "una"]])
        self.assertEqual(table.lines, [2, 4])

    def test_unclosed_quotes_name_the_first_line(self) -> None:
        """RF-005-05: unas comillas sin cerrar (o mal puestas) → ``io.csv_malformed`` con
        la línea donde empieza la fila, sin seguir leyendo."""
        error = self._rejected('Sondeo;Nota\nS-01;"sin cerrar\nS-02;b\n', "io.csv_malformed")
        self.assertEqual((error.field, error.value), ("línea", 2))
        error = self._rejected('Sondeo;Nota\nS-01;ok\nS-02;"mal"puesta\n', "io.csv_malformed")
        self.assertEqual(error.value, 3)
        self.assertIn("comillas", error.message)


class EncodingTest(_FolderTest):
    def test_utf8_with_and_without_bom(self) -> None:
        """RF-005-05: UTF-8 con BOM (el «CSV UTF-8» de Excel) y sin él dan la misma tabla;
        el BOM no pasa al nombre de la primera columna."""
        self._assert_base(self._read(BASE_TEXT))
        self._assert_base(self._read(b"\xef\xbb\xbf" + BASE_TEXT.encode("utf-8")))
        self._assert_base(self._read(BASE_TEXT, encoding="utf-8-sig", written="utf-8-sig"))

    def test_windows_1252(self) -> None:
        """RF-005-05: Windows-1252 (el CSV de Excel en español), con sus caracteres propios
        («€», «…», comillas tipográficas), da los textos de UTF-8."""
        extra = ["S-04", "0,00", "1,00", "Relleno", "Coste 12 € … “sic”"]
        text = BASE_TEXT + _join(extra, ";") + "\r\n"
        data = text.encode("cp1252")
        self.assertIn(b"\x80", data)  # «€»: solo existe en Windows-1252
        for name in ("cp1252", "Windows-1252"):
            with self.subTest(encoding=name):
                table = self._read(data, encoding=name)
                self.assertEqual(table.rows, [*ROWS, extra])
                self.assertEqual(table.columns, HEADER)

    def test_oem_850(self) -> None:
        """RF-005-05: OEM 850 (programas de MS-DOS) da los textos de UTF-8; los mismos bytes
        leídos como Windows-1252 dan otros: se usa la codificación declarada, no se
        adivina."""
        data = BASE_TEXT.encode("cp850")
        self._assert_base(self._read(data, encoding="cp850"))
        other = self._read(data, encoding="cp1252")
        self.assertNotEqual(other.rows, ROWS)
        self.assertEqual(other.rows[1][4], 'Se¤al "d‚bil"')

    def test_iso_8859_1(self) -> None:
        """RF-005-05: ISO-8859-1 (Latin-1) da los textos de UTF-8."""
        for name in ("iso8859-1", "latin-1"):
            with self.subTest(encoding=name):
                self._assert_base(self._read(BASE_TEXT, encoding=name, written="latin-1"))

    def test_declared_encodings(self) -> None:
        """RF-005-05: el asistente ofrece las cuatro codificaciones de la spec (§7)."""
        self.assertEqual(set(csv_tables.ENCODINGS), {"utf-8", "cp1252", "iso8859-1", "cp850"})
        self.assertEqual(csv_tables.ENCODINGS["cp850"], "OEM 850")

    def test_wrong_encoding_names_line_and_byte(self) -> None:
        """RF-005-05: un CSV de Windows-1252 declarado UTF-8 → ``io.csv_not_decodable`` con
        la primera línea que no es UTF-8, el byte y la sugerencia de elegir otra."""
        text = "Sondeo;Desde\r\nS-01;0\r\nS-02;Pizarra ó\r\n"
        error = self._rejected(text, "io.csv_not_decodable", written="cp1252")
        self.assertEqual((error.field, error.value), ("línea", 3))
        self.assertIn("0xF3", error.message)
        self.assertIn("UTF-8", error.message)
        self.assertIn("Windows-1252", error.message)

    def test_bom_with_another_encoding(self) -> None:
        """RF-005-05: un fichero con el BOM de UTF-8 declarado en otra codificación →
        ``io.csv_bom_mismatch``: elija UTF-8 (si no, la primera columna saldría «ï»¿…»)."""
        error = self._rejected(b"\xef\xbb\xbf" + BASE_TEXT.encode("utf-8"),
                               "io.csv_bom_mismatch", encoding="cp1252")
        self.assertEqual((error.field, error.value), ("codificación", "Windows-1252"))
        self.assertIn("UTF-8", error.message)

    def test_utf16_and_binary_files(self) -> None:
        """RF-005-05: UTF-16 («Texto Unicode» de Excel) → ``io.csv_encoding_unsupported``;
        un fichero con bytes nulos (un XLSX, un binario) → ``io.csv_not_text``."""
        for encoding in ("utf-16", "utf-16-be"):
            with self.subTest(encoding=encoding):
                data = BASE_TEXT.encode(encoding)
                if encoding == "utf-16-be":
                    data = b"\xfe\xff" + data
                self._rejected(data, "io.csv_encoding_unsupported")
        error = self._rejected(b"PK\x03\x04\x14\x00\x06\x00\x08\x00\x00\x00!\x00",
                               "io.csv_not_text", encoding="cp1252")
        self.assertEqual((error.field, error.value), ("línea", 1))
        error = self._rejected(b"Sondeo;Desde\nS-01;0\x00\n", "io.csv_not_text")
        self.assertEqual(error.value, 2)


class HeaderRowTest(_FolderTest):
    def test_header_in_another_row(self) -> None:
        """RF-005-05: con títulos y una línea en blanco encima, la cabecera en la fila que
        se declara (``header_row`` = líneas que la preceden); las filas, con su línea."""
        text = "Campaña 2026;;;;\r\nIMGA\r\n\r\n" + BASE_TEXT
        table = self._read(text, header_row=3)
        self.assertEqual(table.columns, HEADER)
        self.assertEqual(table.rows, ROWS)
        self.assertEqual(table.lines, [5, 6, 7, 8])
        self.assertEqual(self._read(BASE_TEXT, header_row=1).columns, ROWS[0])

    def test_without_header(self) -> None:
        """RF-005-05: sin cabecera (``header_row=None``), sin columnas y todas las filas,
        desde la línea 1."""
        table = self._read(BASE_TEXT, header_row=None)
        self.assertEqual(table.columns, [])
        self.assertEqual(table.rows, [HEADER, *ROWS])
        self.assertEqual(table.lines, [1, *BASE_LINES])

    def test_empty_and_header_only(self) -> None:
        """RF-005-05: un fichero vacío, uno solo con cabecera y una cabecera más allá del
        final dan tablas sin filas (el importador lo dice, RF-005-12)."""
        empty = self._read("")
        self.assertEqual((empty.columns, empty.rows, empty.lines), ([], [], []))
        only = self._read("Sondeo;Desde\r\n\r\n")
        self.assertEqual((only.columns, only.rows), (["Sondeo", "Desde"], []))
        past = self._read(BASE_TEXT, header_row=9)
        self.assertEqual((past.columns, past.rows), ([], []))


class PreviewTest(_FolderTest):
    def _rows(self, count: int) -> list[list[str]]:
        return [[f"S-{i:02d}", f"{i},5"] for i in range(1, count + 1)]

    def test_preview_is_the_first_20_rows(self) -> None:
        """RF-005-05: la vista previa del asistente son las 20 primeras filas, con su
        línea; ``max_rows`` limita cualquier lectura y 0 da solo las columnas."""
        self.assertEqual(csv_tables.PREVIEW_ROWS, 20)
        rows = self._rows(25)
        path = self._write(_text([["Sondeo", "Desde"], *rows], ";"))
        preview = csv_tables.preview_table(path, encoding="utf-8", separator=";")
        self.assertEqual(preview.columns, ["Sondeo", "Desde"])
        self.assertEqual(preview.rows, rows[:20])
        self.assertEqual(preview.lines, list(range(2, 22)))
        full = csv_tables.read_table(path, encoding="utf-8", separator=";")
        self.assertEqual(full.rows, rows)
        some = csv_tables.read_table(path, encoding="utf-8", separator=";", max_rows=5)
        self.assertEqual(some.rows, rows[:5])
        none = csv_tables.read_table(path, encoding="utf-8", separator=";", max_rows=0)
        self.assertEqual((none.columns, none.rows), (["Sondeo", "Desde"], []))

    def test_preview_does_not_read_further(self) -> None:
        """RF-005-05: la vista previa se detiene en la fila 20: un byte que no es UTF-8 en la
        línea 30 no la impide, y la lectura entera lo señala en esa línea."""
        lines = [_join(row, ";").encode() for row in [["Sondeo", "Desde"], *self._rows(40)]]
        lines[29] = b"S-29;caf\xe9"
        path = self._write(b"\n".join(lines) + b"\n")
        preview = csv_tables.preview_table(path, encoding="utf-8", separator=";")
        self.assertEqual(len(preview.rows), 20)
        with self.assertRaises(csv_tables.TableError) as caught:
            csv_tables.read_table(path, encoding="utf-8", separator=";")
        self.assertEqual((caught.exception.code, caught.exception.value),
                         ("io.csv_not_decodable", 30))


class SourceUntouchedTest(_FolderTest):
    def test_reading_leaves_the_source_and_its_folder_as_they_were(self) -> None:
        """RF-005-03: leer (entero, la vista previa y lecturas que fallan) no cambia el
        sha256 del fichero ni el listado de su carpeta (nombres, tamaños y fechas), y
        funciona con el fichero en solo lectura: nada se escribe ni se crea junto a él."""
        path = self._write(BASE_TEXT, name="bocas.csv", encoding="cp1252")
        self._write("otro", name="léeme.txt")
        os.chmod(path, stat.S_IREAD)
        self.addCleanup(os.chmod, path, stat.S_IREAD | stat.S_IWRITE)
        before = _fingerprint(self.folder)
        csv_tables.read_table(path, encoding="cp1252", separator=";")
        csv_tables.preview_table(path, encoding="cp1252", separator=";", header_row=2)
        with self.assertRaises(csv_tables.TableError):
            csv_tables.read_table(path, encoding="utf-8", separator=";")
        self.assertEqual(_fingerprint(self.folder), before)
        self.assertEqual(sorted(os.listdir(self.folder)), ["bocas.csv", "léeme.txt"])


class OptionsTest(_FolderTest):
    def test_missing_file(self) -> None:
        """RF-005-05: un fichero que no existe → ``io.csv_unreadable`` con su nombre."""
        with self.assertRaises(csv_tables.TableError) as caught:
            csv_tables.read_table(self.folder / "t.csv", encoding="utf-8", separator=";")
        self.assertEqual((caught.exception.code, caught.exception.obj),
                         ("io.csv_unreadable", "t.csv"))

    def test_invalid_options_are_program_errors(self) -> None:
        """RF-005-05: una codificación, un separador o un número de filas que el asistente
        no ofrece son un error del programa (``ValueError``), no del fichero."""
        path = self._write(BASE_TEXT)
        cases = [
            {"encoding": "utf-16"}, {"encoding": "ascii"}, {"encoding": "no-existe"},
            {"separator": "|"}, {"separator": ""}, {"separator": ";;"},
            {"header_row": -1}, {"header_row": True}, {"max_rows": -1}, {"max_rows": 2.0},
        ]
        for case in cases:
            options = {"encoding": "utf-8", "separator": ";", **case}
            with self.subTest(**{k: repr(v) for k, v in case.items()}):
                with self.assertRaises(ValueError):
                    csv_tables.read_table(path, **options)

    def test_table_rows_and_lines_match(self) -> None:
        """RF-005-05: una ``Table`` tiene una línea por fila."""
        table = csv_tables.Table(["a"], [["1"], ["2"]], [2, 3])
        self.assertEqual(table.lines, [2, 3])
        with self.assertRaises(ValueError):
            csv_tables.Table(["a"], [["1"], ["2"]], [2])


if __name__ == "__main__":
    unittest.main()
