# SPDX-License-Identifier: GPL-3.0-or-later
"""Libros XLSX (spec 005, T13; plan 005 §5.3.2 y §5.4 «XLSX»; RF-005-03, RF-005-06), con
biblioteca estándar: ``zipfile`` y ``xml.etree`` (plan 005 §6, D4: sin openpyxl).

:func:`list_sheets` da las hojas de datos de un libro, en su orden, y :func:`read_sheet` lee
una como la :class:`~.csv_tables.Table` de textos que daría su CSV: los nombres de las
columnas, las filas y, en ``lines``, el **número de fila de la hoja** de cada una (para que
el importador diga «fila 7», la misma que ve el usuario en Excel). :func:`preview_sheet`
son las :data:`PREVIEW_ROWS` (20) primeras filas (RF-005-05); no lee más allá. Así, un
libro y su CSV pasan por el mismo importador (RF-005-06).

Cada celda da un texto:

- **Textos** (cadenas compartidas, en línea o resultado de una fórmula): tal como están,
  con los fragmentos de un texto con formato unidos, sin su lectura fonética, y con los
  caracteres que Excel escribe escapados (``_x000D_``) devueltos a su carácter.
- **Números**: el decimal más corto que da el mismo float64 (RF-005-02), sin exponente ni
  separador de miles, con el separador decimal ``decimal_mark`` (punto por defecto; con
  coma, como el CSV de Excel en español: así los números de las celdas y los escritos como
  texto, como «<0,01», se leen con el mismo decimal declarado). El formato de número no
  cambia el valor (un porcentaje es el número guardado), salvo el de fecha.
- **Fechas**: un número con formato de fecha u hora (identificadores 14–22 y 45–47, o un
  formato propio con d, m, a/y, h o s fuera de comillas) en el sistema de fechas del libro
  (1900, con el 29/02/1900 que cuenta Excel y no existe, o 1904): con el ``date_format``
  declarado (``strftime``, el de las fechas escritas como texto) o, sin él, en ISO 8601
  («aaaa-mm-dd», o «aaaa-mm-dd hh:mm:ss» si el formato tiene hora); una hora o una duración
  («[h]:mm:ss»), «hh:mm:ss». Una fecha imposible queda como número.
- **Booleanos**: :data:`TRUE_TEXT` o :data:`FALSE_TEXT`. **Errores** (``#N/A``…): su
  texto, uno de :data:`ERROR_VALUES`, como en el CSV que guarda Excel; el importador los
  rechaza (RF-005-09).
- **Fórmulas**: su valor en caché. Sin él, o si el libro manda recalcular al abrirlo
  (``fullCalcOnLoad``: el valor guardado puede ser un 0 provisional), la hoja no se lee
  (``io.xlsx_formula_without_value``): hay que abrir el libro en Excel y guardarlo.

Las filas, como en el CSV: las celdas que faltan son textos vacíos; se saltan las filas que
no están o que no tienen ningún valor (o solo espacios); cada fila llega hasta su última
celda con valor y, con cabecera, tiene al menos tantos campos como columnas (sin cabecera,
todas tantos como la más larga). ``header_row`` es el número de filas de la hoja que
preceden a la cabecera (0: la fila 1); ``None``, sin cabecera. A los nombres de las
columnas se les quitan los espacios de los lados y se quitan las columnas vacías del final.

**Fuente intacta** (RF-005-03): el libro se abre solo para leer y nada se escribe ni se
crea junto a él. **Libros malintencionados** (riesgo R11 del plan): ``xml.etree`` no
resuelve entidades externas y expat (≥ 2.4.1) limita la expansión de entidades: los dos son
XML mal formado; una parte que descomprimida pasa de :data:`MAX_PART_BYTES` (o, la de los
metadatos, de :data:`MAX_META_BYTES`) se rechaza sin leerla; la hoja y las cadenas
compartidas se leen por partes (``iterparse``), sin cargar la hoja entera.

Errores: :class:`TableError` (la de :mod:`.csv_tables`; códigos ``io.xlsx_*``) para el
usuario, con el libro, la hoja, la celda o la parte y qué hacer; ``ValueError`` o
``TypeError`` si las opciones no son de las que ofrece el asistente (error del programa).
"""

from __future__ import annotations

import datetime
import posixpath
import re
import zipfile
import zlib
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import IO
from xml.etree import ElementTree

from .csv_tables import PREVIEW_ROWS, Table, TableError

__all__ = [
    "DECIMAL_MARKS",
    "ERROR_VALUES",
    "FALSE_TEXT",
    "ISO_DATE",
    "ISO_DATETIME",
    "MAX_META_BYTES",
    "MAX_PART_BYTES",
    "PREVIEW_ROWS",
    "TIME_FORMAT",
    "TRUE_TEXT",
    "Table",
    "TableError",
    "list_sheets",
    "preview_sheet",
    "read_sheet",
]

TRUE_TEXT = "TRUE"
"""El texto de un booleano verdadero (el del lenguaje de fórmulas del fichero)."""
FALSE_TEXT = "FALSE"
"""El texto de un booleano falso."""
ERROR_VALUES = frozenset({
    "#NULL!", "#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#NUM!", "#N/A", "#GETTING_DATA",
    "#SPILL!", "#CALC!", "#FIELD!", "#BLOCKED!", "#CONNECT!", "#BUSY!", "#UNKNOWN!",
    "#PYTHON!",
})
"""Los valores de error de Excel: el texto de una celda de error (y el que escribe Excel en
el CSV). No son datos: el importador los rechaza en cualquier columna."""
DECIMAL_MARKS = (".", ",")
"""Separadores decimales de los números (el de las fuentes de sondeos, spec 005)."""
ISO_DATE = "%Y-%m-%d"
"""Las fechas sin ``date_format``: ISO 8601."""
ISO_DATETIME = "%Y-%m-%d %H:%M:%S"
"""Las fechas con hora sin ``date_format``."""
TIME_FORMAT = "%H:%M:%S"
"""Las horas (y, con las horas que hagan falta, las duraciones)."""
MAX_PART_BYTES = 1 << 30
"""Tamaño máximo descomprimido de una hoja o de la tabla de cadenas compartidas (1 GiB;
una hoja de un millón de filas de unas 20 columnas ocupa unos 800 MB)."""
MAX_META_BYTES = 64 << 20
"""Tamaño máximo descomprimido de las partes de metadatos (relaciones, libro, estilos)."""

_MAX_COLUMN = 16384  # XFD
_MAX_ROW = 1 << 20
_SECONDS_PER_DAY = 86400
_FIELD_PATH = "ruta"
_FIELD_PART = "parte"
_FIELD_SHEET = "hoja"
_FIELD_CELL = "celda"
_OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_SAVE_AS_XLSX = "ábralo en Excel y guárdelo como «Libro de Excel (.xlsx)»"
_REL_ATTRIBUTE_NAMESPACES = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "http://purl.oclc.org/ooxml/officeDocument/relationships",
)
_DEFAULT_WORKBOOK = "xl/workbook.xml"
_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_CELL_REF = re.compile(r"([A-Za-z]{1,3})(\d+)")
_ESCAPE = re.compile(r"_x([0-9A-Fa-f]{4})_")

# Clases de formato de número que son fechas u horas.
_DATE = "date"
_DATETIME = "datetime"
_TIME = "time"
_ELAPSED = "elapsed"
_BUILTIN_KINDS = {
    14: _DATE, 15: _DATE, 16: _DATE, 17: _DATE,
    18: _TIME, 19: _TIME, 20: _TIME, 21: _TIME,
    22: _DATETIME,
    45: _TIME, 46: _ELAPSED, 47: _TIME,
}
_LITERALS = re.compile(r'"[^"]*"|\\.|[_*].')
_ELAPSED_TOKEN = re.compile(r"\[(?:h+|m+|s+)\]", re.IGNORECASE)
_BRACKETS = re.compile(r"\[[^\]]*\]")
_AM_PM = re.compile(r"am/pm|a/p", re.IGNORECASE)


def list_sheets(path: Path | str) -> list[str]:
    """Los nombres de las hojas de datos del libro ``path``, en su orden (sin las de
    gráficos ni las de macros). :class:`TableError` si no es un libro XLSX que se pueda
    leer. El libro solo se lee (RF-005-03)."""
    path = Path(path)
    with _opened(path) as package:
        return list(_workbook(package, path.name).sheets)


def read_sheet(
    path: Path | str,
    sheet: str,
    *,
    header_row: int | None = 0,
    max_rows: int | None = None,
    decimal_mark: str = ".",
    date_format: str | None = None,
) -> Table:
    """La tabla de la hoja ``sheet`` del libro ``path`` (RF-005-06). ``header_row``: las
    filas de la hoja que preceden a la cabecera, o ``None`` sin cabecera; ``max_rows``: como
    mucho esas filas (``None``, todas), sin leer más allá; ``decimal_mark``: el separador
    decimal de los números («.» o «,»); ``date_format``: el formato ``strftime`` de las
    fechas (``None``: ISO 8601). ``ValueError`` o ``TypeError`` si una opción no es válida;
    :class:`TableError` si el libro o la hoja no se pueden leer. El libro solo se lee
    (RF-005-03)."""
    if not isinstance(sheet, str):
        raise TypeError(f"la hoja es su nombre (un texto), no {sheet!r}")
    _check_count("header_row", header_row)
    _check_count("max_rows", max_rows)
    if decimal_mark not in DECIMAL_MARKS:
        raise ValueError(f"el separador decimal es «.» o «,», no {decimal_mark!r}")
    _check_date_format(date_format)
    path = Path(path)
    with _opened(path) as package:
        book = _workbook(package, path.name)
        part = book.sheets.get(sheet)
        if part is None:
            shown = ", ".join(f"«{name}»" for name in book.sheets) or "ninguna"
            raise TableError(
                "io.xlsx_sheet_missing",
                f"el libro no tiene esa hoja de datos (tiene {shown}): elija una de ellas",
                obj=path.name,
                field=_FIELD_SHEET,
                value=sheet,
            )
        where = f"{path.name} (hoja {sheet})"
        kinds = _styles(package, book.styles, path.name)
        with ExitStack() as stack:
            # Sin la tabla (o declarada y sin la parte), una celda que remite a ella falla.
            strings = book.shared_strings
            shared = _SharedStrings(
                None if strings is None or not _has(package, strings)
                else stack.enter_context(_part(package, strings, path.name)),
                strings, path.name,
            )
            stream = stack.enter_context(_part(package, part, path.name))
            reader = _SheetReader(
                where=where,
                part=part,
                shared=shared,
                kinds=kinds,
                date1904=book.date1904,
                recalculate=book.full_calc_on_load,
                decimal_mark=decimal_mark,
                date_format=date_format,
            )
            with _parsing(where, part):
                return _table(reader.rows(stream), header_row, max_rows)


def preview_sheet(
    path: Path | str,
    sheet: str,
    *,
    header_row: int | None = 0,
    decimal_mark: str = ".",
    date_format: str | None = None,
) -> Table:
    """Las :data:`PREVIEW_ROWS` primeras filas de la hoja tal como se van a interpretar (el
    asistente, RF-005-05); como :func:`read_sheet`."""
    return read_sheet(
        path, sheet, header_row=header_row, max_rows=PREVIEW_ROWS,
        decimal_mark=decimal_mark, date_format=date_format,
    )


# --- El paquete ZIP y sus partes --------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class _Workbook:
    """Lo que hace falta del libro: hojas de datos (nombre → parte, en orden), cadenas
    compartidas y estilos (sus partes, si las hay), sistema de fechas y recálculo."""

    sheets: dict[str, str]
    shared_strings: str | None
    styles: str | None
    date1904: bool
    full_calc_on_load: bool


@contextmanager
def _opened(path: Path) -> Iterator[zipfile.ZipFile]:
    """El libro abierto solo para leer; errores de apertura → :class:`TableError`."""
    try:
        package = zipfile.ZipFile(path, "r")
    except OSError as exc:
        raise TableError(
            "io.xlsx_unreadable",
            f"no se puede leer el fichero ({exc.strerror or exc}): compruebe que existe y "
            "que tiene permiso de lectura",
            obj=path.name,
            field=_FIELD_PATH,
            value=str(path),
            context={"error": repr(exc)},
        ) from exc
    except (zipfile.BadZipFile, EOFError, ValueError) as exc:
        raise _not_xlsx(path, _not_zip_reason(path)) from exc
    with package:
        yield package


def _not_zip_reason(path: Path) -> str:
    try:
        with path.open("rb") as stream:
            head = stream.read(len(_OLE2))
    except OSError:
        head = b""
    if head == _OLE2:
        return ("es un libro de Excel antiguo (.xls) o protegido con contraseña: quite la "
                f"contraseña, {_SAVE_AS_XLSX}")
    return f"no es un libro XLSX (un fichero ZIP de Office Open XML): {_SAVE_AS_XLSX}"


def _not_xlsx(path: Path | str, reason: str) -> TableError:
    name = path.name if isinstance(path, Path) else path
    return TableError("io.xlsx_not_xlsx", reason, obj=name, field=_FIELD_PATH, value=name)


@contextmanager
def _part(package: zipfile.ZipFile, name: str, book: str,
          limit: int | None = None) -> Iterator[IO[bytes]]:
    """La parte ``name`` abierta para leer, si no pasa del máximo descomprimida (el tamaño
    que declara el ZIP: no se lee más allá)."""
    limit = MAX_PART_BYTES if limit is None else limit
    try:
        info = package.getinfo(name)
    except KeyError:
        raise TableError(
            "io.xlsx_malformed",
            f"falta la parte {name} del libro: el libro está dañado; {_SAVE_AS_XLSX}",
            obj=book,
            field=_FIELD_PART,
            value=name,
        ) from None
    if info.file_size > limit:
        raise TableError(
            "io.xlsx_too_large",
            f"la parte ocupa {info.file_size} bytes descomprimida, más que el máximo "
            f"({limit}): divida el libro o guarde la hoja como CSV",
            obj=book,
            field=_FIELD_PART,
            value=name,
        )
    try:
        stream = package.open(info)
    except (NotImplementedError, RuntimeError, zipfile.BadZipFile) as exc:
        raise TableError(
            "io.xlsx_malformed",
            f"no se puede descomprimir la parte (¿protegida o con una compresión no "
            f"admitida?): {_SAVE_AS_XLSX}",
            obj=book,
            field=_FIELD_PART,
            value=name,
            context={"error": repr(exc)},
        ) from exc
    with stream:
        yield stream


@contextmanager
def _parsing(obj: str, part: str) -> Iterator[None]:
    """Un XML mal formado (también entidades) o una parte dañada → :class:`TableError`."""
    try:
        yield
    except (ElementTree.ParseError, zipfile.BadZipFile, zlib.error, EOFError) as exc:
        raise TableError(
            "io.xlsx_malformed",
            f"la parte no es XML válido o está dañada ({exc}): el libro está dañado o no lo "
            f"escribió Excel; {_SAVE_AS_XLSX}",
            obj=obj,
            field=_FIELD_PART,
            value=part,
            context={"error": repr(exc)},
        ) from None


def _xml(package: zipfile.ZipFile, name: str, book: str) -> ElementTree.Element:
    """Una parte pequeña (metadatos) entera."""
    with _part(package, name, book, MAX_META_BYTES) as stream, _parsing(book, name):
        return ElementTree.fromstring(stream.read())


def _local(tag: str) -> str:
    return tag.rpartition("}")[2]


def _has(package: zipfile.ZipFile, name: str) -> bool:
    try:
        package.getinfo(name)
    except KeyError:
        return False
    return True


def _relationships(
    package: zipfile.ZipFile, source: str, book: str
) -> list[tuple[str, str, str]]:
    """(id, tipo, parte de destino) de las relaciones internas de la parte ``source``
    («» = el paquete)."""
    folder, _, name = source.rpartition("/")
    rels = posixpath.join(folder, "_rels", f"{name}.rels")
    if not _has(package, rels):
        return []
    found = []
    for item in _xml(package, rels, book):
        if _local(item.tag) != "Relationship" or item.get("TargetMode") == "External":
            continue
        target = item.get("Target", "")
        if target.startswith("/"):
            target = target[1:]
        else:
            target = posixpath.normpath(posixpath.join(folder, target))
        found.append((item.get("Id", ""), item.get("Type", ""), target))
    return found


def _workbook(package: zipfile.ZipFile, book: str) -> _Workbook:
    main = next((target for _, kind, target in _relationships(package, "", book)
                 if kind.endswith("/officeDocument")), None)
    if main is None and _has(package, _DEFAULT_WORKBOOK):
        main = _DEFAULT_WORKBOOK
    if main is not None and main.endswith(".bin"):
        raise _not_xlsx(book, f"es un libro binario de Excel (.xlsb), que no se admite: "
                              f"{_SAVE_AS_XLSX}")
    if main is None or not _has(package, main):
        raise _not_xlsx(book, f"no es un libro de Excel (no tiene libro de hojas de cálculo): "
                              f"{_SAVE_AS_XLSX}")
    root = _xml(package, main, book)
    relations = {rid: (kind, target) for rid, kind, target in _relationships(package, main,
                                                                              book)}
    sheets: dict[str, str] = {}
    date1904 = full_calc = False
    for element in root:
        local = _local(element.tag)
        if local == "workbookPr":
            date1904 = _true(element.get("date1904"))
        elif local == "calcPr":
            full_calc = _true(element.get("fullCalcOnLoad"))
        elif local == "sheets":
            for entry in element:
                rid = next((entry.get(f"{{{ns}}}id") for ns in _REL_ATTRIBUTE_NAMESPACES
                            if entry.get(f"{{{ns}}}id") is not None), None)
                kind, target = relations.get(rid, ("", ""))
                name = entry.get("name")
                if name is not None and kind.endswith("/worksheet"):
                    sheets[name] = target
    shared = next((t for k, t in relations.values() if k.endswith("/sharedStrings")), None)
    styles = next((t for k, t in relations.values() if k.endswith("/styles")), None)
    return _Workbook(sheets, shared, styles, date1904, full_calc)


def _true(value: str | None) -> bool:
    return value is not None and value.strip().lower() in ("1", "true")


# --- Estilos: qué formatos de número son fechas -------------------------------------------------
def _styles(package: zipfile.ZipFile, part: str | None, book: str) -> list[str | None]:
    """La clase de fecha (o ``None``) del formato de número de cada estilo de celda
    (``cellXfs``), por su índice (el atributo ``s`` de la celda)."""
    if part is None:
        return []
    root = _xml(package, part, book)
    codes: dict[int, str] = {}
    kinds: list[str | None] = []
    for element in root:
        local = _local(element.tag)
        if local == "numFmts":
            for item in element:
                key = _int(item.get("numFmtId"))
                if key is not None:
                    codes[key] = item.get("formatCode", "")
        elif local == "cellXfs":
            for item in element:
                key = _int(item.get("numFmtId")) or 0
                kinds.append(_format_kind(codes[key]) if key in codes
                             else _BUILTIN_KINDS.get(key))
    return kinds


def _format_kind(code: str) -> str | None:
    """La clase de fecha de un formato de número propio: con d, a/y (fecha), m (mes, o
    minutos junto a h o s), h o s (hora) o AM/PM fuera de comillas, escapes y corchetes;
    «[h]», «[m]» o «[s]», duración; si no, ``None`` (un número)."""
    plain = _LITERALS.sub("", code)
    elapsed = _ELAPSED_TOKEN.search(plain) is not None
    plain = _BRACKETS.sub("", plain)
    plain = _AM_PM.sub("h", plain).lower().replace("general", "")
    has_date = any(letter in plain for letter in "dya")
    has_time = elapsed or any(letter in plain for letter in "hs")
    if "m" in plain and not has_date and not has_time:
        has_date = True  # «mmm», «mmmm»: el mes
    if elapsed and not has_date:
        return _ELAPSED
    if has_date:
        return _DATETIME if has_time else _DATE
    return _TIME if has_time else None


def _int(text: str | None) -> int | None:
    try:
        return int(text) if text is not None else None
    except ValueError:
        return None


# --- Cadenas compartidas, leídas solo hasta donde hace falta ------------------------------------
class _SharedStrings:
    """La tabla de cadenas compartidas, leída por partes hasta el índice que se pide (la
    vista previa no lee las del resto del libro)."""

    def __init__(self, stream: IO[bytes] | None, part: str | None, book: str) -> None:
        self._items: list[str] = []
        self._events = None if stream is None else ElementTree.iterparse(
            stream, events=("start", "end"))
        self._part = part
        self._book = book
        self._root: ElementTree.Element | None = None
        self._tags: tuple[str, str, str] = ("", "", "")

    def get(self, index: int) -> str | None:
        """La cadena ``index`` (desde 0) o ``None`` si la tabla no la tiene."""
        if index >= len(self._items) and self._events is not None:
            with _parsing(self._book, self._part or ""):
                self._read_until(index)
        return self._items[index] if 0 <= index < len(self._items) else None

    def _read_until(self, index: int) -> None:
        assert self._events is not None
        for event, element in self._events:
            if event == "start":
                if self._root is None:
                    self._root = element
                    self._tags = _tags(element.tag, "si", "t", "r")
                continue
            if element.tag == self._tags[0]:
                self._items.append(_text_of(element, self._tags[1], self._tags[2]))
                assert self._root is not None
                self._root.clear()  # las ya leídas no se quedan en memoria
                if len(self._items) > index:
                    return
        self._events = None


def _tags(root_tag: str, *names: str) -> tuple[str, ...]:
    """Las etiquetas ``names`` en el espacio de nombres de ``root_tag`` (transicional o
    estricto)."""
    namespace = root_tag[: root_tag.index("}") + 1] if root_tag.startswith("{") else ""
    return tuple(namespace + name for name in names)


def _text_of(element: ElementTree.Element, t_tag: str, r_tag: str) -> str:
    """El texto de un ``<si>`` o un ``<is>``: su ``<t>`` o los ``<t>`` de sus fragmentos
    ``<r>`` (sin la lectura fonética ``<rPh>``), con los escapes devueltos."""
    parts = []
    for child in element:
        if child.tag == t_tag:
            parts.append(child.text or "")
        elif child.tag == r_tag:
            parts.extend(sub.text or "" for sub in child if sub.tag == t_tag)
    return _unescape("".join(parts))


def _unescape(text: str) -> str:
    """``_xHHHH_`` → su carácter, como escribe Excel los de control (``_x000D_``) y un
    «_x» literal (``_x005F_``); las mitades de un par sustituto quedan como están."""
    if "_x" not in text:
        return text

    def replace(match: re.Match[str]) -> str:
        code = int(match[1], 16)
        return match[0] if 0xD800 <= code <= 0xDFFF else chr(code)

    return _ESCAPE.sub(replace, text)


# --- La hoja -----------------------------------------------------------------------------------
@dataclass(slots=True)
class _SheetReader:
    """Lee las filas de una hoja con sus opciones."""

    where: str
    part: str
    shared: _SharedStrings
    kinds: list[str | None]
    date1904: bool
    recalculate: bool
    decimal_mark: str
    date_format: str | None

    def rows(self, stream: IO[bytes]) -> Iterator[tuple[int, list[str]]]:
        """(número de fila de la hoja, textos de la columna A a la última con valor) de
        cada fila que está en la hoja, en orden."""
        events = ElementTree.iterparse(stream, events=("start", "end"))
        row_tag = sheet_data = ""
        data: ElementTree.Element | None = None
        tags: tuple[str, ...] = ()
        last = 0
        for event, element in events:
            if event == "start":
                if not row_tag:
                    tags = _tags(element.tag, "c", "v", "f", "is", "t", "r")
                    row_tag, sheet_data = _tags(element.tag, "row", "sheetData")
                elif element.tag == sheet_data:
                    data = element
                continue
            if element.tag != row_tag:
                continue
            number = _row_number(element.get("r"), last, self.where)
            last = number
            fields = self._fields(element, number, tags)
            if data is not None:
                data.clear()  # las filas ya leídas no se quedan en memoria
            yield number, fields

    def _fields(self, row: ElementTree.Element, number: int,
                tags: tuple[str, ...]) -> list[str]:
        c_tag, v_tag, f_tag, is_tag, t_tag, r_tag = tags
        fields: list[str] = []
        column = 0
        for cell in row:
            if cell.tag != c_tag:
                continue
            at = cell.get("r")
            column = column + 1 if at is None else _column(at, column, number, self.where)
            value: str | None = None
            formula = False
            inline: ElementTree.Element | None = None
            for part in cell:
                if part.tag == v_tag:
                    value = part.text or ""
                elif part.tag == f_tag:
                    formula = True
                elif part.tag == is_tag:
                    inline = part
            if formula and (value is None or self.recalculate):
                raise self._formula_error(at or _ref(column, number))
            kind = cell.get("t", "n")
            if kind == "inlineStr":
                text = "" if inline is None else _text_of(inline, t_tag, r_tag)
            else:
                text = self._text(kind, value, cell.get("s"), at or _ref(column, number))
            if text:
                if len(fields) < column - 1:
                    fields.extend([""] * (column - 1 - len(fields)))
                fields.append(text)
        return fields

    def _text(self, kind: str, value: str | None, style: str | None, at: str) -> str:
        if not value:
            return ""
        if kind == "n":
            number = _number(value)
            if number is None:
                raise self._cell_error(at, value, "no es un número")
            date_kind = self._kind(style)
            if date_kind is not None:
                shown = _date_text(number, date_kind, self.date1904, self.date_format)
                if shown is not None:
                    return shown
            return _number_text(number, self.decimal_mark)
        if kind == "s":
            index = _int(value.strip())
            shown = None if index is None else self.shared.get(index)
            if shown is None:
                raise self._cell_error(at, value, "remite a una cadena compartida que no está")
            return shown
        if kind == "str":
            return _unescape(value)
        if kind == "b":
            flag = value.strip().lower()
            if flag in ("1", "true"):
                return TRUE_TEXT
            if flag in ("0", "false"):
                return FALSE_TEXT
            raise self._cell_error(at, value, "no es un valor booleano (0 o 1)")
        if kind == "e":
            return value
        if kind == "d":
            try:
                moment = datetime.datetime.fromisoformat(value.strip())
            except ValueError:
                raise self._cell_error(at, value, "no es una fecha ISO 8601") from None
            timed = "T" in value or ":" in value
            return moment.strftime(self.date_format or (ISO_DATETIME if timed else ISO_DATE))
        raise self._cell_error(at, value, f"tiene un tipo de celda desconocido («{kind}»)")

    def _kind(self, style: str | None) -> str | None:
        index = _int(style)
        return self.kinds[index] if index is not None and 0 <= index < len(self.kinds) else None

    def _cell_error(self, at: str, value: str, reason: str) -> TableError:
        return TableError(
            "io.xlsx_malformed",
            f"la celda {reason} (valor guardado «{value[:40]}»): el libro está dañado o no "
            f"lo escribió Excel; {_SAVE_AS_XLSX}",
            obj=self.where,
            field=_FIELD_CELL,
            value=at,
            context={"part": self.part, "stored": value[:200]},
        )

    def _formula_error(self, at: str) -> TableError:
        why = ("el libro pide recalcular las fórmulas al abrirlo y el valor guardado no vale"
               if self.recalculate else "la fórmula no tiene su valor calculado guardado")
        return TableError(
            "io.xlsx_formula_without_value",
            f"{why} (el libro lo escribió un programa que no calcula): abra el libro en "
            "Excel, guárdelo y vuelva a importarlo",
            obj=self.where,
            field=_FIELD_CELL,
            value=at,
            context={"part": self.part},
        )


def _row_number(text: str | None, last: int, where: str) -> int:
    """El número de la fila (el siguiente si no lo tiene); fuera de orden o de la hoja →
    :class:`TableError`."""
    number = last + 1 if text is None else _int(text)
    if number is None or not last < number <= _MAX_ROW:
        raise TableError(
            "io.xlsx_malformed",
            f"la fila no tiene un número válido o no va en orden (la anterior es la {last}): "
            f"el libro está dañado; {_SAVE_AS_XLSX}",
            obj=where,
            field="fila",
            value=text,
        )
    return number


def _column(at: str, last: int, row: int, where: str) -> int:
    """La columna (1 = A) de la referencia ``at``; fuera de la hoja o de orden →
    :class:`TableError`."""
    match = _CELL_REF.fullmatch(at)
    column = 0
    if match:
        for letter in match[1].upper():
            column = column * 26 + ord(letter) - ord("A") + 1
    if not match or not last < column <= _MAX_COLUMN:
        raise TableError(
            "io.xlsx_malformed",
            f"la referencia de la celda no es válida, está fuera de la hoja o no va en orden "
            f"en la fila {row}: el libro está dañado; {_SAVE_AS_XLSX}",
            obj=where,
            field=_FIELD_CELL,
            value=at,
        )
    return column


def _ref(column: int, row: int) -> str:
    letters = ""
    while column:
        column, rest = divmod(column - 1, 26)
        letters = chr(ord("A") + rest) + letters
    return f"{letters}{row}"


def _number(text: str) -> float | None:
    """El float64 del texto de un ``<v>`` numérico, o ``None`` si no es un número finito."""
    text = text.strip()
    if not _NUMBER.fullmatch(text):
        return None
    number = float(text)
    return number if number - number == 0.0 else None  # ni infinito ni NaN


def _number_text(number: float, mark: str) -> str:
    """El decimal más corto de ``number`` sin exponente (−0 → «0»), con ``mark``."""
    if number == 0.0:
        return "0"
    text = repr(number)
    if "e" in text:
        text = format(Decimal(text), "f")
    elif text.endswith(".0"):
        text = text[:-2]
    return text if mark == "." else text.replace(".", mark)


def _date_text(serial: float, kind: str, date1904: bool, date_format: str | None) -> str | None:
    """El texto de la fecha, hora o duración de número de serie ``serial`` (redondeado al
    segundo), o ``None`` si no es una fecha posible."""
    seconds = round(serial * _SECONDS_PER_DAY)
    if kind in (_TIME, _ELAPSED):
        if seconds < 0:
            return None
        if kind == _TIME:
            seconds %= _SECONDS_PER_DAY
        hours, rest = divmod(seconds, 3600)
        return f"{hours:02d}:{rest // 60:02d}:{rest % 60:02d}"
    day, second = divmod(seconds, _SECONDS_PER_DAY)
    if date1904:
        base = datetime.datetime(1904, 1, 1) if day >= 0 else None
    elif day >= 61:
        base = datetime.datetime(1899, 12, 30)
    elif 1 <= day <= 59:  # antes del 29/02/1900 que cuenta Excel
        base = datetime.datetime(1899, 12, 31)
    else:  # el 0/01/1900 o el 29/02/1900, que no existen
        base = None
    if base is None:
        return None
    try:
        moment = base + datetime.timedelta(days=day, seconds=second)
    except OverflowError:
        return None
    return moment.strftime(date_format or (ISO_DATE if kind == _DATE else ISO_DATETIME))


# --- La tabla ----------------------------------------------------------------------------------
def _table(
    rows: Iterator[tuple[int, list[str]]],
    header_row: int | None,
    max_rows: int | None,
) -> Table:
    columns: list[str] = []
    pending: tuple[int, list[str]] | None = None
    if header_row is not None:
        target = header_row + 1
        for number, fields in rows:
            if number < target:
                continue
            if number == target:
                columns = [name.strip() for name in fields]
                while columns and not columns[-1]:
                    columns.pop()
            else:
                pending = (number, fields)  # la fila de la cabecera no está: vacía
            break
        else:
            return Table([], [], [])
    width = len(columns)
    found: list[list[str]] = []
    lines: list[int] = []

    def take(number: int, fields: list[str]) -> None:
        if any(field.strip() for field in fields):
            if len(fields) < width:
                fields.extend([""] * (width - len(fields)))
            found.append(fields)
            lines.append(number)

    if pending is not None and (max_rows is None or max_rows > 0):
        take(*pending)
    while max_rows is None or len(found) < max_rows:
        record = next(rows, None)
        if record is None:
            break
        take(*record)
    if header_row is None and found:
        widest = max(len(fields) for fields in found)
        for fields in found:
            fields.extend([""] * (widest - len(fields)))
    return Table(columns, found, lines)


# --- Opciones ----------------------------------------------------------------------------------
def _check_count(name: str, value: int | None) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} debe ser un entero ≥ 0 o None, no {value!r}")


def _check_date_format(date_format: str | None) -> None:
    if date_format is None:
        return
    if not isinstance(date_format, str) or "%" not in date_format:
        raise ValueError(f"el formato de fecha es de strftime («%d/%m/%Y»), no {date_format!r}")
    try:
        datetime.datetime(2001, 2, 3, 4, 5, 6).strftime(date_format)
    except ValueError as exc:
        raise ValueError(f"formato de fecha no válido: {date_format!r} ({exc})") from None
