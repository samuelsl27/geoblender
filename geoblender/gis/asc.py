# SPDX-License-Identifier: GPL-3.0-or-later
"""Lector de ESRI ASCII Grid (spec 006; plan 006 §5.3.2, §5.3.6 y §5.4 A5; RF-006-04,
RF-006-08, RF-006-09, RF-006-10, RF-006-28), con biblioteca estándar y numpy.

:func:`read_asc` lee la cabecera (claves sin distinguir mayúsculas, una por línea con su
valor: ``ncols``, ``nrows``, ``xllcorner`` o ``xllcenter``, ``yllcorner`` o
``yllcenter``, ``cellsize`` o ``dx`` y ``dy``, y ``NODATA_value`` si lo hay), la comprueba
**antes de leer los datos** y lee el cuerpo por trozos de :data:`CHUNK_BYTES` sobre un
array float64. Devuelve un :class:`~.raster.RasterSource` con lo que declara la fuente.

- **Rejilla** (como GDAL): ``xllcorner`` es el borde oeste y el norte es
  ``yllcorner + nrows·dy``; con ``xllcenter`` (el centro de la celda inferior izquierda),
  oeste = ``xllcenter − 0,5·dx`` y norte = ``(yllcenter − 0,5·dy) + nrows·dy``, y la
  fuente referencia centros (``pixel_is_point``; sin aviso: el formato no es ambiguo,
  spec §8). Con ``dx`` y ``dy``, celdas no cuadradas de área \\|dx·dy\\| (RF-006-02).
- **Cotas** (RF-006-08): cada una es el float64 de su texto (el más próximo; sin redondeo
  adicional), por filas de norte a sur, sin que importe cómo se reparten en líneas; las
  iguales al ``NODATA_value`` (comparado en float64) y los ``nan``, NaN.
- **CRS** (RF-006-04): el WKT del ``.prj`` del mismo nombre se identifica con el puerto
  :class:`~.ports.CrsService` (``identify_wkt``, pyproj; T11) si se pasa; sin ``.prj``,
  ``declared_crs = None``; con ``.prj`` pero sin servicio o sin identificar, ``None`` y
  una nota (``gis.prj_unidentified``): lo declara el usuario, nunca se supone. Un ASC no
  declara la referencia vertical (``None``).
- **Rechazos** (RF-006-09), con el fichero, la característica (la clave), el valor
  encontrado y qué hacer: cabecera incompleta o incoherente (``gis.asc_header_invalid``),
  un valor que no es un número, con su fila y su columna (``gis.asc_value_invalid``),
  otro número de valores que ``ncols·nrows`` (``gis.asc_value_count``), más celdas que
  ``gis.import.max_cells`` (de ``gis.params``, leído en cada lectura) y ningún dato.
- **Entrada intacta** (RF-006-10): el ASC y su ``.prj`` se abren solo para leer y nada se
  escribe junto a ellos. Avance y cancelación antes y después de cada trozo; la
  cancelación es ``jobs.worker_api.JobCancelled`` y no deja nada.

El lector de contenido ``gis.asc@1`` (``gis.content``, T40) usa las mismas piezas sin cargar
la rejilla entera: :func:`read_header` (la cabecera comprobada, con la referencia de la celda
del noroeste tal como la da el fichero) y :func:`value_chunks` (las cotas por trozos).
"""

from __future__ import annotations

import math
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, NoReturn

import numpy as np

from ..jobs.worker_api import JobCancelled
from . import params
from .grid import Grid
from .messages import GisError, render
from .ports import Cancelled, CrsService, Progress
from .raster import RasterSource

__all__ = ["CHUNK_BYTES", "AscHeader", "read_asc", "read_header", "read_prj",
           "value_chunks"]

MAX_CELLS_KEY = "gis.import.max_cells"
CHUNK_BYTES = 4 << 20
"""Bytes del cuerpo que se leen de una vez (unos 500 000 valores; avance y cancelación
entre trozos)."""
MAX_HEADER_LINE = 4096
"""Longitud máxima de una línea de la cabecera (bytes)."""

_BOM = b"\xef\xbb\xbf"
_WHITESPACE = b" \t\n\r\x0b\x0c"  # los separadores de bytes.split()
_NOT_TEXT = re.compile(rb"[^\x20-\x7e\t\n\r\x0b\x0c]")
_POSITIVE_INTEGER = re.compile(r"\+?[0-9]+")
_SHOWN_TOKEN = 40
_FIELD_VALUES = "valores"

# Clave en minúsculas → como se escribe (el campo de los errores).
_KEYS = {
    key.lower(): key
    for key in ("ncols", "nrows", "xllcorner", "yllcorner", "xllcenter", "yllcenter",
                "cellsize", "dx", "dy", "NODATA_value")
}


@dataclass(frozen=True, slots=True)
class AscHeader:
    """La cabecera comprobada (:func:`read_header`): rejilla, sin dato, si referencia
    centros, cómo da el paso, si el fichero empieza con BOM, dónde empieza el cuerpo y
    ``x0`` e ``y0``, la referencia de la celda del noroeste **tal como la da el fichero**
    (su esquina noroeste con ``xllcorner``; su centro con ``xllcenter``)."""

    grid: Grid
    nodata: float | None
    centre: bool
    steps: str
    bom: bool
    body_offset: int
    x0: float
    y0: float


def read_asc(
    path: Path | str,
    *,
    max_cells: int | None = None,
    crs_service: CrsService | None = None,
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> RasterSource:
    """El MDT del ESRI ASCII Grid ``path`` en su rejilla de origen (RF-006-08).
    ``max_cells``: el límite de celdas (por defecto, ``gis.import.max_cells`` de
    ``gis.params``); ``crs_service``: el que identifica el WKT del ``.prj`` (sin él, el CRS
    queda sin declarar). ``GisError`` si el fichero no se admite (RF-006-09);
    ``JobCancelled`` si ``cancelled()`` pide parar."""
    path = Path(path)
    name = path.name
    with path.open("rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        header = read_header(stream, name)
        grid = header.grid
        limit = int(params.default(MAX_CELLS_KEY)) if max_cells is None else int(max_cells)
        cells = grid.ncols * grid.nrows
        if cells > limit:
            raise GisError(
                "gis.raster_too_large",
                obj=name,
                field="ncols × nrows",
                value=cells,
                file=name,
                limit=limit,
            )
        values = _read_values(stream, size, header, name, progress, cancelled)
    if header.nodata is not None and not math.isnan(header.nodata):
        values[values == header.nodata] = np.nan
    if np.isnan(values).all():
        raise GisError("gis.raster_empty", obj=name, field=_FIELD_VALUES, file=name)
    crs, notes = None, ()
    prj = _prj_path(path)
    if prj is not None:
        wkt = read_prj(path)
        if wkt and crs_service is not None:
            crs = crs_service.identify_wkt(wkt)
        if crs is None:
            notes = (render("gis.prj_unidentified", file=name, prj=prj.name),)
    return RasterSource(
        grid=grid,
        values=values,
        source_dtype="float64",
        nodata_value=header.nodata,
        pixel_is_point=header.centre,
        declared_crs=crs,
        declared_vertical=None,
        encoding=_encoding(header),
        notes=notes,
    )


def read_prj(path: Path | str) -> str | None:
    """El WKT del ``.prj`` del ASC ``path`` (mismo nombre, extensión ``.prj``), sin BOM ni
    blancos alrededor (UTF-8 o, si no lo es, Latin-1), o ``None`` si no hay ``.prj``."""
    prj = _prj_path(Path(path))
    if prj is None:
        return None
    data = prj.read_bytes().removeprefix(_BOM)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    return text.strip()


def _prj_path(path: Path) -> Path | None:
    for suffix in (".prj", ".PRJ"):
        candidate = path.with_suffix(suffix)
        if candidate.is_file():
            return candidate
    return None


# --- Cabecera -----------------------------------------------------------------------------


def _invalid(name: str, field: str, value: str | None, detail: str) -> NoReturn:
    """``gis.asc_header_invalid``; el valor y el detalle, ya cortados con :func:`_short`."""
    raise GisError(
        "gis.asc_header_invalid",
        obj=name,
        field=field,
        value=None if value is None else _short(value),
        file=name,
        detail=detail,
    )


def _short(text: str) -> str:
    """``text`` cortado a :data:`_SHOWN_TOKEN` caracteres para un mensaje."""
    return text if len(text) <= _SHOWN_TOKEN else text[: _SHOWN_TOKEN - 1] + "…"


def _is_key(token: bytes) -> bool:
    """Si ``token`` empieza una línea de la cabecera: empieza por una letra (como en
    GDAL) y no es un número (``nan``, ``inf``); si no, la línea es del cuerpo, también si
    su primer valor está mal escrito (``801,5``)."""
    if not token[:1].isalpha():
        return False
    try:
        float(token)
    except ValueError:
        return True
    return False


def read_header(stream: BinaryIO, name: str) -> AscHeader:
    """Lee las líneas de la cabecera del ASC abierto en ``stream`` (hasta la primera que no
    empieza por una clave) y las comprueba **antes de leer los datos**;
    ``gis.asc_header_invalid`` si falta o sobra algo (``name``, el del fichero)."""
    bom = stream.read(len(_BOM)) == _BOM
    offset = len(_BOM) if bom else 0
    stream.seek(offset)
    fields: dict[str, str] = {}
    while True:
        line = stream.readline(MAX_HEADER_LINE)
        tokens = line.split()
        if not line or (tokens and not _is_key(tokens[0])):
            break  # fin del fichero o primera línea del cuerpo
        if _NOT_TEXT.search(line):
            _invalid(name, "cabecera", None,
                     "no es texto ASCII: ¿es un fichero de otro formato con extensión .asc?")
        if len(line) == MAX_HEADER_LINE and not line.endswith(b"\n"):
            _invalid(name, "cabecera", None,
                     f"una línea de la cabecera tiene más de {MAX_HEADER_LINE} bytes")
        offset += len(line)
        if not tokens:
            continue  # línea en blanco
        written = tokens[0].decode("ascii")
        key = _KEYS.get(written.lower())
        text = " ".join(token.decode("ascii") for token in tokens[1:]) or None
        if key is None:
            written = _short(written)
            _invalid(name, written, text, f"«{written}» no es una clave de ESRI ASCII Grid")
        if len(tokens) != 2:
            _invalid(name, key, text,
                     f"la línea «{_short(' '.join(t.decode('ascii') for t in tokens))}» "
                     "debe tener una clave y un valor")
        if key in fields:
            _invalid(name, key, text, f"«{key}» está dos veces")
        fields[key] = text  # type: ignore[assignment]
    return _check_header(fields, name, bom, offset)


def _check_header(fields: dict[str, str], name: str, bom: bool, offset: int) -> AscHeader:
    ncols = _count(fields, "ncols", name)
    nrows = _count(fields, "nrows", name)
    x_key = _origin(fields, "xllcorner", "xllcenter", name)
    y_key = _origin(fields, "yllcorner", "yllcenter", name)
    centre = x_key == "xllcenter"
    if (y_key == "yllcenter") != centre:
        _invalid(name, y_key, fields[y_key],
                 f"«{x_key}» con «{y_key}» mezcla esquina y centro: use «xllcorner» y "
                 "«yllcorner», o «xllcenter» y «yllcenter»")
    x = _finite(fields, x_key, name)
    y = _finite(fields, y_key, name)
    if "cellsize" in fields:
        if "dx" in fields or "dy" in fields:
            _invalid(name, "cellsize", fields["cellsize"],
                     "«cellsize» y «dx» o «dy» a la vez: use solo uno de los dos")
        dx = dy = _step(fields, "cellsize", name)
        steps = "cellsize"
    elif "dx" in fields or "dy" in fields:
        for key in ("dx", "dy"):
            if key not in fields:
                _invalid(name, key, None, f"falta «{key}»")
        dx, dy = _step(fields, "dx", name), _step(fields, "dy", name)
        steps = "dx y dy"
    else:
        _invalid(name, "cellsize", None, "falta «cellsize» o «dx» y «dy»")
    nodata = None
    if "NODATA_value" in fields:
        nodata = _number(fields, "NODATA_value", name)
    if centre:  # como GDAL: centro de la celda inferior izquierda − medio paso
        west = x - 0.5 * dx
        north = (y - 0.5 * dy) + nrows * dy
    else:
        west = x
        north = y + nrows * dy
    if not (math.isfinite(west) and math.isfinite(north)):
        _invalid(name, y_key, fields[y_key], "la rejilla se sale de los números finitos")
    first_y = y + (nrows - 1) * dy if centre else north
    return AscHeader(Grid(west, north, dx, dy, ncols, nrows), nodata, centre, steps, bom,
                     offset, x, first_y)


def _required(fields: dict[str, str], key: str, name: str) -> str:
    if key not in fields:
        _invalid(name, key, None, f"falta «{key}»")
    return fields[key]


def _count(fields: dict[str, str], key: str, name: str) -> int:
    text = _required(fields, key, name)
    if not _POSITIVE_INTEGER.fullmatch(text) or int(text) < 1:
        _invalid(name, key, text,
                 f"«{key}» = «{_short(text)}» no es un número entero positivo")
    return int(text)


def _origin(fields: dict[str, str], corner: str, centre: str, name: str) -> str:
    if corner in fields and centre in fields:
        _invalid(name, centre, fields[centre], f"«{corner}» y «{centre}» a la vez")
    if corner not in fields and centre not in fields:
        _invalid(name, corner, None, f"falta «{corner}» o «{centre}»")
    return corner if corner in fields else centre


def _number(fields: dict[str, str], key: str, name: str) -> float:
    text = fields[key]
    try:
        return float(text)
    except ValueError:
        _invalid(name, key, text, f"«{key}» = «{_short(text)}» no es un número")


def _finite(fields: dict[str, str], key: str, name: str) -> float:
    text = fields[key]
    try:
        value = float(text)
    except ValueError:
        value = math.nan
    if not math.isfinite(value):
        _invalid(name, key, text, f"«{key}» = «{_short(text)}» no es un número finito")
    return value


def _step(fields: dict[str, str], key: str, name: str) -> float:
    text = fields[key]
    try:
        value = float(text)
    except ValueError:
        value = math.nan
    if not (math.isfinite(value) and value > 0.0):
        _invalid(name, key, text, f"«{key}» = «{_short(text)}» no es un paso positivo")
    return value


# --- Cuerpo -------------------------------------------------------------------------------


_SPACES = tuple(bytes((byte,)) for byte in _WHITESPACE)
_TAIL_BYTES = 256


def _last_space(data: bytes) -> int:
    """Posición del último separador de ``data`` (−1 si no tiene). Se busca primero en
    los últimos bytes: buscar en todo el trozo un separador que no usa (un tabulador) lo
    recorrería entero."""
    for window in (_TAIL_BYTES, len(data)):
        start = max(0, len(data) - window)
        found = max(data.rfind(space, start) for space in _SPACES)
        if found >= 0:
            return found
    return -1


def value_chunks(
    stream: BinaryIO,
    size: int,
    header: AscHeader,
    name: str,
    *,
    chunk_bytes: int = CHUNK_BYTES,
    cancelled: Cancelled | None = None,
) -> Iterator[tuple[float, str, np.ndarray]]:
    """Las cotas del cuerpo del ASC abierto en ``stream`` (``size`` bytes), por trozos de
    ``chunk_bytes`` que se cortan en un separador (un número nunca queda partido entre dos
    trozos), en el orden del fichero: tras cada trozo, la fracción leída, el texto del
    avance y sus cotas en float64 (las que caben en la rejilla; las que sobran solo se
    cuentan). Al terminar, ``gis.asc_value_count`` si no son ``ncols·nrows``; un valor que
    no es un número, ``gis.asc_value_invalid``. ``cancelled`` se consulta antes de cada
    trozo (``JobCancelled``)."""
    grid = header.grid
    expected = grid.ncols * grid.nrows
    found = 0  # valores vistos (los que sobran solo se cuentan)
    total = size - header.body_offset
    chunks = max(1, -(-total // chunk_bytes))
    stream.seek(header.body_offset)
    done, index, carry = 0, 0, b""
    while done < total:
        if cancelled is not None and cancelled():
            raise JobCancelled(f"Cancelado al leer «{name}» en el trozo {index + 1} de {chunks}")
        data = stream.read(min(chunk_bytes, total - done))
        # Sin bytes, el fichero se ha acortado mientras se leía: lo que queda es el final
        # (y la cuenta de valores lo dirá).
        done = done + len(data) if data else total
        part = carry + data
        if done < total:
            cut = _last_space(part) + 1
            part, carry = part[:cut], part[cut:]
        else:
            carry = b""
        tokens = part.split()
        wanted = tokens[: max(0, expected - found)]
        values = _parse(wanted, found, grid.ncols, name) if wanted else np.empty(0)
        found += len(tokens)
        index += 1
        yield done / total, f"Leyendo «{name}»: trozo {index} de {chunks}", values
    if found != expected:
        raise GisError(
            "gis.asc_value_count",
            obj=name,
            field=_FIELD_VALUES,
            value=found,
            file=name,
            expected=expected,
            ncols=grid.ncols,
            nrows=grid.nrows,
        )


def _read_values(
    stream: BinaryIO,
    size: int,
    header: AscHeader,
    name: str,
    progress: Progress | None,
    cancelled: Cancelled | None,
) -> np.ndarray:
    """Las cotas del cuerpo (:func:`value_chunks` con :data:`CHUNK_BYTES`) en un array
    (nrows, ncols) float64."""
    grid = header.grid
    flat = np.empty(grid.ncols * grid.nrows, np.float64)
    found = 0
    for fraction, text, values in value_chunks(stream, size, header, name,
                                               chunk_bytes=CHUNK_BYTES, cancelled=cancelled):
        flat[found : found + len(values)] = values
        found += len(values)
        if progress is not None:
            progress(fraction, text)
    return flat.reshape(grid.shape)


def _parse(tokens: list[bytes], start: int, ncols: int, name: str) -> np.ndarray:
    """Los números de ``tokens`` en float64 (cada uno, el más próximo a su texto);
    ``gis.asc_value_invalid`` con la fila y la columna del primero que no lo es."""
    try:
        return np.array(tokens, dtype=np.float64)
    except ValueError:
        pass
    for offset, token in enumerate(tokens):
        try:
            np.array([token], dtype=np.float64)
        except ValueError:
            position = start + offset
            raise GisError(
                "gis.asc_value_invalid",
                obj=name,
                field=_FIELD_VALUES,
                value=_short(token.decode("ascii", "backslashreplace")),
                file=name,
                row=position // ncols + 1,
                column=position % ncols + 1,
            ) from None
    raise AssertionError("numpy rechazó un trozo sin ningún valor que rechazar")


def _encoding(header: AscHeader) -> str:
    """Cómo está escrito el fichero, para el informe (``ESRI ASCII Grid, texto ASCII,
    xllcorner/yllcorner, cellsize``)."""
    parts = [
        "ESRI ASCII Grid",
        "texto ASCII con BOM UTF-8" if header.bom else "texto ASCII",
        "xllcenter/yllcenter" if header.centre else "xllcorner/yllcorner",
        header.steps,
    ]
    if header.nodata is None:
        parts.append("sin NODATA_value")
    return ", ".join(parts)
