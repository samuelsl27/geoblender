# SPDX-License-Identifier: GPL-3.0-or-later
"""Lector de XYZ en malla regular (spec 006; plan 006 §5.3.2, §5.3.6 y §5.4 A5; RF-006-08,
RF-006-09, RF-006-10, RF-006-28), con biblioteca estándar y numpy.

:func:`read_xyz_grid` lee un texto con una línea ``X Y Z`` por punto —los centros de las
celdas, en cualquier orden— y devuelve un :class:`~.raster.RasterSource` en la rejilla
cuyos centros son esos puntos.

- **Texto**: separador espacios (uno o varios), tabulador, coma o «;» (``separator``; con
  ``None``, el de la primera línea de datos: «;»; si no, tabulador; si no, coma, solo con
  punto decimal; si no, espacios); punto o coma decimal (``decimal``); una cabecera
  opcional (la primera línea, si ninguno de sus valores es un número); BOM UTF-8, CRLF y
  líneas en blanco. El cuerpo se lee por trozos de :data:`CHUNK_BYTES` cortados en un fin
  de línea y se convierte con numpy de una vez por trozo.
- **Malla** (A5), en X y en Y por separado: los valores distintos, ordenados, se agrupan
  cuando distan ≤ 2 mm (los de una misma columna con ruido); el paso inicial es la mediana
  de las diferencias entre grupos, y el definitivo, (último − primero) / nº de pasos,
  redondeado a la micra si dista de ella menos de 10 nm (el paso de su texto: 0,1 y no
  0,099 999 999 99…). Cada punto va a la celda ``rint((x − x₀)/paso)`` y debe estar a
  ≤ :data:`GRID_TOLERANCE_M` (1 mm) de su centro; las celdas sin punto son NaN. Oeste =
  primera X − medio paso; norte = última Y + medio paso; filas de norte a sur. Dos mallas
  intercaladas justo a medio paso son, para este criterio, una de medio paso con huecos.
- **Cotas** (RF-006-08): cada una, el float64 de su texto (el más próximo, sin redondeo
  adicional); ``nan``, sin dato. Un XYZ no declara valor sin dato, CRS ni referencia
  vertical (``None``): los declara el usuario (RF-006-04), nunca se suponen.
- **Rechazos** (RF-006-09), con el fichero, la característica, el valor y qué hacer:
  ``gis.xyz_not_grid`` (con la sugerencia de importarlo como puntos) si un punto está a
  más de 1 mm de la malla (malla irregular o sobre más de una malla), si dos caen en la
  misma celda (puntos repetidos) o si solo hay una fila o una columna;
  ``gis.xyz_line_invalid``, con la línea, si no tiene tres valores, si uno no es un número,
  si una X o una Y no es finita o si el fichero no es texto; ``gis.raster_too_large`` con
  más celdas (o más puntos, al leerlos) que ``gis.import.max_cells``, y
  ``gis.raster_empty`` sin ninguna cota.
- **Entrada intacta** (RF-006-10): el fichero se abre solo para leer y nada se escribe
  junto a él. Avance y cancelación por trozos (RF-006-28); la cancelación es
  ``jobs.worker_api.JobCancelled`` y no deja nada.

El lector de contenido ``gis.xyz_grid@1`` (``gis.content``, T40) usa las mismas piezas:
:func:`point_steps` (los puntos por trozos, con su avance) y :func:`fit_grid` (la malla, con
la referencia de la celda del noroeste tal como la dan los puntos: su centro).
"""

from __future__ import annotations

import bisect
import math
import os
import re
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, NoReturn

import numpy as np

from ..core.i18n import format_number
from ..jobs.worker_api import JobCancelled
from . import params
from .grid import Grid
from .messages import GisError
from .ports import Cancelled, Progress
from .raster import RasterSource

__all__ = [
    "CHUNK_BYTES",
    "DECIMALS",
    "GRID_TOLERANCE_M",
    "SEPARATORS",
    "XyzGrid",
    "XyzPoints",
    "check_options",
    "fit_grid",
    "point_steps",
    "read_xyz_grid",
]

MAX_CELLS_KEY = "gis.import.max_cells"
CHUNK_BYTES = 4 << 20
"""Bytes que se leen de una vez (unas 130 000 líneas; avance y cancelación entre trozos)."""
GRID_TOLERANCE_M = 0.001
"""Distancia máxima de un punto al centro de su celda (plan 006 §5.3.6: ±1 mm)."""
ROUNDING_SLACK_M = 1e-8
"""Margen del redondeo de float64 al comparar coordenadas UTM (el ulp de 4,4·10⁶ m es
0,93 nm): 10 nm."""
STEP_DECIMALS = 6
"""Decimales (micras) del paso de un texto: el paso se redondea a ellos si dista menos de
:data:`ROUNDING_SLACK_M`."""
MAX_LINE = 4096
"""Longitud máxima de una línea antes de la primera de datos (bytes)."""
SEPARATORS = {" ": "espacio", "\t": "tabulador", ",": "coma", ";": "punto y coma"}
"""Separadores admitidos y su nombre en el informe; el espacio es uno o varios blancos."""
DECIMALS = {".": "punto", ",": "coma"}
"""Separadores decimales admitidos y su nombre en el informe."""

_BOM = b"\xef\xbb\xbf"
_NOT_TEXT = re.compile(rb"[\x00-\x08\x0e-\x1f\x7f]")
_LOOSE = {".": re.compile(rb"[;,\s]+"), ",": re.compile(rb"[;\s]+")}
_SPACE = np.zeros(256, dtype=bool)
_SPACE[list(b" \t\n\r\x0b\x0c")] = True  # los separadores de bytes.split()
_COLUMNS = "XYZ"
_SHOWN_TOKEN = 40
_FIELD_LINE = "línea"
_FIELD_POINTS = "puntos"
_COMMA_HINT = "; si usa coma decimal, elija «coma» como decimal"


@dataclass(frozen=True, slots=True)
class _Prefix:
    """Lo que hay antes de los datos: BOM, cabecera, el separador (elegido o detectado), el
    byte donde empieza la primera línea de datos y las líneas que la preceden."""

    bom: bool
    header: bool
    separator: str
    detected: bool
    offset: int
    lines: int


class _LineIndex:
    """La línea del fichero de cada punto, por trozos: sin líneas en blanco en un trozo,
    solo su primera línea; con ellas, la de cada punto."""

    def __init__(self) -> None:
        self._first_points: list[int] = []
        self._blocks: list[tuple[int, np.ndarray | None]] = []

    def add(self, first_point: int, first_line: int, lines: np.ndarray | None) -> None:
        self._first_points.append(first_point)
        self._blocks.append((first_line, lines))

    def line(self, point: int) -> int:
        block = bisect.bisect_right(self._first_points, point) - 1
        first_line, lines = self._blocks[block]
        offset = point - self._first_points[block]
        return first_line + offset if lines is None else int(lines[offset])


@dataclass(frozen=True, slots=True)
class XyzPoints:
    """Los puntos de un XYZ (:func:`point_steps`): ``xyz`` (n, 3) float64 en el orden del
    fichero, la línea de cada uno (``lines``) y lo que hay antes de los datos (``prefix``)."""

    xyz: np.ndarray
    lines: _LineIndex
    prefix: _Prefix


@dataclass(frozen=True, slots=True)
class XyzGrid:
    """La malla de unos puntos (:func:`fit_grid`): su rejilla (``grid``), sus cotas
    (``values``, NaN en las celdas sin punto) y ``x0`` e ``y0``, la referencia de la celda
    del noroeste tal como la dan los puntos: su centro (la X de la primera columna y la Y de
    la fila norte)."""

    grid: Grid
    values: np.ndarray
    x0: float
    y0: float


def read_xyz_grid(
    path: Path | str,
    *,
    separator: str | None = None,
    decimal: str = ".",
    max_cells: int | None = None,
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> RasterSource:
    """El MDT del XYZ en malla ``path`` en su rejilla de origen (RF-006-08).
    ``separator``: uno de :data:`SEPARATORS` o ``None`` (se detecta); ``decimal``: uno de
    :data:`DECIMALS`; ``max_cells``: el límite de celdas (por defecto,
    ``gis.import.max_cells`` de ``gis.params``). ``ValueError`` si las opciones no son
    válidas (también coma como separador y como decimal); ``GisError`` si el fichero no se
    admite (RF-006-09); ``JobCancelled`` si ``cancelled()`` pide parar."""
    check_options(separator, decimal)
    path = Path(path)
    name = path.name
    limit = int(params.default(MAX_CELLS_KEY)) if max_cells is None else int(max_cells)
    with path.open("rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        points = _drive(point_steps(stream, size, name, separator=separator, decimal=decimal,
                                    limit=limit, chunk_bytes=CHUNK_BYTES, cancelled=cancelled),
                        progress)
    fitted = fit_grid(points, name, limit)
    grid = fitted.grid
    return RasterSource(
        grid=grid,
        values=fitted.values,
        source_dtype="float64",
        nodata_value=None,
        pixel_is_point=True,
        declared_crs=None,
        declared_vertical=None,
        encoding=_encoding(points.prefix, decimal, len(points.xyz), grid.ncols, grid.nrows),
    )


def fit_grid(points: XyzPoints, name: str, limit: int) -> XyzGrid:
    """La malla de ``points`` (A5): ``gis.raster_empty`` sin puntos o sin ninguna cota,
    ``gis.xyz_not_grid`` si no forman una malla y ``gis.raster_too_large`` con más celdas
    que ``limit`` (``name``, el del fichero)."""
    xyz, lines = points.xyz, points.lines
    if not len(xyz):
        raise GisError("gis.raster_empty", obj=name, field=_FIELD_POINTS, file=name)
    west_centre, dx, columns = _axis(xyz[:, 0], "X", name, lines)
    # Y cambiada de signo: el primer grupo es la fila norte y los índices crecen hacia el sur.
    minus_top, dy, rows = _axis(-xyz[:, 1], "Y", name, lines, sign=-1.0)
    ncols, nrows = int(columns.max()) + 1, int(rows.max()) + 1
    cells = ncols * nrows
    if cells > limit:
        raise GisError("gis.raster_too_large", obj=name, field="columnas × filas",
                       value=cells, file=name, limit=limit)
    grid = Grid(west_centre - 0.5 * dx, -minus_top + 0.5 * dy, dx, dy, ncols, nrows)
    flat = rows.astype(np.int64) * ncols + columns.astype(np.int64)
    _check_repeated(flat, grid, name, lines)
    values = np.full(cells, np.nan)
    values[flat] = xyz[:, 2]
    values = values.reshape(nrows, ncols)
    if np.isnan(values).all():
        raise GisError("gis.raster_empty", obj=name, field=_FIELD_POINTS, file=name)
    return XyzGrid(grid, values, west_centre, -minus_top)


def _drive(
    steps: Generator[tuple[float, str], None, XyzPoints], progress: Progress | None
) -> XyzPoints:
    """Avanza :func:`point_steps` hasta el final, con su avance."""
    while True:
        try:
            fraction, text = next(steps)
        except StopIteration as stop:
            return stop.value
        if progress is not None:
            progress(fraction, text)


def check_options(separator: str | None, decimal: str) -> None:
    """``ValueError`` si ``separator`` (de :data:`SEPARATORS` o ``None``, que se detecta) o
    ``decimal`` (de :data:`DECIMALS`) no se admiten, también la coma como los dos."""
    if separator is not None and separator not in SEPARATORS:
        raise ValueError(f"separador {separator!r} no admitido: {list(SEPARATORS)} o None")
    if decimal not in DECIMALS:
        raise ValueError(f"decimal {decimal!r} no admitido: {list(DECIMALS)}")
    if separator == "," and decimal == ",":
        raise ValueError("la coma no puede ser a la vez el separador y el decimal")


# --- Lectura ------------------------------------------------------------------------------


def _short(text: str) -> str:
    """``text`` cortado a :data:`_SHOWN_TOKEN` caracteres para un mensaje."""
    return text if len(text) <= _SHOWN_TOKEN else text[: _SHOWN_TOKEN - 1] + "…"


def _line_invalid(name: str, line: int, field: str, value: object, detail: str) -> NoReturn:
    raise GisError("gis.xyz_line_invalid", obj=name, field=field, value=value, file=name,
                   line=line, detail=detail)


def _check_text(data: bytes, name: str, first_line: int) -> None:
    """``gis.xyz_line_invalid`` en la línea del primer carácter de control de ``data``
    (que empieza en la línea ``first_line``)."""
    found = _NOT_TEXT.search(data)
    if found is not None:
        line = first_line + data.count(b"\n", 0, found.start())
        _line_invalid(name, line, _FIELD_LINE, None,
                      "no es texto: ¿es un fichero de otro formato con extensión .xyz?")


def _is_number(token: bytes, decimal: str) -> bool:
    try:
        float(token.replace(b",", b".") if decimal == "," else token)
    except ValueError:
        return False
    return True


def _detect(line: bytes, decimal: str) -> str:
    """El separador de la línea de datos ``line``."""
    if b";" in line:
        return ";"
    if b"\t" in line:
        return "\t"
    if decimal == "." and b"," in line:
        return ","
    return " "


def _read_prefix(stream: BinaryIO, name: str, separator: str | None,
                 decimal: str) -> _Prefix:
    """Lee el BOM, las líneas en blanco y la cabecera hasta la primera línea de datos, y
    detecta en ella el separador si no se ha elegido."""
    bom = stream.read(len(_BOM)) == _BOM
    offset = len(_BOM) if bom else 0
    stream.seek(offset)
    lines, header, line = 0, False, b""
    while True:
        line = stream.readline(MAX_LINE)
        if not line:
            break  # fin del fichero sin datos
        _check_text(line, name, lines + 1)
        if len(line) == MAX_LINE and not line.endswith(b"\n"):
            _line_invalid(name, lines + 1, _FIELD_LINE, None,
                          f"tiene más de {MAX_LINE} bytes: ¿es un fichero XYZ?")
        tokens = [token for token in _LOOSE[decimal].split(line) if token]
        if tokens:
            if header or any(_is_number(token, decimal) for token in tokens):
                break  # primera línea de datos
            header = True
        offset += len(line)
        lines += 1
    chosen = _detect(line, decimal) if separator is None else separator
    return _Prefix(bom, header, chosen, separator is None, offset, lines)


def point_steps(
    stream: BinaryIO,
    size: int,
    name: str,
    *,
    separator: str | None,
    decimal: str,
    limit: int,
    chunk_bytes: int = CHUNK_BYTES,
    cancelled: Cancelled | None = None,
) -> Generator[tuple[float, str], None, XyzPoints]:
    """Los puntos del XYZ abierto en ``stream`` (``size`` bytes): lee lo que hay antes de los
    datos y las líneas de datos por trozos de ``chunk_bytes`` cortados en un fin de línea
    (una línea nunca queda partida). Da, tras cada trozo, la fracción leída y el texto del
    avance, y devuelve (``StopIteration.value``) los :class:`XyzPoints`. ``GisError`` si una
    línea no vale o si hay más puntos que ``limit``; ``cancelled`` se consulta antes de
    cada trozo (``JobCancelled``)."""
    check_options(separator, decimal)
    prefix = _read_prefix(stream, name, separator, decimal)
    total = size - prefix.offset
    chunks = max(1, -(-total // chunk_bytes))
    stream.seek(prefix.offset)
    blocks: list[np.ndarray] = []
    index = _LineIndex()
    done, chunk, carry, line, points = 0, 0, b"", prefix.lines, 0
    while done < total:
        if cancelled is not None and cancelled():
            raise JobCancelled(
                f"Cancelado al leer «{name}» en el trozo {chunk + 1} de {chunks}")
        data = stream.read(min(chunk_bytes, total - done))
        # Sin bytes, el fichero se ha acortado mientras se leía: lo que queda es el final.
        done = done + len(data) if data else total
        _check_text(data, name, line + 1)  # «carry» no tiene ningún fin de línea
        part = carry + data
        if done < total:
            cut = part.rfind(b"\n") + 1
            part, carry = part[:cut], part[cut:]
        else:
            carry = b""
        if part:
            xyz, first_line, numbers = _parse(part, line, prefix.separator, decimal, name)
            if len(xyz):
                index.add(points, first_line, numbers)
                blocks.append(xyz)
                points += len(xyz)
                if points > limit:  # cada punto es una celda: no hace falta leer más
                    raise GisError("gis.raster_too_large", obj=name, field=_FIELD_POINTS,
                                   value=points, file=name, limit=limit)
            line += part.count(b"\n")
        chunk += 1
        yield done / total, f"Leyendo «{name}»: trozo {chunk} de {chunks}"
    xyz = np.concatenate(blocks) if blocks else np.empty((0, 3), np.float64)
    return XyzPoints(xyz, index, prefix)


def _counts(text: bytes) -> np.ndarray:
    """Cuántos valores tiene cada línea de ``text`` (la última, lo que sigue al último fin
    de línea), sin recorrerlas en Python."""
    if not text:
        return np.zeros(1, np.int64)
    buffer = np.frombuffer(text, dtype=np.uint8)
    space = _SPACE[buffer]
    starts = np.flatnonzero(~space & np.concatenate(([True], space[:-1])))
    newlines = np.flatnonzero(buffer == 0x0A)
    return np.bincount(np.searchsorted(newlines, starts), minlength=newlines.size + 1)


def _split(line: bytes, separator: str) -> list[bytes]:
    """Los valores de la línea original ``line``, como los separa :func:`_parse`."""
    if separator in (",", ";"):
        line = line.replace(separator.encode("ascii"), b" ")
    return line.split()


def _parse(
    part: bytes, before: int, separator: str, decimal: str, name: str
) -> tuple[np.ndarray, int, np.ndarray | None]:
    """Los puntos de ``part`` (líneas enteras que empiezan tras ``before`` líneas), la línea
    del primero y, si hay líneas en blanco, la de cada uno (si no, ``None``)."""
    text = part
    if separator in (",", ";"):
        text = text.replace(separator.encode("ascii"), b" ")
    if decimal == ",":
        text = text.replace(b",", b".")
    counts = _counts(text)
    wrong = np.flatnonzero((counts != 0) & (counts != 3))
    if wrong.size:
        position = int(wrong[0])
        count = int(counts[position])
        found = "1 valor" if count == 1 else f"{count} valores"
        detail = f"tiene {found} y debe tener 3 (X, Y y Z)"
        if decimal == "." and b"," in part.split(b"\n")[position]:
            detail += _COMMA_HINT
        _line_invalid(name, before + position + 1, _FIELD_LINE, count, detail)
    filled = np.flatnonzero(counts)
    tokens = text.split()
    try:
        flat = np.array(tokens, dtype=np.float64)
    except ValueError:
        flat = None
    if flat is None:
        _first_not_number(tokens, filled, part, before, separator, decimal, name)
    xyz = flat.reshape(-1, 3)
    finite = np.isfinite(xyz[:, :2])
    if not finite.all():
        point, column = (int(i) for i in np.argwhere(~finite)[0])
        _value_invalid(part, filled, point, column, before, separator, decimal, name,
                       "no es un número finito")
    first_line = before + 1
    if filled.size == 0 or int(filled[-1]) == filled.size - 1:  # sin líneas en blanco
        return xyz, first_line, None
    return xyz, first_line, first_line + filled


def _first_not_number(tokens: list[bytes], filled: np.ndarray, part: bytes, before: int,
                      separator: str, decimal: str, name: str) -> NoReturn:
    """``gis.xyz_line_invalid`` con el primer valor de ``tokens`` que no es un número."""
    for position, token in enumerate(tokens):
        try:
            np.array([token], dtype=np.float64)
        except ValueError:
            point, column = divmod(position, 3)
            _value_invalid(part, filled, point, column, before, separator, decimal, name,
                           "no es un número")
    raise AssertionError("numpy rechazó un trozo sin ningún valor que rechazar")


def _value_invalid(part: bytes, filled: np.ndarray, point: int, column: int, before: int,
                   separator: str, decimal: str, name: str, problem: str) -> NoReturn:
    """``gis.xyz_line_invalid`` con el valor ``column`` (0 = X) del punto ``point`` de
    ``part``, escrito como en el fichero."""
    position = int(filled[point])
    token = _split(part.split(b"\n")[position], separator)[column]
    text = _short(token.decode("utf-8", "backslashreplace"))
    axis = _COLUMNS[column]
    detail = f"la {axis} «{text}» {problem}"
    if decimal == "." and "," in text:
        detail += _COMMA_HINT
    _line_invalid(name, before + position + 1, axis, text, detail)


# --- Malla --------------------------------------------------------------------------------


def _coordinate(value: float) -> str:
    """Una coordenada en un mensaje, en décimas de milímetro."""
    return format_number(value, 4)


def _metres(value: float) -> str:
    """Un paso en un mensaje, con hasta 6 decimales y sin ceros a la derecha."""
    return format_number(value, STEP_DECIMALS).rstrip("0").rstrip(",.")


def _not_grid(name: str, field: str, value: object, detail: str) -> NoReturn:
    raise GisError("gis.xyz_not_grid", obj=name, field=field, value=value, file=name,
                   detail=detail)


def _axis(
    values: np.ndarray, axis: str, name: str, lines: _LineIndex, sign: float = 1.0
) -> tuple[float, float, np.ndarray]:
    """El centro de la primera columna (o fila), el paso y el índice (float, entero) de
    cada punto en un eje; ``values`` vienen multiplicados por ``sign`` y los mensajes los
    muestran sin él."""
    unique = np.unique(values)
    breaks = np.flatnonzero(np.diff(unique) > 2 * GRID_TOLERANCE_M)
    first = np.concatenate(([0], breaks + 1))
    last = np.concatenate((breaks, [unique.size - 1]))
    centres = 0.5 * (unique[first] + unique[last])  # exacto si el grupo tiene un valor
    if centres.size < 2:
        line = "columna" if axis == "X" else "fila"
        shown = sign * float(centres[0])
        _not_grid(name, axis, shown,
                  f"todos los puntos tienen la misma {axis}, {_coordinate(shown)}: con una "
                  f"sola {line} no se sabe el paso")
    origin = float(centres[0])
    span = float(centres[-1]) - origin
    ratio = span / float(np.median(np.diff(centres)))
    step = span / round(ratio) if math.isfinite(ratio) else math.nan
    snapped = round(step, STEP_DECIMALS) if math.isfinite(step) else step
    if abs(step - snapped) <= ROUNDING_SLACK_M:
        step = snapped
    if not (math.isfinite(step) and step > 2 * GRID_TOLERANCE_M):
        _not_grid(name, axis, step,
                  f"el paso en {axis} saldría de {_metres(step)} m, que no es el de una "
                  "malla")
    index = np.rint((values - origin) / step)
    distance = np.abs(values - (origin + index * step))
    off = np.flatnonzero(distance > GRID_TOLERANCE_M + ROUNDING_SLACK_M)
    if off.size:
        point = int(off[0])
        shown = sign * float(values[point])
        _not_grid(name, axis, shown,
                  f"la {axis} {_coordinate(shown)} de la línea {lines.line(point)} está a "
                  f"{format_number(float(distance[point]) * 1000.0, 2)} mm de la malla de "
                  f"paso {_metres(step)} m, y se admite 1 mm")
    return origin, step, index


def _check_repeated(flat: np.ndarray, grid: Grid, name: str, lines: _LineIndex) -> None:
    """``gis.xyz_not_grid`` si dos puntos caen en la misma celda de ``grid`` (las líneas
    del primer punto que repite celda en el fichero y del que estaba antes en ella)."""
    order = np.argsort(flat, kind="stable")
    ordered = flat[order]
    same = np.flatnonzero(ordered[1:] == ordered[:-1])
    if not same.size:
        return
    later = order[same + 1]
    pair = int(np.argmin(later))
    second, first = int(later[pair]), int(order[same[pair]])
    row, column = divmod(int(flat[second]), grid.ncols)
    x = grid.west + (column + 0.5) * grid.dx
    y = grid.north - (row + 0.5) * grid.dy
    second_line = lines.line(second)
    _not_grid(name, _FIELD_POINTS, second_line,
              f"las líneas {lines.line(first)} y {second_line} caen en la misma celda, la "
              f"de centro X {_coordinate(x)} e Y {_coordinate(y)}: hay puntos repetidos")


def _encoding(prefix: _Prefix, decimal: str, points: int, ncols: int, nrows: int) -> str:
    """Cómo está escrito el fichero, para el informe (``XYZ en malla, texto, separador
    espacio (detectado), punto decimal, sin cabecera, 300 puntos en 20 × 15 celdas``)."""
    separator = SEPARATORS[prefix.separator] + (" (detectado)" if prefix.detected else "")
    return ", ".join((
        "XYZ en malla",
        "texto con BOM UTF-8" if prefix.bom else "texto",
        f"separador {separator}",
        f"{DECIMALS[decimal]} decimal",
        "con cabecera" if prefix.header else "sin cabecera",
        f"{points} puntos en {ncols} × {nrows} celdas",
    ))
