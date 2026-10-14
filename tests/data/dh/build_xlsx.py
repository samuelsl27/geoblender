# SPDX-License-Identifier: GPL-3.0-or-later
"""Libros XLSX sintéticos de la spec 005 (T13; plan 005 §5.4 «XLSX» y §7).

Escribe libros de Excel (Office Open XML) con ``zipfile`` y texto XML hecho aquí, sin
ninguna biblioteca de hojas de cálculo, en la carpeta que se le da (nunca en el
repositorio: **ningún libro se versiona**). Los mismos datos, los mismos bytes: fecha fija
en cada entrada del ZIP y partes en un orden fijo. Desde la raíz del repositorio de código,
con el Python de Blender, para abrirlos en Excel a mano::

    & $PY -B -s -X utf8 -m tests.data.dh.build_xlsx --out <carpeta>

Libros de :func:`write_all` (:data:`BOOKS`):

- ``csv_basico.xlsx``: una hoja por CSV de ``csv_basico/`` (:data:`BASICO_SHEETS`, con el
  nombre del fichero), con cada valor con el tipo que le daría Excel en español: los números
  con coma decimal, como números; las fechas dd/mm/aaaa, como número de serie del sistema
  1900 con el formato de fecha corta (identificador 14) o «dd/mm/yyyy» (164); los demás
  (también «<0,01», «sí», «#8B6B3D»), como texto: cadenas compartidas, «Muestra» en línea y
  la descripción de las litologías con formato (varios fragmentos y una lectura fonética,
  que no es texto de la celda). Una celda vacía del CSV no se escribe.
- ``csv_basico_1904.xlsx``: lo mismo con el sistema de fechas 1904 y todos los textos en
  línea (sin tabla de cadenas compartidas), y la hoja ``fechas_1904``.
- ``tipos.xlsx``: la hoja ``tipos`` (columna «Tipo» con el nombre del caso de
  :data:`KINDS` y «Valor» con una celda de ese tipo: cadenas compartidas y en línea, con
  formato y con caracteres escapados, booleanos, números, fechas, horas, fórmulas con valor
  en caché, errores…), la hoja ``huecos`` (cabecera en la fila 3, celdas y filas que faltan,
  filas en blanco, filas sin número) y la hoja ``sin_cache`` (una fórmula sin valor
  calculado, como la deja un programa que no calcula).
- ``recalcular.xlsx``: una fórmula con un valor en caché que no vale, porque el libro pide
  recalcular al abrirlo (``fullCalcOnLoad``, como lo escriben algunas bibliotecas con un 0
  provisional), y una hoja sin fórmulas.

Las pruebas que necesitan un libro roto (XML mal formado, entidades, partes que faltan)
lo montan con :class:`Book` y :meth:`Book.raw_sheet`; esos no están en :data:`BOOKS`.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import re
import sys
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

HERE = Path(__file__).resolve().parent
BASICO = HERE / "csv_basico"
BASICO_SHEETS = (
    "bocas",
    "desviaciones",
    "litologia",
    "analisis_columnas",
    "analisis_filas",
    "litologias",
    "elementos",
)
"""Las hojas de ``csv_basico.xlsx``: cada una, el CSV ``csv_basico/<hoja>.csv``."""
BOOKS = ("csv_basico.xlsx", "csv_basico_1904.xlsx", "tipos.xlsx", "recalcular.xlsx")
"""Los libros que escribe :func:`write_all`."""

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_DOC_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"
REL_TYPE = NS_DOC_REL + "/"
CT_MAIN = "application/vnd.openxmlformats-officedocument.spreadsheetml."
XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
ZIP_TIME = (1980, 1, 1, 0, 0, 0)

# Estilos (índice en cellXfs) y su formato de número.
STYLE_GENERAL = 0
STYLE_DATE = 1  # 14: fecha corta (dd/mm/aaaa en español)
STYLE_DATE_DMY = 2  # 164: «dd/mm/yyyy»
STYLE_DATE_LONG = 3  # 165: «[$-es-ES]d "de" mmmm "de" yyyy»
STYLE_DATETIME = 4  # 22: fecha y hora
STYLE_TIME = 5  # 20: «h:mm»
STYLE_ELAPSED = 6  # 46: «[h]:mm:ss»
STYLE_PERCENT = 7  # 10: «0.00%»
STYLE_DAYS = 8  # 166: «0.00 "días"» (letras de fecha entre comillas: es un número)
STYLE_NUMBER_FORMATS = (0, 14, 164, 165, 22, 20, 46, 10, 166)
CUSTOM_FORMATS = {
    164: "dd/mm/yyyy",
    165: '[$-es-ES]d "de" mmmm "de" yyyy',
    166: '0.00 "días"',
}

EPOCH_1900 = datetime.date(1899, 12, 30)  # serie 61 = 01/03/1900 (Excel cuenta el 29/02/1900)
EPOCH_1904 = datetime.date(1904, 1, 1)
NUMBER_ES = re.compile(r"-?\d+(?:,\d+)?")
DATE_DMY = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
INLINE_COLUMNS = frozenset({"Muestra"})
RICH_COLUMNS = frozenset({"Descripción"})
PHONETIC = "ふりがな"  # lectura fonética de una cadena con formato: no es texto de la celda


def column_letters(column: int) -> str:
    """La letra de la columna ``column`` (1 = A, 27 = AA)."""
    letters = ""
    while column:
        column, rest = divmod(column - 1, 26)
        letters = chr(ord("A") + rest) + letters
    return letters


def ref(column: int, row: int) -> str:
    """La referencia de una celda: ``ref(2, 7)`` = «B7»."""
    return f"{column_letters(column)}{row}"


def excel_number(value: float) -> str:
    """El número como lo escribe Excel en ``<v>``: sin «.0» si es entero."""
    return str(int(value)) if value.is_integer() else repr(value)


def serial(day: datetime.date | datetime.datetime, *, date1904: bool = False) -> float:
    """El número de serie de ``day`` en el sistema de fechas 1900 o 1904 (días y fracción)."""
    if isinstance(day, datetime.datetime):
        moment = day
    else:
        moment = datetime.datetime(day.year, day.month, day.day)
    epoch = EPOCH_1904 if date1904 else EPOCH_1900
    base = datetime.datetime(epoch.year, epoch.month, epoch.day)
    delta = moment - base
    return delta.days + delta.seconds / 86400


def _t(text: str) -> str:
    """Un ``<t>`` con el texto escapado (con ``xml:space`` si empieza o acaba en blanco)."""
    space = ' xml:space="preserve"' if text != text.strip() else ""
    return f"<t{space}>{escape(text)}</t>"


def _rich(runs: Sequence[str], phonetic: str | None) -> str:
    """El contenido de un ``<si>`` o ``<is>`` con formato: un ``<r>`` por fragmento (el
    primero en negrita) y, si se da, una lectura fonética ``<rPh>``."""
    parts = []
    for index, run in enumerate(runs):
        bold = "<rPr><b/></rPr>" if index == 0 else ""
        parts.append(f"<r>{bold}{_t(run)}</r>")
    if phonetic is not None:
        parts.append(f'<rPh sb="0" eb="1">{_t(phonetic)}</rPh>')
    return "".join(parts)


def cell(
    at: str | None,
    *,
    t: str | None = None,
    s: int | None = None,
    v: str | None = None,
    f: str | None = None,
    inline: str | None = None,
) -> str:
    """El XML de una celda ``<c>``: referencia ``at`` (``None``: sin ``r``), tipo ``t``,
    estilo ``s``, fórmula ``f``, valor ``v`` (ya como texto de ``<v>``) e ``inline`` (el
    contenido de ``<is>``)."""
    attributes = ""
    if at is not None:
        attributes += f' r="{at}"'
    if s is not None:
        attributes += f' s="{s}"'
    if t is not None:
        attributes += f' t="{t}"'
    body = ""
    if f is not None:
        body += f"<f>{escape(f)}</f>"
    if v is not None:
        body += f"<v>{escape(v)}</v>"
    if inline is not None:
        body += f"<is>{inline}</is>"
    return f"<c{attributes}>{body}</c>" if body else f"<c{attributes}/>"


def number(at: str | None, value: str | float, *, s: int | None = None) -> str:
    """Una celda numérica (``value`` como texto de ``<v>`` o como float)."""
    text = value if isinstance(value, str) else excel_number(value)
    return cell(at, s=s, v=text)


def boolean(at: str | None, value: bool) -> str:
    return cell(at, t="b", v="1" if value else "0")


def error(at: str | None, text: str) -> str:
    return cell(at, t="e", v=text)


def inline_text(at: str | None, text: str) -> str:
    """Una cadena en línea (``t="inlineStr"``)."""
    return cell(at, t="inlineStr", inline=_t(text))


def inline_rich(at: str | None, runs: Sequence[str], phonetic: str | None = None) -> str:
    return cell(at, t="inlineStr", inline=_rich(runs, phonetic))


def row(number_: int | None, cells: Sequence[str]) -> str:
    """El XML de una fila ``<row>`` (``number_`` ``None``: sin ``r``)."""
    attribute = "" if number_ is None else f' r="{number_}"'
    return f"<row{attribute}>{''.join(cells)}</row>"


@dataclass(frozen=True, slots=True)
class _Sheet:
    name: str
    xml: bytes
    relation: str = "worksheet"
    folder: str = "worksheets"


class Book:
    """Un libro que se está escribiendo: hojas, cadenas compartidas y opciones del libro
    (``date1904``, ``full_calc_on_load``; ``shared_strings`` falso: los textos van en
    línea y el libro no tiene tabla de cadenas compartidas)."""

    def __init__(
        self,
        *,
        date1904: bool = False,
        full_calc_on_load: bool = False,
        shared_strings: bool = True,
    ) -> None:
        self.date1904 = date1904
        self.full_calc_on_load = full_calc_on_load
        self.shared_strings = shared_strings
        self._strings: list[str] = []
        self._index: dict[str, int] = {}
        self._sheets: list[_Sheet] = []

    # --- celdas de texto (compartidas o en línea según el libro) ---------------------
    def _shared(self, item: str) -> int:
        if item not in self._index:
            self._index[item] = len(self._strings)
            self._strings.append(item)
        return self._index[item]

    def text(self, at: str | None, value: str) -> str:
        """Una celda de texto: cadena compartida o, sin tabla, en línea."""
        if not self.shared_strings:
            return inline_text(at, value)
        return cell(at, t="s", v=str(self._shared(_t(value))))

    def rich(self, at: str | None, runs: Sequence[str], phonetic: str | None = None) -> str:
        """Una celda de texto con formato (fragmentos ``runs``)."""
        if not self.shared_strings:
            return inline_rich(at, runs, phonetic)
        return cell(at, t="s", v=str(self._shared(_rich(runs, phonetic))))

    def shared_raw(self, at: str | None, content: str) -> str:
        """Una cadena compartida con el contenido de ``<si>`` tal cual (p. ej. con
        caracteres escapados como los escribe Excel, ``_x000D_``)."""
        return cell(at, t="s", v=str(self._shared(content)))

    # --- hojas -------------------------------------------------------------------------
    def sheet(self, name: str, rows: Sequence[str]) -> None:
        """Añade una hoja con las filas ``rows`` (XML de :func:`row`)."""
        xml = (
            f'{XML_DECLARATION}<worksheet xmlns="{NS_MAIN}" xmlns:r="{NS_DOC_REL}">'
            f"<sheetData>{''.join(rows)}</sheetData></worksheet>"
        )
        self.raw_sheet(name, xml.encode("utf-8"))

    def raw_sheet(self, name: str, xml: bytes) -> None:
        """Añade una hoja con estos bytes como parte (también un XML roto, para pruebas)."""
        self._sheets.append(_Sheet(name, xml))

    def chart_sheet(self, name: str) -> None:
        """Añade una hoja de gráfico (no es de datos: no la lista ``list_sheets``)."""
        xml = (
            f'{XML_DECLARATION}<chartsheet xmlns="{NS_MAIN}" xmlns:r="{NS_DOC_REL}">'
            "<sheetViews><sheetView workbookViewId=\"0\"/></sheetViews></chartsheet>"
        )
        self._sheets.append(_Sheet(name, xml.encode("utf-8"), "chartsheet", "chartsheets"))

    # --- escritura ---------------------------------------------------------------------
    def parts(self) -> dict[str, bytes]:
        """Las partes del paquete, en el orden en que se escriben."""
        sheets = []
        relations = []
        overrides = [("/xl/workbook.xml", CT_MAIN + "sheet.main+xml")]
        for number_, sheet in enumerate(self._sheets, start=1):
            target = f"{sheet.folder}/sheet{number_}.xml"
            sheets.append((sheet, target, f"rId{number_}"))
            relations.append((f"rId{number_}", REL_TYPE + sheet.relation, target))
            overrides.append((f"/xl/{target}", CT_MAIN + f"{sheet.relation}+xml"))
        styles_id = f"rId{len(sheets) + 1}"
        relations.append((styles_id, REL_TYPE + "styles", "styles.xml"))
        overrides.append(("/xl/styles.xml", CT_MAIN + "styles+xml"))
        if self.shared_strings:
            relations.append((f"rId{len(sheets) + 2}", REL_TYPE + "sharedStrings",
                              "sharedStrings.xml"))
            overrides.append(("/xl/sharedStrings.xml", CT_MAIN + "sharedStrings+xml"))
        parts = {
            "[Content_Types].xml": self._content_types(overrides),
            "_rels/.rels": _relationships([("rId1", REL_TYPE + "officeDocument",
                                            "xl/workbook.xml")]),
            "xl/workbook.xml": self._workbook(sheets),
            "xl/_rels/workbook.xml.rels": _relationships(relations),
            "xl/styles.xml": _styles(),
        }
        if self.shared_strings:
            parts["xl/sharedStrings.xml"] = self._shared_strings()
        for sheet, target, _ in sheets:
            parts[f"xl/{target}"] = sheet.xml
        return parts

    def write(self, path: Path) -> str:
        """Escribe el libro en ``path`` (que no debe existir) y da su sha256."""
        return write_parts(path, self.parts())

    def _content_types(self, overrides: list[tuple[str, str]]) -> bytes:
        items = "".join(
            f"<Override PartName={quoteattr(name)} ContentType={quoteattr(kind)}/>"
            for name, kind in overrides
        )
        return (
            f'{XML_DECLARATION}<Types xmlns="{NS_TYPES}">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f"{items}</Types>"
        ).encode("utf-8")

    def _workbook(self, sheets: list[tuple[_Sheet, str, str]]) -> bytes:
        entries = "".join(
            f'<sheet name={quoteattr(sheet.name)} sheetId="{number_}" r:id="{rid}"/>'
            for number_, (sheet, _, rid) in enumerate(sheets, start=1)
        )
        properties = '<workbookPr date1904="1"/>' if self.date1904 else "<workbookPr/>"
        calc = '<calcPr calcId="124519" fullCalcOnLoad="1"/>' if self.full_calc_on_load else ""
        return (
            f'{XML_DECLARATION}<workbook xmlns="{NS_MAIN}" xmlns:r="{NS_DOC_REL}">'
            f"{properties}<bookViews><workbookView/></bookViews>"
            f"<sheets>{entries}</sheets>{calc}</workbook>"
        ).encode("utf-8")

    def _shared_strings(self) -> bytes:
        items = "".join(f"<si>{item}</si>" for item in self._strings)
        count = len(self._strings)
        return (
            f'{XML_DECLARATION}<sst xmlns="{NS_MAIN}" count="{count}" '
            f'uniqueCount="{count}">{items}</sst>'
        ).encode("utf-8")


def _relationships(items: Sequence[tuple[str, str, str]]) -> bytes:
    body = "".join(
        f"<Relationship Id={quoteattr(rid)} Type={quoteattr(kind)} Target={quoteattr(target)}/>"
        for rid, kind, target in items
    )
    return f'{XML_DECLARATION}<Relationships xmlns="{NS_PKG_REL}">{body}</Relationships>'.encode(
        "utf-8"
    )


def _styles() -> bytes:
    formats = "".join(
        f'<numFmt numFmtId="{key}" formatCode={quoteattr(code)}/>'
        for key, code in CUSTOM_FORMATS.items()
    )
    apply = ' applyNumberFormat="1"'
    xfs = "".join(
        f'<xf numFmtId="{fmt}" fontId="0" fillId="0" borderId="0" xfId="0"'
        f"{apply if fmt else ''}/>"
        for fmt in STYLE_NUMBER_FORMATS
    )
    return (
        f'{XML_DECLARATION}<styleSheet xmlns="{NS_MAIN}">'
        f'<numFmts count="{len(CUSTOM_FORMATS)}">{formats}</numFmts>'
        '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border>'
        "</borders>"
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>'
        "</cellStyleXfs>"
        f'<cellXfs count="{len(STYLE_NUMBER_FORMATS)}">{xfs}</cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/>'
        "</cellStyles></styleSheet>"
    ).encode("utf-8")


def write_parts(path: Path, parts: dict[str, bytes]) -> str:
    """Escribe un ZIP con ``parts`` (nombre → bytes, en ese orden) en ``path``, que no debe
    existir, siempre con los mismos bytes; da su sha256."""
    with open(path, "xb") as stream, zipfile.ZipFile(stream, "w") as package:
        for name, data in parts.items():
            info = zipfile.ZipInfo(name, date_time=ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0
            package.writestr(info, data)
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- csv_basico como libro -----------------------------------------------------------------
def _csv_rows(stem: str) -> list[list[str]]:
    with (BASICO / f"{stem}.csv").open(encoding="utf-8", newline="") as stream:
        return [list(fields) for fields in csv.reader(stream, delimiter=";")]


def _typed(book: Book, at: str, text: str, column: str) -> str:
    """La celda que daría Excel en español al escribir ``text`` en la columna ``column``."""
    if NUMBER_ES.fullmatch(text):
        return number(at, float(text.replace(",", ".")))
    match = DATE_DMY.fullmatch(text)
    if match:
        day = datetime.date(int(match[3]), int(match[2]), int(match[1]))
        style = STYLE_DATE if column == "Fecha inicio" else STYLE_DATE_DMY
        return number(at, serial(day, date1904=book.date1904), s=style)
    if column in INLINE_COLUMNS:
        return inline_text(at, text)
    if column in RICH_COLUMNS and " " in text:
        head, _, tail = text.partition(" ")
        return book.rich(at, [head + " ", tail], PHONETIC)
    if column in RICH_COLUMNS:
        return book.rich(at, [text], PHONETIC)
    return book.text(at, text)


def basico_book(*, date1904: bool = False) -> Book:
    """``csv_basico.xlsx`` (sistema 1900, cadenas compartidas) o, con ``date1904``,
    ``csv_basico_1904.xlsx`` (sistema 1904, textos en línea y la hoja ``fechas_1904``)."""
    book = Book(date1904=date1904, shared_strings=not date1904)
    for stem in BASICO_SHEETS:
        records = _csv_rows(stem)
        header = records[0]
        rows = [row(1, [book.text(ref(c, 1), name) for c, name in enumerate(header, 1)])]
        for number_, fields in enumerate(records[1:], start=2):
            cells = [
                _typed(book, ref(c, number_), text, header[c - 1])
                for c, text in enumerate(fields, start=1)
                if text != ""
            ]
            rows.append(row(number_, cells))
        book.sheet(stem, rows)
    if date1904:
        book.sheet("fechas_1904", [
            row(1, [book.text("A1", "Fecha")]),
            row(2, [number("A2", 0, s=STYLE_DATE)]),
            row(3, [number("A3", serial(datetime.date(2025, 3, 3), date1904=True),
                           s=STYLE_DATE)]),
            row(4, [number("A4", serial(datetime.datetime(2025, 3, 3, 12, 30),
                                        date1904=True), s=STYLE_DATETIME)]),
        ])
    return book


# --- tipos.xlsx ----------------------------------------------------------------------------
MARCH_3_2025 = serial(datetime.date(2025, 3, 3))  # 45719
KINDS: tuple[str, ...] = (
    "compartida",
    "compartida_espacios",
    "compartida_rica",
    "compartida_escapes",
    "en_linea",
    "en_linea_rica",
    "verdadero",
    "falso",
    "entero",
    "negativo",
    "decimal",
    "exponente_pequeño",
    "exponente_grande",
    "redondeo",
    "menos_cero",
    "porcentaje",
    "numero_con_texto",
    "fecha",
    "fecha_dmy",
    "fecha_larga",
    "fecha_hora",
    "hora",
    "duracion",
    "fecha_1900_02_28",
    "fecha_1900_02_29",
    "fecha_1900_03_01",
    "fecha_iso",
    "formula_numero",
    "formula_texto",
    "formula_logica",
    "formula_error",
    "error",
    "vacia_con_estilo",
)
"""Los casos de la hoja ``tipos`` (columna «Tipo»), en orden desde la fila 2."""


def _kind_cell(book: Book, kind: str, at: str) -> str:
    cells = {
        "compartida": lambda: book.text(at, "S-01"),
        "compartida_espacios": lambda: book.text(at, "  dos  espacios "),
        "compartida_rica": lambda: book.rich(at, ["Óxidos ", "de hierro"], PHONETIC),
        # Excel escribe un retorno de carro como _x000D_ y un «_x» literal como _x005F_x.
        "compartida_escapes": lambda: book.shared_raw(
            at, _t("línea_x000D_\nnueva _x005F_x0041_")),
        "en_linea": lambda: inline_text(at, "M-0101"),
        "en_linea_rica": lambda: inline_rich(at, ["Ag ", "≥ 0,5"]),
        "verdadero": lambda: boolean(at, True),
        "falso": lambda: boolean(at, False),
        "entero": lambda: number(at, "150"),
        "negativo": lambda: number(at, "-60"),
        "decimal": lambda: number(at, "0.105"),
        "exponente_pequeño": lambda: number(at, "1E-5"),
        "exponente_grande": lambda: number(at, "1.5E+21"),
        "redondeo": lambda: number(at, "0.30000000000000004"),
        "menos_cero": lambda: number(at, "-0"),
        "porcentaje": lambda: number(at, "0.105", s=STYLE_PERCENT),
        "numero_con_texto": lambda: number(at, "2.5", s=STYLE_DAYS),
        "fecha": lambda: number(at, MARCH_3_2025, s=STYLE_DATE),
        "fecha_dmy": lambda: number(at, MARCH_3_2025, s=STYLE_DATE_DMY),
        "fecha_larga": lambda: number(at, MARCH_3_2025, s=STYLE_DATE_LONG),
        "fecha_hora": lambda: number(
            at, serial(datetime.datetime(2025, 3, 3, 12, 30)), s=STYLE_DATETIME),
        "hora": lambda: number(at, 12.5 / 24, s=STYLE_TIME),
        "duracion": lambda: number(at, "1.5", s=STYLE_ELAPSED),
        "fecha_1900_02_28": lambda: number(at, "59", s=STYLE_DATE),
        "fecha_1900_02_29": lambda: number(at, "60", s=STYLE_DATE),
        "fecha_1900_03_01": lambda: number(at, "61", s=STYLE_DATE),
        "fecha_iso": lambda: cell(at, t="d", s=STYLE_DATE, v="2025-03-03"),
        "formula_numero": lambda: cell(at, f="B10*2", v="300"),
        "formula_texto": lambda: cell(at, t="str", f='B2&"x"', v="S-01x"),
        "formula_logica": lambda: cell(at, t="b", f="B10>0", v="1"),
        "formula_error": lambda: cell(at, t="e", f="NA()", v="#N/A"),
        "error": lambda: error(at, "#DIV/0!"),
        "vacia_con_estilo": lambda: cell(at, s=STYLE_DATE),
    }
    return cells[kind]()


def tipos_book() -> Book:
    """``tipos.xlsx``: las hojas ``tipos``, ``huecos`` y ``sin_cache``."""
    book = Book()
    rows = [row(1, [book.text("A1", "Tipo"), book.text("B1", "Valor")])]
    for number_, kind in enumerate(KINDS, start=2):
        rows.append(row(number_, [book.text(ref(1, number_), kind),
                                  _kind_cell(book, kind, ref(2, number_))]))
    book.sheet("tipos", rows)
    book.sheet("huecos", [
        row(1, [book.text("A1", "Campaña C-2025")]),
        # fila 2: no está
        row(3, [book.text("A3", "Sondeo"), book.text("B3", " Desde "), book.text("C3", "Hasta"),
                book.text("D3", "Litología"), cell("E3", s=STYLE_DATE)]),
        row(4, [book.text("A4", "S-01"), number("B4", 0), number("C4", 3),
                book.text("D4", "SUE")]),
        # fila 5: no está; la 6 solo tiene celdas con estilo y sin valor
        row(6, [cell("A6", s=STYLE_DATE), cell("B6", s=STYLE_DATE)]),
        row(7, [book.text("A7", "S-01"), number("C7", 45), book.text("D7", "CAL")]),
        row(8, [book.text("A8", "S-02")]),
        # fila 9: sin número de fila ni referencias de celda
        row(None, [book.text(None, "S-03"), number(None, 0), number(None, "2.5"),
                   book.text(None, "ARC")]),
        row(10, [book.text("A10", "S-03"), book.text("F10", "fuera")]),
        row(11, [book.text("A11", "   ")]),
    ])
    book.sheet("sin_cache", [
        row(1, [book.text("A1", "Sondeo"), book.text("B1", "Profundidad")]),
        row(2, [book.text("A2", "S-01"), cell("B2", f="100+50")]),
    ])
    return book


def recalcular_book() -> Book:
    """``recalcular.xlsx``: ``fullCalcOnLoad`` y una fórmula con un 0 provisional."""
    book = Book(full_calc_on_load=True)
    book.sheet("formulas", [
        row(1, [book.text("A1", "Profundidad")]),
        row(2, [cell("A2", f="100+50", v="0")]),
    ])
    book.sheet("valores", [
        row(1, [book.text("A1", "Profundidad")]),
        row(2, [number("A2", 150)]),
    ])
    return book


def write_all(out: Path) -> dict[str, str]:
    """Escribe los libros de :data:`BOOKS` en la carpeta ``out`` (que se crea si no
    existe; ninguno de los libros debe existir) y da nombre → sha256."""
    out.mkdir(parents=True, exist_ok=True)
    books = {
        "csv_basico.xlsx": basico_book(),
        "csv_basico_1904.xlsx": basico_book(date1904=True),
        "tipos.xlsx": tipos_book(),
        "recalcular.xlsx": recalcular_book(),
    }
    return {name: book.write(out / name) for name, book in books.items()}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tests.data.dh.build_xlsx",
        description="Escribe los libros XLSX sintéticos de la spec 005 en una carpeta.",
    )
    parser.add_argument("--out", type=Path, required=True,
                        help="carpeta donde escribirlos (no en el repositorio)")
    options = parser.parse_args(argv)
    try:
        hashes = write_all(options.out)
    except FileExistsError as exc:
        print(f"ya existe {exc.filename}: no se sustituye", file=sys.stderr)
        return 1
    for name, digest in hashes.items():
        print(f"{name}  {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
