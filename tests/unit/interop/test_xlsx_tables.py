# SPDX-License-Identifier: GPL-3.0-or-later
"""Libros XLSX (spec 005, T13; plan 005 §5.3.2 y §5.4 «XLSX», ``interop.xlsx_tables``).

- **RF-005-06** (la hoja que elija el usuario da los mismos sondeos y valores que el CSV
  equivalente): ``csv_basico.xlsx`` (sistema de fechas 1900, cadenas compartidas, en línea y
  con formato) y ``csv_basico_1904.xlsx`` (sistema 1904, solo en línea), de
  ``tests/data/dh/build_xlsx.py``, dan en cada hoja las columnas, la fila de cada registro y
  los textos de su CSV de ``csv_basico/``: los números, con el mismo float64 bit a bit; las
  fechas, con el formato declarado; lo demás, el mismo texto. Cada tipo de celda
  (cadenas compartidas y en línea, con formato, fonética y escapes; booleanos; números con
  exponente o −0; fechas 1900 y 1904 por el formato de número, con la fecha que Excel cuenta
  y no existe; horas y duraciones; fórmulas con valor en caché; errores como «#N/A») da su
  texto; una fórmula sin valor en caché, o con un valor que el libro manda recalcular, se
  rechaza con su celda y qué hacer. Celdas y filas que faltan, filas en blanco y la cabecera
  en otra fila, como en el CSV; la vista previa son las 20 primeras filas y no lee más allá.
- **RF-005-03** (la fuente no cambia): leer, también la vista previa y las lecturas que
  fallan, deja el sha256 de cada libro y el listado de su carpeta (nombres, tamaños y
  fechas) como estaban, con los libros en solo lectura.
- Riesgo R11 del plan (XLSX malicioso): entidades externas y la expansión de entidades
  (expat ≥ 2.4.1) rechazadas como XML mal formado; una parte que descomprimida pasa del
  máximo, rechazada sin leerla.

Los libros se escriben en la carpeta temporal con ``build_xlsx``: nunca se versionan.
"""

import hashlib
import os
import pyexpat
import shutil
import stat
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import numpy as np

from tests.data.dh import build_xlsx
from tests.support.package import import_geoblender

xlsx_tables = import_geoblender("interop.xlsx_tables")
csv_tables = import_geoblender("interop.csv_tables")
values = import_geoblender("drillholes.values")
errors = import_geoblender("core.errors")

SPANISH = {"decimal_mark": ",", "date_format": "%d/%m/%Y"}
STRICT_MAIN = "http://purl.oclc.org/ooxml/spreadsheetml/main"
STRICT_DOC_REL = "http://purl.oclc.org/ooxml/officeDocument/relationships"

# El texto de cada caso de la hoja «tipos» con las opciones por defecto (punto decimal,
# fechas ISO 8601) y lo que cambia con coma decimal y fechas dd/mm/aaaa.
TIPOS: dict[str, str] = {
    "compartida": "S-01",
    "compartida_espacios": "  dos  espacios ",
    "compartida_rica": "Óxidos de hierro",
    "compartida_escapes": "línea\r\nnueva _x0041_",
    "en_linea": "M-0101",
    "en_linea_rica": "Ag ≥ 0,5",
    "verdadero": "TRUE",
    "falso": "FALSE",
    "entero": "150",
    "negativo": "-60",
    "decimal": "0.105",
    "exponente_pequeño": "0.00001",
    "exponente_grande": "1500000000000000000000",
    "redondeo": "0.30000000000000004",
    "menos_cero": "0",
    "porcentaje": "0.105",
    "numero_con_texto": "2.5",
    "fecha": "2025-03-03",
    "fecha_dmy": "2025-03-03",
    "fecha_larga": "2025-03-03",
    "fecha_hora": "2025-03-03 12:30:00",
    "hora": "12:30:00",
    "duracion": "36:00:00",
    "fecha_1900_02_28": "1900-02-28",
    "fecha_1900_02_29": "60",
    "fecha_1900_03_01": "1900-03-01",
    "fecha_iso": "2025-03-03",
    "formula_numero": "300",
    "formula_texto": "S-01x",
    "formula_logica": "TRUE",
    "formula_error": "#N/A",
    "error": "#DIV/0!",
    "vacia_con_estilo": "",
}
TIPOS_SPANISH = {
    **TIPOS,
    "decimal": "0,105",
    "exponente_pequeño": "0,00001",
    "redondeo": "0,30000000000000004",
    "porcentaje": "0,105",
    "numero_con_texto": "2,5",
    "fecha": "03/03/2025",
    "fecha_dmy": "03/03/2025",
    "fecha_larga": "03/03/2025",
    "fecha_hora": "03/03/2025",
    "fecha_1900_02_28": "28/02/1900",
    "fecha_1900_03_01": "01/03/1900",
    "fecha_iso": "03/03/2025",
}
HUECOS_COLUMNS = ["Sondeo", "Desde", "Hasta", "Litología"]
HUECOS_ROWS = [
    ["S-01", "0", "3", "SUE"],
    ["S-01", "", "45", "CAL"],
    ["S-02", "", "", ""],
    ["S-03", "0", "2.5", "ARC"],
    ["S-03", "", "", "", "", "fuera"],
]
HUECOS_LINES = [4, 7, 8, 9, 10]


def _fingerprint(folder: Path) -> dict[str, tuple[int, int, str]]:
    """Nombre → (tamaño, fecha de modificación en ns, sha256) de cada fichero de la carpeta."""
    found = {}
    for entry in os.scandir(folder):
        info = entry.stat()
        digest = hashlib.sha256(Path(entry.path).read_bytes()).hexdigest()
        found[entry.name] = (info.st_size, info.st_mtime_ns, digest)
    return found


def _parsed(texts: list[str], mark: str) -> object:
    return values.parse_column(texts, values.ValueRules(decimal_mark=mark))


class _BooksTest(unittest.TestCase):
    """Con los libros de ``build_xlsx.write_all`` en una carpeta temporal propia."""

    folder: Path

    @classmethod
    def setUpClass(cls) -> None:
        cls.folder = Path(tempfile.mkdtemp(prefix="gb-xlsx-"))
        cls.addClassCleanup(shutil.rmtree, cls.folder, True)
        cls.hashes = build_xlsx.write_all(cls.folder)

    def _book(self, book: build_xlsx.Book, name: str = "t.xlsx") -> Path:
        """Escribe ``book`` (un libro hecho en la prueba) en la carpeta y da su ruta."""
        path = self.folder / name
        path.unlink(missing_ok=True)
        book.write(path)
        return path

    def _zip(self, parts: dict[str, bytes], name: str = "z.xlsx") -> Path:
        path = self.folder / name
        path.unlink(missing_ok=True)
        build_xlsx.write_parts(path, parts)
        return path

    def _rejected(self, path: Path, code: str, sheet: str | None = "datos",
                  **options: object) -> object:
        with self.assertRaises(xlsx_tables.TableError) as caught:
            if sheet is None:
                xlsx_tables.list_sheets(path)
            else:
                xlsx_tables.read_sheet(path, sheet, **options)
        error = caught.exception
        self.assertIsInstance(error, errors.GeoblenderError)
        self.assertIs(xlsx_tables.TableError, csv_tables.TableError)
        self.assertEqual(error.code, code)
        self.assertIn(path.name, error.obj)
        return error

    def _one_cell(self, xml_cell: str) -> Path:
        """Un libro con la hoja «datos»: cabecera «Valor» y la celda ``xml_cell`` en B2."""
        book = build_xlsx.Book()
        book.sheet("datos", [
            build_xlsx.row(1, [book.text("A1", "Sondeo"), book.text("B1", "Valor")]),
            build_xlsx.row(2, [book.text("A2", "S-01"), xml_cell]),
        ])
        return self._book(book)


class EquivalenceTest(_BooksTest):
    def _assert_like_csv(self, book: Path, stem: str) -> None:
        """La hoja ``stem`` de ``book`` frente a ``csv_basico/<stem>.csv``: mismas columnas
        y filas; en cada columna, los mismos números (float64 bit a bit, mismas marcas «<» y
        «>») y, donde no hay número, el mismo texto."""
        expected = csv_tables.read_table(build_xlsx.BASICO / f"{stem}.csv", encoding="utf-8",
                                         separator=";")
        table = xlsx_tables.read_sheet(book, stem, **SPANISH)
        self.assertIsInstance(table, csv_tables.Table)
        self.assertEqual(table.columns, expected.columns)
        self.assertEqual(table.lines, expected.lines)
        self.assertEqual([len(r) for r in table.rows], [len(r) for r in expected.rows])
        numbers = 0
        for index, column in enumerate(expected.columns):
            with self.subTest(sheet=stem, column=column):
                theirs = [r[index] for r in expected.rows]
                ours = [r[index] for r in table.rows]
                parsed_theirs, parsed_ours = _parsed(theirs, ","), _parsed(ours, ",")
                np.testing.assert_array_equal(parsed_ours.values.view(np.int64),
                                              parsed_theirs.values.view(np.int64))
                np.testing.assert_array_equal(parsed_ours.flags, parsed_theirs.flags)
                np.testing.assert_array_equal(parsed_ours.rejected_rows,
                                              parsed_theirs.rejected_rows)
                for row_index in parsed_theirs.rejected_rows:
                    self.assertEqual(ours[row_index], theirs[row_index])
                numbers += int(np.count_nonzero(~np.isnan(parsed_theirs.values)))
        self.assertGreater(numbers, 0, stem)

    def test_each_sheet_gives_its_csv(self) -> None:
        """RF-005-06, RF-005-02: cada hoja de ``csv_basico.xlsx`` (fechas 1900 con los
        formatos 14 y «dd/mm/yyyy», cadenas compartidas, en línea y con formato) leída con
        coma decimal y fechas dd/mm/aaaa da su CSV: columnas, fila de cada registro,
        números iguales en float64 y los demás textos («<0,01», «sí», colores, fechas)."""
        book = self.folder / "csv_basico.xlsx"
        self.assertEqual(xlsx_tables.list_sheets(book), list(build_xlsx.BASICO_SHEETS))
        for stem in build_xlsx.BASICO_SHEETS:
            self._assert_like_csv(book, stem)

    def test_1904_workbook_with_inline_strings_gives_the_same(self) -> None:
        """RF-005-06: con el sistema de fechas 1904 y todos los textos en línea (sin tabla
        de cadenas compartidas), las mismas tablas; la serie 0 es el 1 de enero de 1904."""
        book = self.folder / "csv_basico_1904.xlsx"
        with zipfile.ZipFile(book) as package:
            self.assertNotIn("xl/sharedStrings.xml", package.namelist())
        self.assertEqual(xlsx_tables.list_sheets(book),
                         [*build_xlsx.BASICO_SHEETS, "fechas_1904"])
        for stem in build_xlsx.BASICO_SHEETS:
            self._assert_like_csv(book, stem)
        table = xlsx_tables.read_sheet(book, "fechas_1904")
        self.assertEqual(table.rows, [["1904-01-01"], ["2025-03-03"], ["2025-03-03 12:30:00"]])

    def test_default_options_point_and_iso_dates(self) -> None:
        """RF-005-06: por defecto, los números con punto decimal (su decimal más corto, sin
        ceros de más) y las fechas en ISO 8601; los textos, tal como están."""
        table = xlsx_tables.read_sheet(self.folder / "csv_basico.xlsx", "bocas")
        self.assertEqual(table.rows[0], ["S-01", "700010.5", "4400040.5", "798.117", "150",
                                         "", "", "DD", "C-2025", "2025-03-03", "2025-03-07",
                                         "no"])
        self.assertEqual(table.rows[4][5:7], ["300", "-75"])
        assays = xlsx_tables.read_sheet(self.folder / "csv_basico.xlsx", "analisis_filas",
                                        decimal_mark=",")
        self.assertEqual(assays.rows[0], ["S-01", "58,5", "60,5", "M-0101", "Au", "<0,01", "g/t"])


class CellKindsTest(_BooksTest):
    def _tipos(self, **options: object) -> dict[str, str]:
        table = xlsx_tables.read_sheet(self.folder / "tipos.xlsx", "tipos", **options)
        self.assertEqual(table.columns, ["Tipo", "Valor"])
        self.assertEqual([r[0] for r in table.rows], list(build_xlsx.KINDS))
        self.assertEqual(table.lines, list(range(2, len(build_xlsx.KINDS) + 2)))
        return {r[0]: r[1] for r in table.rows}

    def test_each_cell_kind_default(self) -> None:
        """RF-005-06: cadenas compartidas (con blancos, con formato sin su fonética, con
        ``_x000D_`` y ``_x005F_``) y en línea; booleanos «TRUE»/«FALSE»; números por su
        decimal más corto sin exponente (−0 → «0»; el formato de porcentaje o con texto no
        cambia el valor); fechas por el formato de número (14, «dd/mm/yyyy», con
        configuración regional y literales), fecha y hora, hora, duración; el 29/02/1900
        que cuenta Excel, como número; fórmulas por su valor en caché; errores tal cual."""
        self.assertEqual(self._tipos(), TIPOS)

    def test_each_cell_kind_spanish(self) -> None:
        """RF-005-06: con coma decimal y fechas «%d/%m/%Y», los números y las fechas salen
        así (como los escribiría el CSV de Excel en español); los textos no cambian."""
        self.assertEqual(self._tipos(**SPANISH), TIPOS_SPANISH)

    def test_error_values(self) -> None:
        """RF-005-09 (a través de RF-005-06): los textos de error de Excel están en
        ``ERROR_VALUES``, para que el importador los rechace en cualquier columna."""
        for text in ("#N/A", "#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#NUM!", "#NULL!"):
            self.assertIn(text, xlsx_tables.ERROR_VALUES)
        self.assertEqual((xlsx_tables.TRUE_TEXT, xlsx_tables.FALSE_TEXT), ("TRUE", "FALSE"))

    def test_gaps_header_row_and_blank_rows(self) -> None:
        """RF-005-05, RF-005-06: cabecera en la fila 3 (``header_row=2``) sin blancos a los
        lados ni la columna vacía final; celdas que faltan, vacías; filas que faltan, en
        blanco, con solo estilo o solo espacios, saltadas; una fila sin número sigue a la
        anterior; cada fila tiene al menos las columnas de la cabecera y su número de fila."""
        book = self.folder / "tipos.xlsx"
        table = xlsx_tables.read_sheet(book, "huecos", header_row=2)
        self.assertEqual(table.columns, HUECOS_COLUMNS)
        self.assertEqual(table.rows, HUECOS_ROWS)
        self.assertEqual(table.lines, HUECOS_LINES)
        first = xlsx_tables.read_sheet(book, "huecos", header_row=2, max_rows=2)
        self.assertEqual((first.rows, first.lines), (HUECOS_ROWS[:2], HUECOS_LINES[:2]))
        none = xlsx_tables.read_sheet(book, "huecos", header_row=2, max_rows=0)
        self.assertEqual((none.columns, none.rows, none.lines), (HUECOS_COLUMNS, [], []))
        bare = xlsx_tables.read_sheet(book, "huecos", header_row=None)
        self.assertEqual(bare.columns, [])
        self.assertEqual(bare.lines, [1, 3, *HUECOS_LINES])
        self.assertEqual(bare.rows[1], ["Sondeo", " Desde ", "Hasta", "Litología", "", ""])
        self.assertEqual({len(r) for r in bare.rows}, {6})
        empty_header = xlsx_tables.read_sheet(book, "huecos", header_row=1)
        self.assertEqual((empty_header.columns, empty_header.lines), ([], [3, *HUECOS_LINES]))
        beyond = xlsx_tables.read_sheet(book, "huecos", header_row=20)
        self.assertEqual((beyond.columns, beyond.rows, beyond.lines), ([], [], []))

    def test_preview_reads_20_rows_and_no_further(self) -> None:
        """RF-005-05: la vista previa son las 20 primeras filas de 28 y no llega a la
        cadena compartida que no existe de la fila 30 (la lectura entera, sí, con su celda)."""
        book = build_xlsx.Book()
        rows = [build_xlsx.row(1, [book.text("A1", "Sondeo"), book.text("B1", "Desde")])]
        for number in range(2, 30):
            rows.append(build_xlsx.row(number, [book.text(f"A{number}", f"S-{number:02d}"),
                                                build_xlsx.number(f"B{number}", number)]))
        rows.append(build_xlsx.row(30, [build_xlsx.cell("A30", t="s", v="9999")]))
        book.sheet("datos", rows)
        path = self._book(book)
        preview = xlsx_tables.preview_sheet(path, "datos")
        self.assertEqual(xlsx_tables.PREVIEW_ROWS, 20)
        self.assertEqual(len(preview.rows), 20)
        self.assertEqual(preview.lines, list(range(2, 22)))
        self.assertEqual(preview.rows[-1], ["S-21", "21"])
        error = self._rejected(path, "io.xlsx_malformed")
        self.assertEqual((error.field, error.value), ("celda", "A30"))

    def test_strict_namespaces(self) -> None:
        """RF-005-06: un libro en OOXML estricto (otros espacios de nombres) se lee igual."""
        parts = build_xlsx.tipos_book().parts()
        strict = {
            name: data.replace(build_xlsx.NS_MAIN.encode(), STRICT_MAIN.encode())
            .replace(build_xlsx.NS_DOC_REL.encode(), STRICT_DOC_REL.encode())
            for name, data in parts.items()
        }
        path = self._zip(strict)
        self.assertEqual(xlsx_tables.list_sheets(path), ["tipos", "huecos", "sin_cache"])
        table = xlsx_tables.read_sheet(path, "huecos", header_row=2)
        self.assertEqual((table.rows, table.lines), (HUECOS_ROWS, HUECOS_LINES))


class FormulaTest(_BooksTest):
    def test_formula_without_cached_value(self) -> None:
        """RF-005-06: una fórmula sin valor calculado (libro escrito por un programa que no
        calcula) → ``io.xlsx_formula_without_value`` con su hoja y su celda, y qué hacer
        (abrir y guardar en Excel)."""
        path = self.folder / "tipos.xlsx"
        error = self._rejected(path, "io.xlsx_formula_without_value", "sin_cache")
        self.assertEqual((error.field, error.value), ("celda", "B2"))
        self.assertIn("sin_cache", error.obj)
        self.assertIn("Excel", error.reason)

    def test_full_calc_on_load_makes_cached_values_untrusted(self) -> None:
        """RF-005-06, RF-005-02: si el libro manda recalcular al abrirlo
        (``fullCalcOnLoad``), el valor en caché de una fórmula (un 0 provisional) no se
        toma; una hoja del mismo libro sin fórmulas se lee."""
        path = self.folder / "recalcular.xlsx"
        error = self._rejected(path, "io.xlsx_formula_without_value", "formulas")
        self.assertEqual(error.value, "A2")
        self.assertEqual(xlsx_tables.read_sheet(path, "valores").rows, [["150"]])


class ErrorsTest(_BooksTest):
    def test_sheet_missing_and_chart_sheets(self) -> None:
        """RF-005-06: una hoja que no está → ``io.xlsx_sheet_missing`` con las que hay; las
        hojas de gráfico no son de datos: no se listan ni se leen."""
        error = self._rejected(self.folder / "csv_basico.xlsx", "io.xlsx_sheet_missing",
                               "Hoja1")
        self.assertEqual((error.field, error.value), ("hoja", "Hoja1"))
        self.assertIn("bocas", error.reason)
        book = build_xlsx.Book()
        book.sheet("datos", [build_xlsx.row(1, [book.text("A1", "Sondeo")])])
        book.chart_sheet("Gráfico1")
        path = self._book(book)
        self.assertEqual(xlsx_tables.list_sheets(path), ["datos"])
        self._rejected(path, "io.xlsx_sheet_missing", "Gráfico1")

    def test_not_a_workbook(self) -> None:
        """RF-005-06: un fichero que no existe → ``io.xlsx_unreadable``; un texto, un libro
        antiguo o protegido con contraseña (OLE2), un libro binario (.xlsb) o un ZIP sin
        libro → ``io.xlsx_not_xlsx`` con qué hacer."""
        self._rejected(self.folder / "no_existe.xlsx", "io.xlsx_unreadable", None)
        text = self.folder / "texto.xlsx"
        text.write_text("Sondeo;Desde\nS-01;0\n", encoding="utf-8")
        self._rejected(text, "io.xlsx_not_xlsx", None)
        ole = self.folder / "antiguo.xlsx"
        ole.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(504))
        self.assertIn("(.xls)", self._rejected(ole, "io.xlsx_not_xlsx", None).reason)
        rels = build_xlsx._relationships([("rId1", build_xlsx.REL_TYPE + "officeDocument",
                                           "xl/workbook.bin")])
        binary = self._zip({"_rels/.rels": rels, "xl/workbook.bin": b"\x83\x01"}, "b.xlsx")
        self.assertIn(".xlsb", self._rejected(binary, "io.xlsx_not_xlsx", None).reason)
        other = self._zip({"content.xml": b"<office:document-content/>"}, "o.xlsx")
        self._rejected(other, "io.xlsx_not_xlsx", "datos")

    def test_malformed_cells(self) -> None:
        """RF-005-06: un número que no lo es, un booleano que no es 0 ni 1, una cadena
        compartida que no existe, un tipo de celda desconocido o una fecha ISO mal escrita →
        ``io.xlsx_malformed`` con su celda."""
        cells = {
            "número": build_xlsx.cell("B2", v="1,5"),
            "infinito": build_xlsx.cell("B2", v="1E999"),
            "booleano": build_xlsx.cell("B2", t="b", v="2"),
            "compartida": build_xlsx.cell("B2", t="s", v="99"),
            "tipo": build_xlsx.cell("B2", t="x", v="1"),
            "fecha": build_xlsx.cell("B2", t="d", v="03/03/2025"),
        }
        for about, xml_cell in cells.items():
            with self.subTest(about):
                error = self._rejected(self._one_cell(xml_cell), "io.xlsx_malformed")
                self.assertEqual((error.field, error.value), ("celda", "B2"))

    def test_malformed_xml_and_order(self) -> None:
        """RF-005-06: una hoja con el XML cortado, filas que no van en orden o una celda
        fuera de la hoja → ``io.xlsx_malformed``."""
        head = (f'<worksheet xmlns="{build_xlsx.NS_MAIN}"><sheetData>'
                '<row r="1"><c r="A1" t="inlineStr"><is><t>Sondeo</t></is></c></row>')
        sheets = {
            "cortado": head + '<row r="2"><c r="A2"><v>1',
            "orden": head + '<row r="1"><c r="A1"><v>2</v></c></row></sheetData></worksheet>',
            "fuera": head + '<row r="2"><c r="XFE2"><v>2</v></c></row></sheetData></worksheet>',
        }
        for about, xml in sheets.items():
            with self.subTest(about):
                book = build_xlsx.Book()
                book.raw_sheet("datos", xml.encode("utf-8"))
                self._rejected(self._book(book), "io.xlsx_malformed")

    def test_entities_are_not_expanded(self) -> None:
        """R11 del plan: una entidad externa (que apunta a un fichero) y la expansión de
        entidades anidadas («billion laughs») → ``io.xlsx_malformed`` en poco tiempo, sin
        leer el fichero (expat ≥ 2.4.1)."""
        self.assertGreaterEqual(pyexpat.version_info, (2, 4, 1))
        canary = self.folder / "canario.txt"
        canary.write_text("SECRETO", encoding="utf-8")
        entities = "".join(
            f'<!ENTITY e{i} "{f"&e{i - 1};" * 10 if i else "ja"}">' for i in range(10)
        )
        sheets = {
            "externa": (f'<!DOCTYPE w [<!ENTITY x SYSTEM "{canary.as_uri()}">]>'
                        f'<worksheet xmlns="{build_xlsx.NS_MAIN}"><sheetData><row r="1">'
                        '<c r="A1" t="inlineStr"><is><t>&x;</t></is></c></row></sheetData>'
                        "</worksheet>"),
            "expansión": (f"<!DOCTYPE w [{entities}]>"
                          f'<worksheet xmlns="{build_xlsx.NS_MAIN}"><sheetData><row r="1">'
                          '<c r="A1" t="inlineStr"><is><t>&e9;</t></is></c></row></sheetData>'
                          "</worksheet>"),
        }
        for about, xml in sheets.items():
            with self.subTest(about):
                book = build_xlsx.Book()
                book.raw_sheet("datos", xml.encode("utf-8"))
                path = self._book(book)
                start = time.perf_counter()
                self._rejected(path, "io.xlsx_malformed")
                self.assertLess(time.perf_counter() - start, 2.0)

    def test_part_too_large(self) -> None:
        """R11 del plan: una parte que descomprimida pasa de ``MAX_PART_BYTES`` →
        ``io.xlsx_too_large``, sin leerla."""
        path = self.folder / "tipos.xlsx"
        with mock.patch.object(xlsx_tables, "MAX_PART_BYTES", 200):
            error = self._rejected(path, "io.xlsx_too_large", "tipos")
        self.assertEqual(error.field, "parte")

    def test_invalid_options(self) -> None:
        """Opciones que el asistente no ofrece → ``ValueError`` (o ``TypeError`` si la hoja no
        es un texto): error del programa, no del usuario."""
        path = self.folder / "tipos.xlsx"
        bad = (
            {"decimal_mark": ";"},
            {"date_format": "dd/mm/aaaa"},
            {"header_row": -1},
            {"max_rows": True},
        )
        for options in bad:
            with self.subTest(**{k: repr(v) for k, v in options.items()}):
                with self.assertRaises(ValueError):
                    xlsx_tables.read_sheet(path, "tipos", **options)
        with self.assertRaises(TypeError):
            xlsx_tables.read_sheet(path, 3)


class SourceIntactTest(unittest.TestCase):
    def test_reading_leaves_the_books_as_they_were(self) -> None:
        """RF-005-03: con los libros en solo lectura, listar, leer cada hoja, la vista
        previa y las lecturas que fallan dejan el sha256, el tamaño y la fecha de cada libro
        y el listado de la carpeta como estaban (nada se crea junto a ellos)."""
        folder = Path(tempfile.mkdtemp(prefix="gb-xlsx-"))
        self.addCleanup(shutil.rmtree, folder, True)
        hashes = build_xlsx.write_all(folder)
        for name in hashes:
            os.chmod(folder / name, stat.S_IREAD)
            self.addCleanup(os.chmod, folder / name, stat.S_IREAD | stat.S_IWRITE)
        before = _fingerprint(folder)
        self.assertEqual({name: entry[2] for name, entry in before.items()}, hashes)
        for name in hashes:
            path = folder / name
            for sheet in xlsx_tables.list_sheets(path):
                for read in (xlsx_tables.preview_sheet, xlsx_tables.read_sheet):
                    try:
                        read(path, sheet, **SPANISH)
                    except xlsx_tables.TableError as exc:  # sin_cache y formulas
                        self.assertEqual(exc.code, "io.xlsx_formula_without_value")
            with self.assertRaises(xlsx_tables.TableError):
                xlsx_tables.read_sheet(path, "no hay tal hoja")
        self.assertEqual(_fingerprint(folder), before)


class BuildXlsxTest(unittest.TestCase):
    def test_same_bytes_twice(self) -> None:
        """RF-005-06 (datos de T13): ``build_xlsx.write_all`` escribe dos veces los mismos
        bytes, y no sustituye un libro que ya existe."""
        with tempfile.TemporaryDirectory(prefix="gb-xlsx-") as tmp:
            first = build_xlsx.write_all(Path(tmp) / "a")
            second = build_xlsx.write_all(Path(tmp) / "b")
            self.assertEqual(list(first), list(build_xlsx.BOOKS))
            self.assertEqual(first, second)
            with self.assertRaises(FileExistsError):
                build_xlsx.write_all(Path(tmp) / "a")


if __name__ == "__main__":
    unittest.main()
