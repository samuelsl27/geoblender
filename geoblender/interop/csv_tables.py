# SPDX-License-Identifier: GPL-3.0-or-later
"""Tablas CSV con separador y codificación declarados (spec 005, T12; plan 005 §5.3.2;
RF-005-03, RF-005-05), con biblioteca estándar. La usan los importadores de sondeos
(spec 005) y de puntos (spec 006).

:func:`read_table` lee un CSV como una :class:`Table` de textos: los nombres de las
columnas, las filas tal como están escritas y la línea del fichero donde empieza cada fila
(para que el importador diga «fila 7» al rechazarla). No interpreta números ni decimales:
eso lo hace quien lee la tabla, con el decimal que declara el usuario.
:func:`preview_table` son las :data:`PREVIEW_ROWS` (20) primeras filas, las del asistente
(RF-005-05); no lee más allá.

- **Codificación** (:data:`ENCODINGS`): la que declara el usuario, nunca adivinada: UTF-8
  (con o sin BOM; el BOM no pasa a la primera columna), Windows-1252, ISO-8859-1 u OEM 850.
  Cada línea se descodifica por separado: un byte que no es de esa codificación, un BOM de
  UTF-8 con otra declarada, UTF-16 o bytes nulos (no es texto) se rechazan con la línea.
- **Separador** (:data:`SEPARATORS`): «;», coma o tabulador, con comillas dobles (``"``)
  alrededor del campo que lleva el separador, comillas (dobladas) o un salto de línea, como
  escribe Excel; o «espacio»: uno o varios espacios o tabuladores, sin comillas (XYZ
  disperso de la spec 006). Unas comillas sin cerrar o mal puestas se rechazan con la línea
  donde empieza la fila.
- **Cabecera**: ``header_row`` es el número de líneas que la preceden (0: la primera);
  ``None``, sin cabecera (sin columnas). A los nombres de las columnas se les quitan los
  espacios de los lados; los valores quedan como están escritos. Se saltan las filas en
  blanco o solo con separadores (las filas vacías de Excel); las demás quedan con sus
  campos, aunque tengan más o menos que la cabecera (el importador las rechaza con su fila).
- **Fuente intacta** (RF-005-03): el fichero se abre solo para leer y nada se escribe ni se
  crea junto a él.

Errores: :class:`TableError` (``io.csv_*``) para el usuario, con el fichero, la línea o la
codificación y qué hacer; ``ValueError`` si las opciones no son de las que ofrece el
asistente (error del programa).
"""

from __future__ import annotations

import codecs
import csv
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from ..core.errors import GeoblenderError

__all__ = [
    "ENCODINGS",
    "PREVIEW_ROWS",
    "SEPARATORS",
    "Table",
    "TableError",
    "preview_table",
    "read_table",
]

ENCODINGS: dict[str, str] = {
    "utf-8": "UTF-8",
    "cp1252": "Windows-1252",
    "iso8859-1": "ISO-8859-1 (Latin-1)",
    "cp850": "OEM 850",
}
"""Codificaciones admitidas (spec 005 §7), por su nombre de Python (el de
``codecs.lookup``; también valen sus alias, como «latin-1» o «windows-1252»), con el nombre
que ve el usuario. UTF-8 admite el BOM («utf-8-sig» es la misma)."""
SEPARATORS: dict[str, str] = {
    ";": "punto y coma",
    ",": "coma",
    "\t": "tabulador",
    " ": "espacio",
}
"""Separadores admitidos y su nombre; el espacio es uno o varios blancos, sin comillas."""
PREVIEW_ROWS = 20
"""Filas de la vista previa del asistente (RF-005-05)."""
QUOTE = '"'
"""Las comillas de un campo (dobladas dentro de él)."""

_UTF8 = "utf-8"
_UTF8_BOM = codecs.BOM_UTF8
_UTF16_BOMS = (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)
_SPACE = " "
_FIELD_LINE = "línea"
_FIELD_ENCODING = "codificación"
_FIELD_PATH = "ruta"
_ENCODING_HINT = (
    "elija la codificación del fichero (los CSV de Excel en español suelen ser "
    "Windows-1252, o UTF-8 si se guardaron como «CSV UTF-8»)"
)


class TableError(GeoblenderError):
    """Un fichero de tabla que no se puede leer como se declaró: el objeto es el nombre del
    fichero; el campo, la línea, la codificación o la ruta (códigos ``io.csv_*``)."""


@dataclass(frozen=True, slots=True)
class Table:
    """Una tabla de textos: ``columns``, los nombres de las columnas (vacío sin cabecera);
    ``rows``, las filas con sus campos tal como están escritos; ``lines``, la línea del
    fichero (desde 1) donde empieza cada fila."""

    columns: list[str]
    rows: list[list[str]]
    lines: list[int]

    def __post_init__(self) -> None:
        if len(self.lines) != len(self.rows):
            raise ValueError(
                f"una tabla necesita una línea por fila: {len(self.rows)} filas y "
                f"{len(self.lines)} líneas"
            )


def read_table(
    path: Path | str,
    *,
    encoding: str,
    separator: str,
    header_row: int | None = 0,
    max_rows: int | None = None,
) -> Table:
    """La tabla del CSV ``path`` (RF-005-05). ``encoding``: una de :data:`ENCODINGS` (o un
    alias); ``separator``: uno de :data:`SEPARATORS`; ``header_row``: las líneas que
    preceden a la cabecera, o ``None`` sin cabecera; ``max_rows``: como mucho esas filas
    (``None``, todas), sin leer más allá. ``ValueError`` si una opción no es válida;
    :class:`TableError` si el fichero no se puede leer así. El fichero solo se lee
    (RF-005-03)."""
    codec = _codec(encoding)
    _check_separator(separator)
    _check_count("header_row", header_row)
    _check_count("max_rows", max_rows)
    path = Path(path)
    try:
        with path.open("rb") as stream:
            return _table(stream, path.name, codec, separator, header_row, max_rows)
    except OSError as exc:
        raise TableError(
            "io.csv_unreadable",
            f"no se puede leer el fichero ({exc.strerror or exc}): compruebe que existe y "
            "que tiene permiso de lectura",
            obj=path.name,
            field=_FIELD_PATH,
            value=str(path),
            context={"error": repr(exc)},
        ) from exc


def preview_table(
    path: Path | str, *, encoding: str, separator: str, header_row: int | None = 0
) -> Table:
    """Las :data:`PREVIEW_ROWS` primeras filas del CSV ``path`` tal como se van a
    interpretar (el asistente, RF-005-05); como :func:`read_table`."""
    return read_table(
        path, encoding=encoding, separator=separator, header_row=header_row,
        max_rows=PREVIEW_ROWS,
    )


def _table(
    stream: BinaryIO,
    name: str,
    codec: str,
    separator: str,
    header_row: int | None,
    max_rows: int | None,
) -> Table:
    records = _records(_decoded(stream, name, codec), name, separator)
    columns: list[str] = []
    if header_row is not None:
        for _ in range(header_row):
            if next(records, None) is None:
                return Table([], [], [])
        header = next(records, None)
        if header is None:
            return Table([], [], [])
        columns = [column.strip() for column in header[1]]
    rows: list[list[str]] = []
    lines: list[int] = []
    while max_rows is None or len(rows) < max_rows:
        record = next(records, None)
        if record is None:
            break
        line, fields = record
        if any(field.strip() for field in fields):
            rows.append(fields)
            lines.append(line)
    return Table(columns, rows, lines)


def _decoded(stream: BinaryIO, name: str, codec: str) -> Iterator[str]:
    """Las líneas del fichero (con su fin de línea), descodificadas una a una: así un
    error dice su línea y la vista previa no descodifica más de lo que lee."""
    for number, raw in enumerate(stream, start=1):
        if number == 1:
            raw = _without_bom(raw, name, codec)
        if b"\x00" in raw:
            raise TableError(
                "io.csv_not_text",
                "tiene bytes nulos: no es un fichero de texto (¿un libro XLSX o un "
                "binario?); para un libro de Excel, elija la hoja o guárdelo como CSV",
                obj=name,
                field=_FIELD_LINE,
                value=number,
            )
        try:
            yield raw.decode(codec)
        except UnicodeDecodeError as exc:
            raise TableError(
                "io.csv_not_decodable",
                f"el byte 0x{raw[exc.start]:02X} (byte {exc.start + 1} de la línea) no es "
                f"texto {ENCODINGS[codec]}: {_ENCODING_HINT}",
                obj=name,
                field=_FIELD_LINE,
                value=number,
                context={"encoding": codec, "detail": str(exc)},
            ) from None


def _without_bom(first: bytes, name: str, codec: str) -> bytes:
    """La primera línea sin el BOM de UTF-8 (si se declaró UTF-8); UTF-16 o un BOM de UTF-8
    con otra codificación, rechazados."""
    if first.startswith(_UTF16_BOMS):
        raise TableError(
            "io.csv_encoding_unsupported",
            "el fichero está en UTF-16 («Texto Unicode» de Excel), que no se admite: "
            "guárdelo como «CSV UTF-8» o «CSV (delimitado por comas)»",
            obj=name,
            field=_FIELD_ENCODING,
            value="UTF-16",
        )
    if not first.startswith(_UTF8_BOM):
        return first
    if codec != _UTF8:
        raise TableError(
            "io.csv_bom_mismatch",
            "el fichero empieza por la marca de UTF-8 (BOM): elija la codificación UTF-8",
            obj=name,
            field=_FIELD_ENCODING,
            value=ENCODINGS[codec],
        )
    return first[len(_UTF8_BOM):]


def _records(lines: Iterable[str], name: str, separator: str) -> Iterator[tuple[int, list[str]]]:
    """(línea donde empieza, campos) de cada fila; una línea en blanco da ``[]``."""
    if separator == _SPACE:
        for number, line in enumerate(lines, start=1):
            yield number, line.split()
        return
    reader = csv.reader(lines, delimiter=separator, quotechar=QUOTE, strict=True)
    start = 1
    while True:
        try:
            fields = next(reader)
        except StopIteration:
            return
        except csv.Error as exc:
            raise TableError(
                "io.csv_malformed",
                f"la fila que empieza en esta línea no es CSV válido con el separador "
                f"«{SEPARATORS[separator]}»: unas comillas sin cerrar o mal puestas (un "
                f"campo entre comillas acaba en comillas seguidas del separador o del fin "
                f"de línea) o un salto de línea suelto",
                obj=name,
                field=_FIELD_LINE,
                value=start,
                context={"detail": str(exc)},
            ) from None
        yield start, fields
        start = reader.line_num + 1


def _codec(encoding: str) -> str:
    """El nombre de Python de ``encoding`` si es una de :data:`ENCODINGS` («utf-8-sig» es
    UTF-8); si no, ``ValueError``."""
    try:
        codec = codecs.lookup(encoding).name if isinstance(encoding, str) else None
    except LookupError:
        codec = None
    if codec == "utf-8-sig":
        codec = _UTF8
    if codec not in ENCODINGS:
        raise ValueError(
            f"codificación no admitida: {encoding!r} (admitidas: {', '.join(ENCODINGS)})"
        )
    return codec


def _check_separator(separator: str) -> None:
    if not isinstance(separator, str) or separator not in SEPARATORS:
        shown = ", ".join(repr(key) for key in SEPARATORS)
        raise ValueError(f"separador no admitido: {separator!r} (admitidos: {shown})")


def _check_count(name: str, value: int | None) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} debe ser un entero ≥ 0 o None, no {value!r}")
