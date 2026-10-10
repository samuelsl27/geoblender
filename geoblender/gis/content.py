# SPDX-License-Identifier: GPL-3.0-or-later
"""Lectores de contenido de la topografía (spec 006, T40; RF-006-26; RF-008-08, RF-008-09,
RF-008-14; ADR-0024 §4 a §7; plan 006 §5.6.2 y D19).

Cinco :class:`~..core.content.readers.ContentReader` de la 008. Cada uno es **una sola
función** generadora, la misma al importar (en el trabajo de la importación), al comprobar en
el hilo de Blender y en el trabajo ``core_content_hash`` (este módulo está en su lista
estática): lee su formato con las piezas del importador de la 006, lo escribe en el
``ContentHasher`` de su petición y da su progreso tras cada trozo (cada ``yield`` es un punto
de cancelación). Lo que el importador no admite es el mismo ``GisError``; ninguno crea, cambia
ni borra nada junto a su fuente (RF-006-10, RF-008-14).

Lo que se hashea es lo que importa la 006 (``gbch/1``, D-8: exacto):

- :data:`GEOTIFF` (``gis.geotiff@1``, ``raster``): las fuentes GeoTIFF y las rejillas de
  ``rasters/`` (perfil ``project``), por bandas de filas (``geotiff.reader.read_bands``, sin
  cargar la rejilla). Cabecera: filas y columnas; la referencia de la celda del noroeste tal
  como la da el fichero (su esquina noroeste o, con *PixelIsPoint*, su centro, y entonces la
  celda es ``"point"``); dx y dy; clase ``float``; el sin dato de ``GDAL_NODATA`` y el CRS de
  sus claves (``{"epsg": n}`` o ``None``). Celdas: las de ``read_geotiff``, en float64, con el
  sin dato y los bloques que no están en el fichero en NaN. Compresión, tiras o teselas,
  BigTIFF, orden de bytes y float32 frente a float64 no cuentan. :func:`raster_digest` da, sin
  escribirlo, el hash de lo que escribe ``GeoTiffIO`` con el perfil ``project`` (ida y
  vuelta).
- :data:`ASC` (``gis.asc@1``, ``raster`` compuesto, ADR-0024 §4): la parte ``main``, la
  rejilla (referencia: la esquina noroeste con ``xllcorner`` o el centro de la celda del
  noroeste con ``xllcenter``; el ``NODATA_value``; sin CRS), por trozos del cuerpo
  (``asc.value_chunks``), y, si la entrada lo tiene, la parte ``prj``: un documento (sus
  bytes).
- :data:`XYZ_GRID` (``gis.xyz_grid@1``, ``raster``): la malla de los puntos
  (``xyz_grid.point_steps`` y ``fit_grid``): referencia, el centro de la celda del noroeste
  (``"point"``); sin sin dato ni CRS del fichero; las celdas sin punto, NaN. El orden de los
  puntos, el separador y el decimal no cuentan. Se lee entero (la malla sale de todos los
  puntos) y sin el límite de celdas de la importación: lo importado se comprueba aunque el
  proyecto cambie ``gis.import.max_cells``.
- :data:`POINTS_TEXT` (``gis.points_text@1``, ``table``, en orden): una fila por fila de la
  tabla (sin las vacías) en el orden del fichero (:data:`POINT_COLUMNS`): X, Y y Z en float64
  con el decimal declarado (``None`` si están vacías o no son un número), el punto, el código
  y la línea en texto (``""`` sin columna) y ``raw``: ``None`` si la fila se importa por sí
  misma y, si no (columnas de menos, o de más con algo escrito; una X, Y o Z que no es un
  número), el JSON canónico de sus campos tal como están. La cabecera y las columnas sin papel
  no cuentan.
- :data:`GPKG_LAYER` (``gis.gpkg_layer@1``, ``vector``, D19): una capa de un GeoPackage
  externo que lee el lector de capas de ``core`` (``core.content.builtin.read_gpkg_layer``)
  en el hasher de esta petición: el mismo hash de datos que ``core.gpkg_layer@1`` y, con las
  mismas declaraciones, el mismo de contenido. Con su ``-wal``, sobre una copia
  (``needs_copy``: el trabajo la copia con ``JobDir.copy_input``; en el hilo, la copia privada
  del lector de ``core``).

**Ajustes de lectura** (``ReadRequest.settings``: los de la importación, que vuelve a recibir
su lector; uno que no es suyo es ``ValueError``): ``nodata_override`` (un número o ``None``) en
los tres de rejilla; ``separator`` (de ``xyz_grid.SEPARATORS`` o ``None``) y ``decimal`` en el
XYZ; ``encoding``, ``separator``, ``decimal``, ``columns`` (``{"x", "y", "z", "point_id",
"code", "line"}`` → índice de columna desde 0, o ``None``), ``header_row`` (por defecto, 0) y
``line_kind`` (``"hard"`` o ``"soft"``) en el texto de puntos; ``layer``, ``role`` y
``elevation_field`` en las capas. **Declaraciones** (``DECL``, ``core.inputs``): los CRS
declarados y las convenciones (el sin dato forzado, la correspondencia de columnas y el tipo
de línea, el papel y el campo de cota): no cambian los datos, sí el hash de contenido.

**Lector de tablas** (ARQ-07): ``gis`` (nivel 2) no importa ``interop`` (nivel 10). El de
puntos lee con el puerto ``gis.ports.TableReader`` que le da :func:`use_table_reader`:
``bl/ops/gis.py`` en Blender y ``workers/core_content_hash.py`` en el trabajo, los dos con
``interop.csv_tables.read_table``. Sin él, ``RuntimeError``.

Importar este módulo no registra nada: :data:`CONTENT_READERS` los reúne para que los
registre ``bl/ops/gis.py``. Python puro y numpy (ADR-0004).
"""

from __future__ import annotations

import math
import numbers
import os
import sys
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from ..core.content import builtin
from ..core.content.encoder import (
    NORMALIZER,
    ContentDigest,
    ContentHasher,
    DocumentEncoder,
    GridEncoder,
)
from ..core.content.readers import MAIN_ROLE, ContentReader, ReadRequest
from ..core.georef import CrsRef
from ..core.hashing import canonical_json
from . import asc, xyz_grid
from .geotiff import reader as geotiff_reader
from .points import ColumnMapping, _field, _number, check_rows_options, row_has_columns
from .ports import TableReader
from .raster import Raster

__all__ = [
    "ASC",
    "CONTENT_READERS",
    "GEOTIFF",
    "GPKG_LAYER",
    "POINTS_TEXT",
    "POINT_COLUMNS",
    "XYZ_GRID",
    "raster_digest",
    "raster_header",
    "table_reader",
    "use_table_reader",
]

PRJ_ROLE = "prj"
"""El papel del ``.prj`` de un ASC en su entrada (la parte documento del compuesto)."""
GRID_SETTINGS: tuple[str, ...] = ("nodata_override",)
"""Ajustes de lectura de ``gis.geotiff@1`` y ``gis.asc@1``."""
XYZ_SETTINGS: tuple[str, ...] = ("separator", "decimal", "nodata_override")
"""Ajustes de lectura de ``gis.xyz_grid@1``."""
POINTS_SETTINGS: tuple[str, ...] = (
    "encoding", "separator", "decimal", "header_row", "columns", "line_kind",
)
"""Ajustes de lectura de ``gis.points_text@1`` (los cuatro primeros sin ``header_row``,
obligatorios: :data:`POINTS_REQUIRED`)."""
POINTS_REQUIRED: tuple[str, ...] = ("encoding", "separator", "decimal", "columns")
GPKG_SETTINGS: tuple[str, ...] = ("layer", "role", "elevation_field")
"""Ajustes de lectura de ``gis.gpkg_layer@1`` (``layer``, obligatorio)."""
MAPPING_ROLES: tuple[str, ...] = ("x", "y", "z", "point_id", "code", "line")
"""Los papeles de ``columns`` en el texto de puntos (X, Y y Z, obligatorios)."""
LINE_KINDS: tuple[str, ...] = ("hard", "soft")
"""El tipo de las líneas del texto de puntos: duras o blandas."""
POINT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("x", "float"),
    ("y", "float"),
    ("z", "float"),
    ("point_id", "text"),
    ("code", "text"),
    ("line", "text"),
    ("raw", "text"),
)
"""Las columnas de la tabla de ``gis.points_text@1``, en su orden."""
TEXT_ROW_BYTES = 64
"""Lo que se cuenta por fila de texto de puntos para repartir el hash en trozos."""
XYZ_READ_SHARE = 0.9
"""La parte del avance de ``gis.xyz_grid@1`` que es leer los puntos (el resto, hashear)."""
GEOTIFF_BYTES_PER_S = 8_000_000
"""Los bytes de un GeoTIFF que lee y hashea ``gis.geotiff@1`` por segundo, a la baja: su
estimación. Medido en el PC de referencia: 2000 × 2000 con DEFLATE y predictor 3, de 30 MB/s
(Float32) a 70 MB/s (Float64); el peor, LZW sin predictor, unos 8,5 MB/s (T34: 43 MB en
5,1 s)."""
ASC_BYTES_PER_S = 40_000_000
"""Ídem, ``gis.asc@1`` (medido: 34 MB, 2000 × 2000 con 3 decimales, en 0,59 s; 58 MB/s)."""
XYZ_BYTES_PER_S = 30_000_000
"""Ídem, ``gis.xyz_grid@1`` (medido: 32 MB, un millón de puntos, en 0,68 s; 47 MB/s)."""
TEXT_BYTES_PER_S = 3_000_000
"""Ídem, ``gis.points_text@1`` (el CSV de ``interop`` y un sha256 por fila, en Python;
medido: 8,5 MB, 200 000 filas, en 2,0 s; 4,2 MB/s)."""

_TABLES = "tables"
_PORTS: dict[str, TableReader] = {}
_LOCK = threading.Lock()
_UNLIMITED = sys.maxsize


# --- El lector de tablas (puerto) -------------------------------------------------------------


def use_table_reader(reader: TableReader | None) -> TableReader | None:
    """Da a ``gis.points_text@1`` el lector de tablas de texto (``interop.csv_tables.
    read_table``; ``None`` lo quita) y devuelve el que tenía. Lo llaman ``bl/ops/gis.py`` al
    registrar y desregistrar y el envoltorio del trabajo ``core_content_hash``."""
    if reader is not None and not callable(reader):
        raise TypeError(f"el lector de tablas es una función, no {type(reader).__name__}")
    with _LOCK:
        previous = _PORTS.pop(_TABLES, None)
        if reader is not None:
            _PORTS[_TABLES] = reader
    return previous


def table_reader() -> TableReader | None:
    """El lector de tablas de texto que tiene ahora ``gis.points_text@1`` (o ``None``)."""
    return _PORTS.get(_TABLES)


# --- Comunes ------------------------------------------------------------------------------------


def _main(request: ReadRequest, optional: tuple[str, ...] = ()) -> Path:
    """El fichero principal; ``ValueError`` si llegan papeles que el lector no lee."""
    extra = sorted(set(request.files) - {MAIN_ROLE, *optional})
    if extra:
        raise ValueError(
            f"el lector «{request.reader}» lee {[MAIN_ROLE, *optional]}, no {extra}"
        )
    return request.files[MAIN_ROLE]


def _settings(request: ReadRequest, allowed: tuple[str, ...]) -> Mapping[str, Any]:
    """Los ajustes de lectura; ``ValueError`` si alguno no es de este lector."""
    unknown = sorted(str(key) for key in request.settings if key not in allowed)
    if unknown:
        raise ValueError(
            f"ajustes de lectura desconocidos para «{request.reader}»: {unknown} (son "
            f"{list(allowed)})"
        )
    return request.settings


def _check_nodata_override(settings: Mapping[str, Any], reader_id: str) -> None:
    """``nodata_override``: un número finito o ``None`` (no se lee: es una convención)."""
    value = settings.get("nodata_override")
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(
            f"el sin dato forzado de «{reader_id}» es un número o None, no {value!r}"
        )
    if not math.isfinite(float(value)):
        raise ValueError(f"el sin dato forzado de «{reader_id}» ({value!r}) no es finito")


def _text_or_none(settings: Mapping[str, Any], key: str, reader_id: str) -> None:
    value = settings.get(key)
    if value is not None and not isinstance(value, str):
        raise TypeError(f"«{key}» de «{reader_id}» es un texto o None, no {value!r}")


def _grid_header(
    rows: int,
    columns: int,
    x0: float,
    y0: float,
    dx: float,
    dy: float,
    *,
    point: bool,
    nodata: float | None,
    crs: CrsRef | None,
) -> dict[str, Any]:
    """La cabecera ``gbch/1`` de una rejilla de cotas (clase ``float``)."""
    return {
        "rows": rows,
        "columns": columns,
        "x0": x0,
        "y0": y0,
        "dx": dx,
        "dy": dy,
        "cell": "point" if point else "area",
        "class": "float",
        "nodata": nodata,
        "crs": None if crs is None else {"epsg": crs.epsg},
    }


def _per_second(speed: int) -> Callable[[int], float]:
    """La estimación de un lector que lee ``speed`` bytes por segundo."""

    def estimate(size: int) -> float:
        return size / speed

    return estimate


# --- gis.geotiff@1 ------------------------------------------------------------------------------


def read_geotiff(request: ReadRequest) -> Iterator[float]:
    """El generador de ``gis.geotiff@1``: la cabecera (comprobada como al importar) y las
    celdas por bandas de filas, con el avance por bloques."""
    path = _main(request)
    _check_nodata_override(_settings(request, GRID_SETTINGS), request.reader)
    with open(path, "rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        header = geotiff_reader.read_header(stream, size, path.name)
        feed = request.hasher.begin_grid(_grid_header(
            header.height, header.width, header.x0, header.y0, header.dx, header.dy,
            point=header.pixel_is_point, nodata=header.nodata, crs=header.crs,
        ))
        for fraction, band in geotiff_reader.read_bands(stream, header):
            if band is not None:
                feed.update(band)
            if fraction < 1.0:
                yield fraction
        feed.finish()
    yield 1.0


def raster_header(raster: Raster) -> dict[str, Any]:
    """La cabecera ``gbch/1`` con que ``gis.geotiff@1`` lee ``raster`` escrito por
    ``GeoTiffIO`` con el perfil ``project``: su rejilla (esquina noroeste, celda área), sin
    dato NaN y el EPSG de su CRS."""
    grid = raster.grid
    return _grid_header(grid.nrows, grid.ncols, grid.west, grid.north, grid.dx, grid.dy,
                        point=False, nodata=math.nan, crs=raster.crs)


def raster_digest(
    raster: Raster, declarations: Mapping[str, Any], *, normalizer: str = NORMALIZER
) -> ContentDigest:
    """El ``ContentDigest`` que da ``gis.geotiff@1`` al leer ``raster`` escrito por
    ``GeoTiffIO`` con el perfil ``project`` (Float64 con los mismos bits), sin escribirlo: el
    hash de una rejilla del proyecto que escribe una operación (RF-006-26, ida y vuelta)."""
    hasher = ContentHasher("raster", declarations=declarations, reader=GEOTIFF.id,
                           normalizer=normalizer)
    feed = hasher.begin_grid(raster_header(raster))
    feed.update(raster.values)
    feed.finish()
    return hasher.digest()


# --- gis.asc@1 ----------------------------------------------------------------------------------


def read_asc(request: ReadRequest) -> Iterator[float]:
    """El generador de ``gis.asc@1``: la rejilla por trozos de ``chunk_bytes`` del cuerpo
    (filas completas al codificador) y, si lo hay, el ``.prj``; el hash es el compuesto."""
    path = _main(request, (PRJ_ROLE,))
    _check_nodata_override(_settings(request, GRID_SETTINGS), request.reader)
    with open(path, "rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        header = asc.read_header(stream, path.name)
        grid = header.grid
        feed = GridEncoder(_grid_header(
            grid.nrows, grid.ncols, header.x0, header.y0, grid.dx, grid.dy,
            point=header.centre, nodata=header.nodata, crs=None,
        ))
        nodata = header.nodata
        replace = nodata is not None and not math.isnan(nodata)
        pending = np.empty(0, np.float64)
        for fraction, _text, values in asc.value_chunks(
            stream, size, header, path.name, chunk_bytes=request.chunk_bytes
        ):
            pending = np.concatenate((pending, values))
            complete = len(pending) - len(pending) % grid.ncols
            if complete:
                rows = pending[:complete].reshape(-1, grid.ncols)
                feed.update(np.where(rows == nodata, np.nan, rows) if replace else rows)
                pending = pending[complete:]
            if fraction < 1.0:
                yield fraction
        parts = {MAIN_ROLE: ("raster", feed.finish())}
    prj = request.files.get(PRJ_ROLE)
    if prj is not None:
        parts[PRJ_ROLE] = ("document", _document_sha256(prj, request.chunk_bytes))
    request.hasher.composite(parts)
    yield 1.0


def _document_sha256(path: Path, chunk_bytes: int) -> str:
    """El hash de datos de un documento (sus bytes)."""
    feed = DocumentEncoder()
    with open(path, "rb", buffering=0) as stream:
        while chunk := stream.read(chunk_bytes):
            feed.update(chunk)
    return feed.finish()


# --- gis.xyz_grid@1 -----------------------------------------------------------------------------


def read_xyz_grid(request: ReadRequest) -> Iterator[float]:
    """El generador de ``gis.xyz_grid@1``: los puntos por trozos de ``chunk_bytes``, la
    malla y sus celdas por bandas de filas."""
    path = _main(request)
    settings = _settings(request, XYZ_SETTINGS)
    _check_nodata_override(settings, request.reader)
    separator = settings.get("separator")
    decimal = settings.get("decimal", ".")
    xyz_grid.check_options(separator, decimal)
    with open(path, "rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        steps = xyz_grid.point_steps(stream, size, path.name, separator=separator,
                                     decimal=decimal, limit=_UNLIMITED,
                                     chunk_bytes=request.chunk_bytes)
        while True:
            try:
                fraction, _text = next(steps)
            except StopIteration as stop:
                points = stop.value
                break
            yield XYZ_READ_SHARE * fraction
    fitted = xyz_grid.fit_grid(points, path.name, _UNLIMITED)
    grid = fitted.grid
    feed = request.hasher.begin_grid(_grid_header(
        grid.nrows, grid.ncols, fitted.x0, fitted.y0, grid.dx, grid.dy,
        point=True, nodata=None, crs=None,
    ))
    step = max(1, request.chunk_bytes // (8 * grid.ncols))
    for top in range(0, grid.nrows, step):
        feed.update(fitted.values[top : top + step])
        if top + step < grid.nrows:
            yield XYZ_READ_SHARE + (1.0 - XYZ_READ_SHARE) * (top + step) / grid.nrows
    feed.finish()
    yield 1.0


# --- gis.points_text@1 --------------------------------------------------------------------------


def _mapping(value: object) -> ColumnMapping:
    """La correspondencia de ``columns`` (papel → índice desde 0, o ``None``)."""
    if not isinstance(value, Mapping):
        raise TypeError(
            f"«columns» es un diccionario {{papel: índice}}, no {type(value).__name__}"
        )
    unknown = sorted(str(key) for key in value if key not in MAPPING_ROLES)
    if unknown:
        raise ValueError(f"papeles desconocidos en «columns»: {unknown} (son "
                         f"{list(MAPPING_ROLES)})")
    missing = [role for role in ("x", "y", "z") if value.get(role) is None]
    if missing:
        raise ValueError(f"a «columns» le faltan los papeles {missing}")
    return ColumnMapping(**{role: value.get(role) for role in MAPPING_ROLES})


def _point_row(
    fields: Sequence[str], mapping: ColumnMapping, decimal: str, expected: int, header: bool
) -> list[object]:
    """Los valores de una fila (:data:`POINT_COLUMNS`), interpretados como en
    ``gis.points.points_from_rows``."""
    values: list[object] = []
    valid = row_has_columns(fields, expected, header)
    for index in (mapping.x, mapping.y, mapping.z):
        number, _problem = _number(_field(fields, index), decimal)
        values.append(number)
        valid = valid and number is not None
    values += [_field(fields, mapping.point_id), _field(fields, mapping.code),
               _field(fields, mapping.line)]
    values.append(None if valid else canonical_json([str(f) for f in fields]).decode("utf-8"))
    return values


def read_points_text(request: ReadRequest) -> Iterator[float]:
    """El generador de ``gis.points_text@1``: la tabla con el lector de tablas (da 0 tras
    leerla) y sus filas por lotes de unos ``chunk_bytes``."""
    path = _main(request)
    settings = _settings(request, POINTS_SETTINGS)
    missing = [key for key in POINTS_REQUIRED if key not in settings]
    if missing:
        raise ValueError(f"faltan ajustes de lectura de «{request.reader}»: {missing}")
    mapping = _mapping(settings["columns"])
    decimal = settings["decimal"]
    if settings.get("line_kind", "hard") not in LINE_KINDS:
        raise ValueError(f"tipo de línea {settings['line_kind']!r} no admitido: "
                         f"{list(LINE_KINDS)}")
    tables = table_reader()
    if tables is None:
        raise RuntimeError(
            f"«{request.reader}» no tiene lector de tablas de texto: se lo da "
            "interop.csv_tables desde bl/ops/gis.py o el trabajo core_content_hash "
            "(use_table_reader)"
        )
    table = tables(path, encoding=settings["encoding"], separator=settings["separator"],
                   header_row=settings.get("header_row", 0))
    headers, expected = check_rows_options(table.columns, mapping, decimal)
    yield 0.0
    feed = request.hasher.begin_rows(POINT_COLUMNS, True)
    rows = table.rows
    total = len(rows)
    step = max(1, request.chunk_bytes // TEXT_ROW_BYTES)
    for start in range(0, total, step):
        feed.update([_point_row(fields, mapping, decimal, expected, bool(headers))
                     for fields in rows[start : start + step]])
        if start + step < total:
            yield (start + step) / total
    feed.finish()
    yield 1.0


# --- gis.gpkg_layer@1 ---------------------------------------------------------------------------


def read_gpkg_layer(request: ReadRequest) -> Iterator[float]:
    """El generador de ``gis.gpkg_layer@1``: el de ``core.gpkg_layer@1`` (D19) sobre la capa
    ``layer``, escribiendo en el hasher de esta petición."""
    settings = _settings(request, GPKG_SETTINGS)
    if "layer" not in settings:
        raise ValueError(f"falta la capa que lee «{request.reader}» («layer»)")
    for key in ("role", "elevation_field"):
        _text_or_none(settings, key, request.reader)
    inner = builtin.GPKG_LAYER.request(
        request.kind, {}, request.files, {"layer": settings["layer"]},
        normalizer=request.normalizer, chunk_bytes=request.chunk_bytes,
    )
    # La capa la lee el lector de core en el hasher de esta petición: el mismo hash de datos,
    # y el ContentDigest con las declaraciones y el lector de gis.
    object.__setattr__(inner, "hasher", request.hasher)
    yield from builtin.read_gpkg_layer(inner)


# --- Los lectores -------------------------------------------------------------------------------

GEOTIFF = ContentReader(
    "gis.geotiff", 1, ("raster",), False, False, _per_second(GEOTIFF_BYTES_PER_S), read_geotiff,
)
"""Un GeoTIFF: las fuentes y las rejillas de ``rasters/``."""
ASC = ContentReader(
    "gis.asc", 1, ("raster",), False, False, _per_second(ASC_BYTES_PER_S), read_asc,
)
"""Un ESRI ASCII Grid con su ``.prj`` (compuesto)."""
XYZ_GRID = ContentReader(
    "gis.xyz_grid", 1, ("raster",), False, False, _per_second(XYZ_BYTES_PER_S), read_xyz_grid,
)
"""Un XYZ en malla regular."""
POINTS_TEXT = ContentReader(
    "gis.points_text", 1, ("table",), False, False, _per_second(TEXT_BYTES_PER_S),
    read_points_text,
)
"""Un texto de puntos (CSV, TXT o XYZ disperso)."""
GPKG_LAYER = ContentReader(
    "gis.gpkg_layer", 1, ("vector",), True, True, builtin.GPKG_LAYER.estimate_s,
    read_gpkg_layer,
)
"""Una capa de un GeoPackage externo (con su ``-wal``)."""
CONTENT_READERS: tuple[ContentReader, ...] = (GEOTIFF, ASC, XYZ_GRID, POINTS_TEXT, GPKG_LAYER)
"""Los lectores de ``gis``, para registrarlos desde ``bl/`` y en el trabajo de hash."""
