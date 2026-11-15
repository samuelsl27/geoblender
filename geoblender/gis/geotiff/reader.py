# SPDX-License-Identifier: GPL-3.0-or-later
"""Lector del GeoTIFF propio (spec 006; plan 006 §5.3.2, §5.3.6 y §5.4 A3; RF-006-04,
RF-006-08, RF-006-09, RF-006-10, RF-006-28; ADR-0020), con biblioteca estándar y numpy.

:func:`read_geotiff` lee el primer IFD de un TIFF o BigTIFF (``II`` o ``MM``), comprueba
**antes de leer los datos** que el fichero es del subconjunto admitido (plan §5.3.6) y lee
sus tiras o teselas una a una (``codecs.decode_block``) sobre un array float64: cada cota
es el valor de la fuente sin redondeo (un Float32 pasa a float64 sin cambio); el sin dato
de ``GDAL_NODATA`` (comparado en el tipo del fichero, como GDAL) y los bloques que no están
en el fichero (desplazamiento y tamaño 0) quedan NaN. Devuelve un
:class:`~..raster.RasterSource` con lo que declara la fuente.

- **Georreferencia**: ``ModelPixelScale`` + un ``ModelTiepoint`` (esquina noroeste =
  punto − (I·dx, −J·dy)) o ``ModelTransformation`` sin giro ni cizalla; con
  *PixelIsPoint* (``GTRasterTypeGeoKey`` = 2), la esquina se desplaza medio paso al
  noroeste (como GDAL) y se anota (``gis.pixel_is_point``).
- **CRS** (RF-006-04): ``ProjectedCSTypeGeoKey`` y ``VerticalCSTypeGeoKey`` del catálogo
  de la 002 → ``declared_crs`` y ``declared_vertical``; sin claves, ``None``; un CRS
  definido por parámetros (32767, o proyectado sin código), ``None`` con una nota
  (``gis.crs_user_defined``): lo declara el usuario, nunca se supone. Un CRS fuera del
  catálogo, geográfico o con unidades que no son metros se rechaza.
- **Rechazos** (RF-006-09), con el fichero, la característica (la etiqueta o la clave), el
  valor encontrado y qué hacer: compresión, bandas, tipo de dato, predictor que no es del
  tipo, giro, escala u offset (``GDAL_METADATA``), unidad de las cotas, más celdas que
  ``gis.import.max_cells`` (de ``gis.params``, leído en cada lectura), falta de
  georreferencia, fichero que no es TIFF, bloque dañado y ráster sin ninguna cota.
- **Entrada intacta** (RF-006-10): el fichero se abre solo para leer y nada se escribe
  junto a él. Avance y cancelación (RF-006-28), antes y después de cada bloque; la
  cancelación es ``jobs.worker_api.JobCancelled`` y no deja nada.

El lector de contenido ``gis.geotiff@1`` (``gis.content``, T40) usa las mismas piezas sin
cargar la rejilla entera: :func:`read_header` (la cabecera comprobada, con la referencia de la
celda del noroeste tal como la da el fichero) y :func:`read_bands` (las celdas por bandas de
filas, con el sin dato y los bloques que faltan en NaN, como :func:`read_geotiff`). La
cubicación de la 011 lee además unas filas sueltas (:func:`read_rows`, solo los bloques que las
tocan) y la rejilla de la cabecera (``GeoTiffHeader.grid``); las entidades de la 015, una ventana de filas
y columnas (:func:`read_window`, solo las teselas que la tocan: una plataforma lee lo que va a calcular y no
la rejilla entera).
"""

from __future__ import annotations

import math
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, NoReturn

import numpy as np

from ...core.errors import ValidationError
from ...core.georef import CrsCatalog, CrsRef, VerticalRef, load_catalog
from ...jobs.worker_api import JobCancelled
from .. import params
from ..grid import Grid
from ..messages import GisError, format_value, render
from ..ports import Cancelled, Progress
from ..raster import RasterSource
from . import geokeys, tiff
from .codecs import COMPRESSIONS, CodecError, compression_name, decode_block

__all__ = ["GeoTiffHeader", "read_bands", "read_geotiff", "read_header", "read_rows", "read_window"]

MAX_CELLS_KEY = "gis.import.max_cells"

# (SampleFormat, BitsPerSample) → tipo de numpy de los que se leen (plan §5.3.6).
_DTYPES = {
    (1, 8): "u1", (2, 8): "i1", (1, 16): "u2", (2, 16): "i2", (1, 32): "u4", (2, 32): "i4",
    (3, 32): "f4", (3, 64): "f8",
}
# Nombres de GDAL de los tipos, para los mensajes y el informe.
_TYPE_NAMES = {
    (1, 8): "Byte", (2, 8): "Int8", (1, 16): "UInt16", (2, 16): "Int16", (1, 32): "UInt32",
    (2, 32): "Int32", (1, 64): "UInt64", (2, 64): "Int64", (3, 16): "Float16",
    (3, 32): "Float32", (3, 64): "Float64", (5, 16): "CInt16", (5, 32): "CInt32",
    (6, 32): "CFloat32", (6, 64): "CFloat64",
}
_METRE_UNITS = frozenset({"m", "metre", "metres", "meter", "meters", "metro", "metros"})
_PREDICTOR_NONE, _PREDICTOR_INTEGER, _PREDICTOR_FLOAT = 1, 2, 3


@dataclass(frozen=True, slots=True)
class _Layout:
    """Cómo están las muestras en el fichero: tamaño, tipo, compresión, predictor y la
    tabla de bloques (tiras de ``block_h`` filas o teselas de ``block_w × block_h``)."""

    width: int
    height: int
    dtype: np.dtype
    type_name: str
    compression: int
    predictor: int
    tiled: bool
    block_w: int
    block_h: int
    offsets: tuple[int, ...]
    counts: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _Declared:
    """Lo que declaran las claves GeoTIFF: CRS, referencia vertical, *PixelIsPoint* y
    las notas para el informe."""

    crs: CrsRef | None = None
    vertical: VerticalRef | None = None
    pixel_is_point: bool = False
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GeoTiffHeader:
    """Lo que declara un GeoTIFF admitido antes de leer sus celdas (:func:`read_header`):
    ``name`` y ``size`` (el nombre del fichero y sus bytes); ``x0`` e ``y0``, la referencia
    de la celda del noroeste **tal como la da el fichero** (su esquina noroeste o, con
    *PixelIsPoint*, su centro); ``dx`` y ``dy``; ``nodata`` (el de ``GDAL_NODATA`` o
    ``None``); ``pixel_is_point``; ``crs`` y ``vertical`` declarados por sus claves (o
    ``None``) y sus ``notes``; ``encoding`` (cómo está guardado, para el informe) y cómo se
    leen sus bloques (``layout``)."""

    name: str
    size: int
    x0: float
    y0: float
    dx: float
    dy: float
    nodata: float | None
    pixel_is_point: bool
    crs: CrsRef | None
    vertical: VerticalRef | None
    notes: tuple[str, ...]
    encoding: str
    layout: _Layout

    @property
    def width(self) -> int:
        """Las columnas de la rejilla (``ImageWidth``)."""
        return self.layout.width

    @property
    def height(self) -> int:
        """Las filas de la rejilla (``ImageLength``)."""
        return self.layout.height

    @property
    def grid(self) -> Grid:
        """La rejilla de sus celdas (la de :func:`read_geotiff`): con *PixelIsPoint*, la
        esquina noroeste medio paso al noroeste del centro que da el fichero."""
        corner_x, corner_y = self.x0, self.y0
        if self.pixel_is_point:
            corner_x -= self.dx / 2.0
            corner_y += self.dy / 2.0
        return Grid(corner_x, corner_y, self.dx, self.dy, self.width, self.height)


def read_header(
    stream: BinaryIO, size: int, name: str, *, catalog: CrsCatalog | None = None
) -> GeoTiffHeader:
    """La cabecera del GeoTIFF abierto en ``stream`` (``size`` bytes; ``name``, para los
    mensajes), comprobada **antes de leer los datos**: ``GisError`` si no se admite
    (RF-006-09; plan §5.3.6). ``catalog``: el catálogo de CRS (por defecto, el de la
    extensión)."""
    try:
        ifd = tiff.read_first_ifd(stream, size)
        layout = _layout(ifd, name)
        x0, y0, dx, dy = _georeference(ifd, name)
        declared = _declared(ifd, name, load_catalog() if catalog is None else catalog)
        _check_metadata(ifd, name)
        nodata = _nodata(ifd, name)
    except tiff.TiffError as error:
        raise GisError(
            "gis.tiff_invalid", obj=name, field="TIFF", file=name, detail=str(error)
        ) from None
    return GeoTiffHeader(
        name=name,
        size=size,
        x0=x0,
        y0=y0,
        dx=dx,
        dy=dy,
        nodata=nodata,
        pixel_is_point=declared.pixel_is_point,
        crs=declared.crs,
        vertical=declared.vertical,
        notes=declared.notes,
        encoding=_encoding(ifd, layout),
        layout=layout,
    )


def read_bands(
    stream: BinaryIO, header: GeoTiffHeader
) -> Iterator[tuple[float, np.ndarray | None]]:
    """Las celdas del GeoTIFF de ``header`` por bandas de filas de norte a sur, en float64
    con NaN en el sin dato y en los bloques que no están en el fichero (como
    :func:`read_geotiff`), sin cargar la rejilla entera. Tras cada bloque da la fracción de
    bloques leídos y la banda que ese bloque termina (una tira, o la fila de teselas al leer
    la última) o ``None``; cada banda es un array nuevo. ``GisError`` si un bloque está
    dañado."""
    layout = header.layout
    match = _nodata_sample(layout.dtype, header.nodata)
    total = len(layout.offsets)
    band: np.ndarray | None = None
    for index, (top, left, rows, cols, part) in enumerate(_blocks(stream, header)):
        if band is None:
            band = np.empty((rows, layout.width), np.float64)
        _place(band[:, left : left + cols], part, match)
        if left + cols < layout.width:
            yield (index + 1) / total, None
        else:
            done, band = band, None
            yield (index + 1) / total, done


def read_rows(stream: BinaryIO, header: GeoTiffHeader, top: int, stop: int) -> np.ndarray:
    """Las filas ``[top, stop)`` del GeoTIFF de ``header`` (0, la del norte) en float64, con
    NaN en el sin dato y en los bloques que no están en el fichero (como :func:`read_bands`),
    leyendo **solo** los bloques que las tocan (cada uno se decodifica entero): un array nuevo
    de ``stop − top`` filas. Unas filas vacías o fuera de la imagen son un error del programa
    (``ValueError``); ``GisError`` si un bloque está dañado."""
    layout = header.layout
    for value in (top, stop):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"las filas se indican con enteros, no {value!r}")
    if not 0 <= top < stop <= layout.height:
        raise ValueError(f"las filas [{top}, {stop}) no están en las {layout.height} de "
                         f"«{header.name}»")
    match = _nodata_sample(layout.dtype, header.nodata)
    band = np.empty((stop - top, layout.width), np.float64)
    for first, left, rows, cols, part in _blocks(stream, header, within=(top, stop)):
        upper, lower = max(first, top), min(first + rows, stop)
        piece = None if part is None else part[upper - first : lower - first]
        _place(band[upper - top : lower - top, left : left + cols], piece, match)
    return band


def read_window(
    stream: BinaryIO, header: GeoTiffHeader, rows: tuple[int, int], cols: tuple[int, int]
) -> np.ndarray:
    """Las celdas de las filas ``[rows[0], rows[1])`` y las columnas ``[cols[0], cols[1])`` del
    GeoTIFF de ``header`` (0, la fila del norte y la columna del oeste) en float64, con NaN en el sin
    dato y en los bloques que no están en el fichero (como :func:`read_rows`), leyendo **solo** los
    bloques —teselas o tiras— que las tocan (cada uno se decodifica entero): un array nuevo de la forma
    de la ventana. Son las mismas celdas que ``read_geotiff(...).values[filas, columnas]``, bit a bit.
    Una ventana vacía o que no está en la imagen es un error del programa (``ValueError``);
    ``GisError`` si un bloque está dañado."""
    layout = header.layout
    for value in (*rows, *cols):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"la ventana se indica con enteros, no {value!r}")
    (top, stop), (left, right) = rows, cols
    if not (0 <= top < stop <= layout.height and 0 <= left < right <= layout.width):
        raise ValueError(f"la ventana de filas [{top}, {stop}) y columnas [{left}, {right}) no está en "
                         f"los {layout.height} × {layout.width} de «{header.name}»")
    match = _nodata_sample(layout.dtype, header.nodata)
    window = np.empty((stop - top, right - left), np.float64)
    for first, start, count, width, part in _blocks(
        stream, header, within=(top, stop), between=(left, right)
    ):
        upper, lower = max(first, top), min(first + count, stop)
        before, after = max(start, left), min(start + width, right)
        piece = (
            None
            if part is None
            else part[upper - first : lower - first, before - start : after - start]
        )
        _place(window[upper - top : lower - top, before - left : after - left], piece, match)
    return window


def read_geotiff(
    path: Path | str,
    *,
    name: str | None = None,
    max_cells: int | None = None,
    catalog: CrsCatalog | None = None,
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> RasterSource:
    """El MDT del GeoTIFF ``path`` en su rejilla de origen (RF-006-08). ``name``: el fichero
    que nombran las notas y los errores (por defecto, el de ``path``; el trabajo de la
    importación lee una copia y nombra el fichero del usuario, T52); ``max_cells``: el
    límite de celdas (por defecto, ``gis.import.max_cells`` de ``gis.params``); ``catalog``:
    el catálogo de CRS (por defecto, el de la extensión). ``GisError`` si el fichero no se
    admite (RF-006-09); ``JobCancelled`` si ``cancelled()`` pide parar."""
    path = Path(path)
    name = name or path.name
    with path.open("rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        header = read_header(stream, size, name, catalog=catalog)
        limit = int(params.default(MAX_CELLS_KEY)) if max_cells is None else int(max_cells)
        cells = header.width * header.height
        if cells > limit:
            raise GisError(
                "gis.raster_too_large",
                obj=name,
                field="ImageWidth × ImageLength",
                value=cells,
                file=name,
                limit=limit,
            )
        values = _read_values(stream, header, progress, cancelled)
    if np.isnan(values).all():
        raise GisError("gis.raster_empty", obj=name, field="valores", file=name)
    notes = header.notes
    if header.pixel_is_point:
        notes = (render("gis.pixel_is_point", file=name), *notes)
    return RasterSource(
        grid=header.grid,
        values=values,
        source_dtype=header.layout.dtype.name,
        nodata_value=header.nodata,
        pixel_is_point=header.pixel_is_point,
        declared_crs=header.crs,
        declared_vertical=header.vertical,
        encoding=header.encoding,
        notes=notes,
    )


# --- Comprobaciones antes de leer ---------------------------------------------------------


def _unsupported(name: str, feature: str, value: object) -> NoReturn:
    raise GisError(
        "gis.tiff_feature_unsupported",
        obj=name,
        field=feature,
        value=value,
        file=name,
        feature=feature,
    )


def _layout(ifd: tiff.Ifd, name: str) -> _Layout:
    width = ifd.number(tiff.IMAGE_WIDTH)
    height = ifd.number(tiff.IMAGE_LENGTH)
    if width is None or height is None:
        raise tiff.TiffError("le falta ImageWidth o ImageLength")
    if width < 1 or height < 1:
        raise tiff.TiffError(f"la imagen tiene {width} × {height} celdas")
    compression = ifd.number(tiff.COMPRESSION, 1)
    if compression not in COMPRESSIONS:
        raise GisError(
            "gis.tiff_compression_unsupported",
            obj=name,
            field="Compression",
            value=compression,
            file=name,
            name=compression_name(compression),
        )
    samples = ifd.number(tiff.SAMPLES_PER_PIXEL, 1)
    if samples != 1:
        raise GisError(
            "gis.raster_bands_unsupported",
            obj=name,
            field="SamplesPerPixel",
            value=samples,
            file=name,
        )
    kind = (ifd.number(tiff.SAMPLE_FORMAT, 1), ifd.number(tiff.BITS_PER_SAMPLE, 1))
    type_name = _TYPE_NAMES.get(kind, f"SampleFormat {kind[0]}, BitsPerSample {kind[1]}")
    if kind not in _DTYPES:
        raise GisError(
            "gis.raster_dtype_unsupported",
            obj=name,
            field="SampleFormat",
            value=type_name,
            file=name,
        )
    dtype = np.dtype(_DTYPES[kind]).newbyteorder(ifd.byteorder)
    fill_order = ifd.number(tiff.FILL_ORDER, 1)
    if fill_order != 1:
        _unsupported(name, "FillOrder", fill_order)
    planar = ifd.number(tiff.PLANAR_CONFIGURATION, 1)
    if planar not in (1, 2):  # con una muestra por píxel, 1 y 2 son lo mismo
        _unsupported(name, "PlanarConfiguration", planar)
    predictor = ifd.number(tiff.PREDICTOR, _PREDICTOR_NONE)
    if not (
        predictor == _PREDICTOR_NONE
        or (predictor == _PREDICTOR_INTEGER and dtype.kind in "iu")
        or (predictor == _PREDICTOR_FLOAT and dtype.kind == "f")
    ):
        _unsupported(name, f"Predictor con datos {type_name}", predictor)
    if tiff.TILE_WIDTH in ifd.tags or tiff.TILE_LENGTH in ifd.tags:
        block_w = ifd.number(tiff.TILE_WIDTH, 0)
        block_h = ifd.number(tiff.TILE_LENGTH, 0)
        if block_w < 1 or block_h < 1:
            raise tiff.TiffError(f"teselas de {block_w} × {block_h} celdas")
        blocks = -(-width // block_w) * -(-height // block_h)
        offsets = _table(ifd, tiff.TILE_OFFSETS, "TileOffsets", blocks)
        counts = _table(ifd, tiff.TILE_BYTE_COUNTS, "TileByteCounts", blocks)
        tiled = True
    else:
        rows = ifd.number(tiff.ROWS_PER_STRIP, height)
        if rows < 1:
            raise tiff.TiffError(f"RowsPerStrip = {rows}")
        block_w, block_h = width, min(rows, height)
        blocks = -(-height // block_h)
        offsets = _table(ifd, tiff.STRIP_OFFSETS, "StripOffsets", blocks)
        counts = _table(ifd, tiff.STRIP_BYTE_COUNTS, "StripByteCounts", blocks)
        tiled = False
    return _Layout(width, height, dtype, type_name, compression, predictor, tiled, block_w,
                   block_h, offsets, counts)


def _table(ifd: tiff.Ifd, tag: int, label: str, expected: int) -> tuple[int, ...]:
    values = ifd.numbers(tag)
    if values is None:
        raise tiff.TiffError(f"le falta {label}")
    if len(values) != expected or not all(isinstance(v, int) for v in values):
        raise tiff.TiffError(
            f"{label} tiene {len(values)} valores y se esperaban {expected} enteros"
        )
    return values  # type: ignore[return-value]


def _shown(values: tuple[float, ...]) -> str:
    """Números como los lee una persona, separados por «; » (``0,8; 0,6``)."""
    return "; ".join(format_value(float(v)) for v in values)


def _georeference(ifd: tiff.Ifd, name: str) -> tuple[float, float, float, float]:
    """Esquina noroeste del píxel (0, 0) según la fuente (sin *PixelIsPoint*), dx y dy."""
    matrix = ifd.numbers(tiff.MODEL_TRANSFORMATION)
    if matrix is not None:
        if len(matrix) != 16:
            raise tiff.TiffError(f"ModelTransformation tiene {len(matrix)} valores y no 16")
        scale_x, shear_x, _, shift_x, shear_y, scale_y, _, shift_y = matrix[:8]
        shown = _shown((shift_x, scale_x, shear_x, shift_y, shear_y, scale_y))
        if shear_x != 0.0 or shear_y != 0.0:
            raise GisError(
                "gis.raster_rotated",
                obj=name,
                field="ModelTransformation",
                value=shown,
                file=name,
            )
        dx, dy = float(scale_x), -float(scale_y)
        if not (_positive(dx) and _positive(dy)):
            _unsupported(name, "ModelTransformation", shown)
        corner_x, corner_y = float(shift_x), float(shift_y)
    else:
        scale = ifd.numbers(tiff.MODEL_PIXEL_SCALE)
        tie = ifd.numbers(tiff.MODEL_TIEPOINT)
        if scale is None or tie is None:
            raise GisError(
                "gis.raster_not_georeferenced",
                obj=name,
                field="ModelPixelScale",
                file=name,
            )
        if len(scale) < 2 or len(tie) < 6 or len(tie) % 6:
            raise tiff.TiffError(
                f"ModelPixelScale ({len(scale)} valores) o ModelTiepoint ({len(tie)}) "
                "incompletos"
            )
        if len(tie) > 6:
            _unsupported(name, "ModelTiepoint (puntos de enlace)", len(tie) // 6)
        dx, dy = float(scale[0]), float(scale[1])
        if not (_positive(dx) and _positive(dy)):
            _unsupported(name, "ModelPixelScale", _shown((dx, dy)))
        pixel_i, pixel_j, _, tie_x, tie_y, _ = (float(v) for v in tie)
        corner_x = tie_x - pixel_i * dx
        corner_y = tie_y + pixel_j * dy
    if not (math.isfinite(corner_x) and math.isfinite(corner_y)):
        raise tiff.TiffError("la georreferencia no es un número finito")
    return corner_x, corner_y, dx, dy


def _positive(step: float) -> bool:
    return math.isfinite(step) and step > 0.0


def _key(keys: dict[int, geokeys.GeoKeyValue], key: int) -> int | None:
    value = keys.get(key)
    if value is not None and not isinstance(value, int):
        raise tiff.TiffError(f"la clave GeoTIFF {key} no es un número entero")
    return value


def _declared(ifd: tiff.Ifd, name: str, catalog: CrsCatalog) -> _Declared:
    directory = ifd.numbers(tiff.GEO_KEY_DIRECTORY)
    if directory is None:
        return _Declared()
    try:
        keys = geokeys.parse_geokeys(
            [int(v) for v in directory],
            doubles=ifd.numbers(tiff.GEO_DOUBLE_PARAMS) or (),
            ascii=ifd.text(tiff.GEO_ASCII_PARAMS) or "",
        )
    except geokeys.GeoKeyError as error:
        raise tiff.TiffError(str(error)) from None
    raster_type = _key(keys, geokeys.GT_RASTER_TYPE)
    if raster_type not in (None, geokeys.RASTER_PIXEL_IS_AREA, geokeys.RASTER_PIXEL_IS_POINT):
        _unsupported(name, "GTRasterTypeGeoKey", raster_type)
    model = _key(keys, geokeys.GT_MODEL_TYPE)
    if model == geokeys.MODEL_GEOGRAPHIC:
        code = _key(keys, geokeys.GEOGRAPHIC_TYPE)
        shown = "geográfico" if code in (None, geokeys.USER_DEFINED) else f"EPSG:{code}"
        raise GisError(
            "gis.raster_crs_unsupported",
            obj=name,
            field="GTModelTypeGeoKey",
            value=shown,
            file=name,
        )
    if model not in (None, geokeys.MODEL_PROJECTED):
        _unsupported(name, "GTModelTypeGeoKey", model)
    units = _key(keys, geokeys.PROJ_LINEAR_UNITS)
    if units not in (None, geokeys.LINEAR_METRE):
        _unsupported(name, "ProjLinearUnitsGeoKey", units)
    vertical_units = _key(keys, geokeys.VERTICAL_UNITS)
    if vertical_units not in (None, geokeys.LINEAR_METRE):
        _unsupported(name, "VerticalUnitsGeoKey", vertical_units)
    notes: tuple[str, ...] = ()
    crs = None
    code = _key(keys, geokeys.PROJECTED_CS_TYPE)
    if code is None or code == geokeys.USER_DEFINED:
        if model == geokeys.MODEL_PROJECTED or code == geokeys.USER_DEFINED:
            notes = (render("gis.crs_user_defined", file=name),)
    else:
        try:
            crs = catalog.horizontal(code)
        except ValidationError:
            raise GisError(
                "gis.raster_crs_unsupported",
                obj=name,
                field="ProjectedCSTypeGeoKey",
                value=f"EPSG:{code}",
                file=name,
            ) from None
    vertical = None
    vertical_code = _key(keys, geokeys.VERTICAL_CS_TYPE)
    if vertical_code not in (None, geokeys.USER_DEFINED):
        try:
            vertical = catalog.vertical(vertical_code)
        except ValidationError:
            raise GisError(
                "gis.raster_vertical_unsupported",
                obj=name,
                field="VerticalCSTypeGeoKey",
                value=f"EPSG:{vertical_code}",
                file=name,
            ) from None
    return _Declared(crs, vertical, raster_type == geokeys.RASTER_PIXEL_IS_POINT, notes)


def _check_metadata(ifd: tiff.Ifd, name: str) -> None:
    """Sin escala ni offset de valores y con las cotas en metros (``GDAL_METADATA``)."""
    text = ifd.text(tiff.GDAL_METADATA)
    if text is None:
        return
    try:
        metadata = geokeys.parse_gdal_metadata(text)
    except ValueError as error:
        raise tiff.TiffError(f"GDAL_METADATA: {error}") from None
    if metadata.scale != 1.0 or metadata.offset != 0.0:
        raise GisError(
            "gis.raster_scale_offset",
            obj=name,
            field="GDAL_METADATA",
            value=_shown((metadata.scale, metadata.offset)),
            file=name,
            scale=metadata.scale,
            offset=metadata.offset,
        )
    if metadata.unit and metadata.unit.casefold() not in _METRE_UNITS:
        _unsupported(name, "UNITTYPE (GDAL_METADATA)", metadata.unit)


def _nodata(ifd: tiff.Ifd, name: str) -> float | None:
    text = ifd.text(tiff.GDAL_NODATA)
    if text is None:
        return None
    try:
        return geokeys.parse_nodata(text)
    except ValueError:
        _unsupported(name, "GDAL_NODATA", text.strip())


# --- Lectura ------------------------------------------------------------------------------


def _nodata_sample(dtype: np.dtype, nodata: float | None) -> np.generic | None:
    """El sin dato en el tipo del fichero (como lo compara GDAL), o ``None`` si no lo hay,
    es NaN (ya es sin dato) o no cabe en un tipo entero."""
    if nodata is None or math.isnan(nodata):
        return None
    if dtype.kind == "f":
        with np.errstate(over="ignore"):
            return dtype.type(nodata)
    info = np.iinfo(dtype)
    if nodata.is_integer() and info.min <= nodata <= info.max:
        return dtype.type(int(nodata))
    return None


def _blocks(
    stream: BinaryIO,
    header: GeoTiffHeader,
    cancelled: Cancelled | None = None,
    within: tuple[int, int] | None = None,
    between: tuple[int, int] | None = None,
) -> Iterator[tuple[int, int, int, int, np.ndarray | None]]:
    """Los bloques (tiras o teselas) en el orden del fichero: su fila y su columna de
    arriba a la izquierda, sus filas y columnas dentro de la imagen y sus muestras en el tipo
    del fichero, recortadas a ellas, o ``None`` si el bloque no está en el fichero
    (``SPARSE_OK`` de GDAL: sin dato). ``cancelled`` se consulta antes de cada bloque;
    ``within`` (filas ``[desde, hasta)``) y ``between`` (columnas ``[desde, hasta)``): solo los
    bloques que las tocan, sin leer los demás."""
    layout = header.layout
    name = header.name
    across = -(-layout.width // layout.block_w)
    total = len(layout.offsets)
    for index, (offset, count) in enumerate(zip(layout.offsets, layout.counts, strict=True)):
        if cancelled is not None and cancelled():
            raise JobCancelled(f"Cancelado al leer «{name}» en el bloque {index + 1} de {total}")
        if layout.tiled:
            row, col = divmod(index, across)
            top, left, coded = row * layout.block_h, col * layout.block_w, layout.block_h
        else:
            top, left = index * layout.block_h, 0
            coded = min(layout.block_h, layout.height - top)
        rows = min(layout.block_h, layout.height - top)
        if within is not None and (top + rows <= within[0] or top >= within[1]):
            continue
        cols = min(layout.block_w, layout.width - left)
        if between is not None and (left + cols <= between[0] or left >= between[1]):
            continue
        part = None
        if count != 0:
            samples = _block(stream, header.size, layout, offset, count, coded, name, index,
                             total)
            part = samples[:rows, :cols]
        yield top, left, rows, cols, part


def _place(target: np.ndarray, part: np.ndarray | None, match: np.generic | None) -> None:
    """Copia las muestras de un bloque en ``target`` (float64) con el sin dato en NaN; un
    bloque que no está en el fichero, todo NaN."""
    if part is None:
        target[...] = np.nan
        return
    target[...] = part
    if match is not None:
        target[part == match] = np.nan


def _read_values(
    stream: BinaryIO,
    header: GeoTiffHeader,
    progress: Progress | None,
    cancelled: Cancelled | None,
) -> np.ndarray:
    layout = header.layout
    match = _nodata_sample(layout.dtype, header.nodata)
    values = np.empty((layout.height, layout.width), np.float64)
    total = len(layout.offsets)
    for index, (top, left, rows, cols, part) in enumerate(_blocks(stream, header, cancelled)):
        _place(values[top : top + rows, left : left + cols], part, match)
        if progress is not None:
            progress((index + 1) / total,
                     f"Leyendo «{header.name}»: bloque {index + 1} de {total}")
    return values


def _block(
    stream: BinaryIO,
    size: int,
    layout: _Layout,
    offset: int,
    count: int,
    rows: int,
    name: str,
    index: int,
    total: int,
) -> np.ndarray:
    """Las muestras de un bloque, en el orden nativo; ``gis.tiff_block_corrupt`` si se
    sale del fichero o no se puede decodificar."""
    if offset + count > size:
        detail = (f"el fichero termina antes que él: byte {offset} + {count} y el fichero "
                  f"tiene {size} bytes")
        raise _corrupt(name, index, total, detail)
    stream.seek(offset)
    data = stream.read(count)
    try:
        return decode_block(
            data,
            compression=layout.compression,
            predictor=layout.predictor,
            dtype=layout.dtype,
            width=layout.block_w,
            rows=rows,
        )
    except CodecError as error:
        raise _corrupt(name, index, total, str(error)) from None


def _corrupt(name: str, index: int, total: int, detail: str) -> GisError:
    return GisError(
        "gis.tiff_block_corrupt",
        obj=name,
        field="bloque",
        value=index + 1,
        file=name,
        block=index + 1,
        blocks=total,
        detail=detail,
    )


def _encoding(ifd: tiff.Ifd, layout: _Layout) -> str:
    """Cómo está guardado el fichero, para el informe (``GeoTIFF «II», Float32,
    compresión LZW, predictor 3, teselas de 16 × 16``)."""
    kind = "GeoTIFF (BigTIFF)" if ifd.bigtiff else "GeoTIFF"
    order = "II" if ifd.byteorder == "<" else "MM"
    parts = [f"{kind} «{order}»", layout.type_name]
    if layout.compression == 1:
        parts.append("sin compresión")
    else:
        parts.append(f"compresión {compression_name(layout.compression)}")
    if layout.predictor != _PREDICTOR_NONE:
        parts.append(f"predictor {layout.predictor}")
    if layout.tiled:
        parts.append(f"teselas de {layout.block_w} × {layout.block_h}")
    else:
        parts.append(f"tiras de {layout.block_h} filas")
    return ", ".join(parts)
