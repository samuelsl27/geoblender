# SPDX-License-Identifier: GPL-3.0-or-later
"""Escritor del GeoTIFF propio (spec 006; plan 006 §5.2.1 y §5.4 A4; RF-006-08, RF-006-24,
RF-006-28; ADR-0020), con biblioteca estándar y numpy.

:func:`write_geotiff` escribe un :class:`~..raster.Raster` con uno de los dos perfiles de
``gis.ports.WriteProfile`` (plan §5.2.1):

- ``project`` (``rasters/gis_*.tif``): Float64 y sin dato NaN (``GDAL_NODATA`` = ``nan``);
  cada celda con **los mismos bits** que el ráster (RF-006-08).
- ``deliverable`` (``exports/…``): Float32 y sin dato −9999 (``GDAL_NODATA`` = ``-9999``):
  cada cota es el ``numpy.float32`` de su valor y cada celda sin dato (NaN o ±∞), −9999
  (RF-006-24). Una cota válida que en float32 es −9999 (``gis.export_nodata_collision``) o
  que no cabe en float32 (``gis.export_value_out_of_range``) se rechaza antes de escribir.

Los dos: banda única, «II», teselas de :data:`TILE_SIZE` × :data:`TILE_SIZE` por filas (las
del borde, rellenas con el sin dato), predictor 3 y DEFLATE de nivel 6
(``codecs.encode_block``); ``ModelPixelScale`` (dx, dy, 0) y ``ModelTiepoint`` (0, 0, 0,
oeste, norte, 0) con los float64 de la rejilla; claves 1024 = 1 (proyectado), 1025 = 1
(*PixelIsArea*), 3072 = EPSG del CRS y 4096 = EPSG vertical, si la referencia vertical lo
tiene (una referencia local no se escribe: el proyecto la guarda con el dataset). Sin
``DateTime`` ni ``Software``: el mismo ráster da los mismos bytes.

Disposición: cabecera (:data:`DATA_OFFSET` bytes reservados, los de una de BigTIFF), las
teselas comprimidas una tras otra y, al final, el IFD con sus valores. Los desplazamientos se
calculan en dos pasadas: primero las teselas y después el IFD; así se sabe el tamaño total
antes de elegir el formato: TIFF clásico hasta :data:`BIGTIFF_THRESHOLD` bytes (4 GiB −
64 KiB) y BigTIFF por encima (el umbral se puede inyectar en las pruebas).

Escritura atómica: en un temporal, ``fsync`` y ``os.replace``. El temporal es
``<destino>.tmp`` (:func:`temporary_path`) o el que da quien llama (``temporary``): en el
proyecto, ``gis.store`` da ``<fichero>.tmp-<sesión>``, el patrón de restos de la 008 (plan
§5.6.5), y con ``replace=False`` lo deja escrito para ponerlo en su sitio él mismo al confirmar
la operación. Mientras tanto el destino anterior sigue intacto; si algo falla o se cancela
(``jobs.worker_api.JobCancelled``, comprobado antes de cada tesela, con el avance después de
cada una), el temporal se borra. Si Windows no deja sustituir el destino porque otro programa
lo tiene abierto (QGIS), ``gis.raster_target_locked``: es el error, sin fichero a medias y con
el anterior intacto, también en ``rasters/`` (sin ``<nombre>__<hash8>.tif``, D20). Cualquier
otro fallo del disco es ``gis.raster_write_failed``.

:func:`write_steps` (spec 011, T12; plan 011 T4) es la misma escritura por pasos, una tesela
por paso, para el hilo de Blender (RNF-011-04): los mismos bytes, el mismo temporal y el mismo
renombrado; cerrar el generador a mitad borra el temporal. :func:`write_geotiff` recorre esos
pasos de una vez, con su avance y su cancelación.
"""

from __future__ import annotations

import math
import os
from collections.abc import Generator, Iterator
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import numpy as np

from ...core.georef import VerticalRef
from ...core.paths import check_path_length
from ...jobs.worker_api import JobCancelled
from ..messages import GisError
from ..ports import Cancelled, Progress, WriteProfile
from ..raster import Raster
from . import geokeys, tiff
from .codecs import COMPRESSION_DEFLATE, PREDICTOR_FLOATING_POINT, encode_block

__all__ = [
    "BIGTIFF_THRESHOLD",
    "DATA_OFFSET",
    "DELIVERABLE_NODATA",
    "TEMPORARY_SUFFIX",
    "TILE_SIZE",
    "check_bigtiff_threshold",
    "target_locked",
    "temporary_path",
    "write_failed",
    "write_geotiff",
    "write_steps",
]

TILE_SIZE = 256
"""Lado de las teselas (plan §5.2.1)."""

BIGTIFF_THRESHOLD = 4 * 2**30 - 64 * 2**10
"""Tamaño total por encima del cual se escribe BigTIFF (4 GiB − 64 KiB; plan §5.4 A4)."""

DELIVERABLE_NODATA = -9999.0
"""Sin dato de los GeoTIFF entregables (convenio de IMGA, TOP-03; RF-006-24)."""

DATA_OFFSET = tiff.BIGTIFF_HEADER_SIZE
"""Byte en que empiezan las teselas: lo que ocupa la cabecera de un BigTIFF; en un TIFF
clásico, los 8 bytes tras su cabecera quedan a cero."""

TEMPORARY_SUFFIX = ".tmp"

_PIXEL_IS_AREA = geokeys.RASTER_PIXEL_IS_AREA
_PHOTOMETRIC_MIN_IS_BLACK = 1
_PLANAR_CONTIGUOUS = 1
_SAMPLE_FORMAT_FLOAT = 3
_FIELD_VALUE = "cota"
_FIELD_TARGET = "destino"


@dataclass(frozen=True, slots=True)
class _Profile:
    """Tipo de las muestras en el fichero y su sin dato."""

    dtype: np.dtype
    nodata: float

    @property
    def bits(self) -> int:
        return self.dtype.itemsize * 8


_PROFILES = {
    WriteProfile.PROJECT: _Profile(np.dtype(np.float64), math.nan),
    WriteProfile.DELIVERABLE: _Profile(np.dtype(np.float32), DELIVERABLE_NODATA),
}


def temporary_path(path: Path | str) -> Path:
    """El temporal de ``path`` mientras se escribe: ``<destino>.tmp``, en su carpeta."""
    path = Path(path)
    return path.with_name(path.name + TEMPORARY_SUFFIX)


def check_bigtiff_threshold(threshold: object) -> int:
    """``threshold`` si es un umbral válido para elegir BigTIFF (un entero de 0 a
    :data:`BIGTIFF_THRESHOLD`: por encima, un TIFF clásico no podría apuntar a todo el
    fichero); si no, ``TypeError`` o ``ValueError`` (un error del programa)."""
    if isinstance(threshold, bool) or not isinstance(threshold, int):
        raise TypeError(f"el umbral de BigTIFF es un número entero de bytes, no {threshold!r}")
    if not 0 <= threshold <= BIGTIFF_THRESHOLD:
        raise ValueError(
            f"el umbral de BigTIFF ({threshold} bytes) debe estar entre 0 y "
            f"{BIGTIFF_THRESHOLD}"
        )
    return threshold


def write_geotiff(
    raster: Raster,
    path: Path | str,
    *,
    profile: WriteProfile | str,
    temporary: Path | str | None = None,
    replace: bool = True,
    bigtiff_threshold: int = BIGTIFF_THRESHOLD,
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> Path:
    """Escribe ``raster`` en ``path`` con ``profile`` (``WriteProfile`` o su texto), con
    temporal y renombrado: nunca un fichero a medias. ``temporary``: el temporal (por defecto,
    :func:`temporary_path`); con ``replace=False`` el fichero queda escrito entero en él y
    ``path`` no se toca (lo pone en su sitio quien llama). Devuelve lo escrito: ``path`` o,
    sin ``replace``, el temporal. ``GisError`` si una cota no se puede entregar en float32, si
    el destino está bloqueado o si falla el disco; ``JobCancelled`` si ``cancelled()`` pide
    parar (se pregunta antes de cada tesela). ``raster`` no se modifica. Recorre de una vez
    los pasos de :func:`write_steps`."""
    steps = write_steps(raster, path, profile=profile, temporary=temporary, replace=replace,
                        bigtiff_threshold=bigtiff_threshold)
    name = Path(path).name
    total = _tile_count(raster, TILE_SIZE)
    index = 0
    with closing(steps):  # cancelar o fallar a mitad cierran los pasos: sin temporal
        while True:
            if index < total and cancelled is not None and cancelled():
                raise JobCancelled(
                    f"Cancelado al escribir «{name}» en la tesela {index + 1} de {total}"
                )
            try:
                fraction = next(steps)
            except StopIteration as stop:
                return stop.value
            index += 1
            if progress is not None:
                progress(fraction, f"Escribiendo «{name}»: tesela {index} de {total}")


def write_steps(
    raster: Raster,
    path: Path | str,
    *,
    profile: WriteProfile | str,
    temporary: Path | str | None = None,
    replace: bool = True,
    bigtiff_threshold: int = BIGTIFF_THRESHOLD,
) -> Generator[float, None, Path]:
    """:func:`write_geotiff` por pasos (plan 011 T4 y A10; RNF-011-04): **los mismos bytes**,
    el mismo temporal y el mismo renombrado, con **un paso por tesela**. Cada ``next()``
    comprime y escribe una tesela en el temporal y da el avance (teselas escritas / total,
    hasta 1); la llamada que termina el generador escribe el IFD, fuerza a disco, pone el
    fichero en su sitio (con ``replace``) y devuelve lo escrito en ``StopIteration.value``
    (``path`` o, sin ``replace``, el temporal): ``escrito = yield from write_steps(...)``.

    Lo que no se puede escribir (otro objeto, otro perfil, el destino como temporal, una cota
    que no se puede entregar en float32) se rechaza **al llamar**, antes de ningún paso y sin
    crear nada. Cerrar el generador a mitad (``close()``: Esc) o un fallo en un paso borran el
    temporal y dejan el destino anterior intacto; el destino bloqueado es
    ``gis.raster_target_locked`` y un fallo del disco, ``gis.raster_write_failed``, como en
    :func:`write_geotiff`. El lado de las teselas es el de :data:`TILE_SIZE` al llamar.
    ``raster`` no se modifica, y no debe cambiar mientras duran los pasos."""
    if not isinstance(raster, Raster):
        raise TypeError(f"se escribe un Raster, no {type(raster).__name__}")
    if not isinstance(replace, bool):
        raise TypeError(f"«replace» es verdadero o falso, no {replace!r}")
    chosen = _PROFILES[WriteProfile(profile)]
    threshold = check_bigtiff_threshold(bigtiff_threshold)
    path = Path(path)
    name = path.name
    if chosen.dtype == np.float32:
        _check_deliverable(raster.values, name)
    temporary = temporary_path(path) if temporary is None else Path(temporary)
    if temporary == path:
        raise ValueError(f"el temporal de «{name}» no puede ser el propio destino")
    check_path_length(temporary, obj=name)
    return _steps(raster, path, temporary, replace, _Layout(chosen, threshold, TILE_SIZE))


def target_locked(name: str) -> GisError:
    """``gis.raster_target_locked`` de ``name``: otro programa tiene abierto el destino (D20:
    es el error, sin escribir nada; lo usa también ``gis.store``)."""
    return GisError("gis.raster_target_locked", obj=name, field=_FIELD_TARGET, value=name,
                    file=name)


def write_failed(name: str, error: OSError) -> GisError:
    """``gis.raster_write_failed`` de ``name`` con el motivo del sistema (``error``)."""
    return GisError(
        "gis.raster_write_failed",
        obj=name,
        field=_FIELD_TARGET,
        value=name,
        file=name,
        detail=error.strerror or str(error),
    )


def _discard(temporary: Path) -> None:
    try:
        temporary.unlink(missing_ok=True)
    except OSError:
        pass


# --- Comprobación del entregable -----------------------------------------------------------


def _check_deliverable(values: np.ndarray, name: str) -> None:
    """Rechaza, antes de escribir nada, las cotas válidas (finitas) que en float32 son el
    sin dato −9999 o no caben en float32. Por bandas de :data:`TILE_SIZE` filas."""
    nodata = np.float32(DELIVERABLE_NODATA)
    clashes: list[tuple[int, int, float]] = []
    overflows: list[tuple[int, int, float]] = []
    clash_count = overflow_count = 0
    for top in range(0, values.shape[0], TILE_SIZE):
        band = values[top : top + TILE_SIZE]
        finite = np.isfinite(band)
        with np.errstate(over="ignore"):
            single = band.astype(np.float32)
        clash = finite & (single == nodata)
        overflow = finite & ~np.isfinite(single)
        for mask, found in ((clash, clashes), (overflow, overflows)):
            if not found and mask.any():
                row, col = np.argwhere(mask)[0]
                found.append((top + int(row), int(col), float(band[row, col])))
        clash_count += int(clash.sum())
        overflow_count += int(overflow.sum())
    for code, found, count in (
        ("gis.export_nodata_collision", clashes, clash_count),
        ("gis.export_value_out_of_range", overflows, overflow_count),
    ):
        if found:
            row, col, value = found[0]
            raise GisError(
                code, obj=name, field=_FIELD_VALUE, value=value, file=name, count=count,
                row=row + 1, column=col + 1,
            )


# --- Escritura ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Layout:
    """Lo que fija los bytes además del ráster: el perfil, el umbral de BigTIFF y el lado de
    las teselas (el de :data:`TILE_SIZE` al empezar)."""

    profile: _Profile
    threshold: int
    tile: int


def _tile_count(raster: Raster, size: int) -> int:
    grid = raster.grid
    return -(-grid.nrows // size) * -(-grid.ncols // size)


def _tiles(values: np.ndarray, profile: _Profile, size: int) -> Iterator[np.ndarray]:
    """Las teselas de ``size`` × ``size`` por filas (TIFF 6.0), en el tipo del perfil, con el
    sin dato del perfil en las celdas sin dato (entregable) y en el relleno del borde."""
    rows, cols = values.shape
    for top in range(0, rows, size):
        for left in range(0, cols, size):
            part = values[top : top + size, left : left + size]
            tile = np.full((size, size), profile.nodata, profile.dtype)
            height, width = part.shape
            if profile.dtype == np.float64:
                tile[:height, :width] = part  # los mismos bits, NaN con su carga incluido
            else:
                single = part.astype(np.float32)
                single[~np.isfinite(part)] = profile.nodata
                tile[:height, :width] = single
            yield tile


def _steps(
    raster: Raster,
    path: Path,
    temporary: Path,
    replace: bool,
    layout: _Layout,
) -> Generator[float, None, Path]:
    """Los pasos de :func:`write_steps`, ya comprobado lo que se escribe: el temporal se crea
    en el primero."""
    name = path.name
    try:
        with temporary.open("wb") as stream:
            yield from _write(stream, raster, layout)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException as error:  # también GeneratorExit: cerrar los pasos a mitad
        _discard(temporary)
        if isinstance(error, OSError):
            raise write_failed(name, error) from None
        raise
    if not replace:
        return temporary
    try:
        os.replace(temporary, path)
    except OSError as error:
        _discard(temporary)
        if isinstance(error, PermissionError):  # Windows: otro programa lo tiene abierto
            raise target_locked(name) from None
        raise write_failed(name, error) from None
    return path


def _write(stream: BinaryIO, raster: Raster, layout: _Layout) -> Iterator[float]:
    """Cabecera reservada, las teselas comprimidas una tras otra (un paso y su avance por
    tesela) y, tras la última, el IFD con sus valores y la cabecera definitiva."""
    profile = layout.profile
    total = _tile_count(raster, layout.tile)
    stream.write(bytes(DATA_OFFSET))
    position = DATA_OFFSET
    offsets: list[int] = []
    counts: list[int] = []
    for tile in _tiles(raster.values, profile, layout.tile):
        data = encode_block(tile, predictor=PREDICTOR_FLOATING_POINT)
        stream.write(data)
        offsets.append(position)
        counts.append(len(data))
        position += len(data)
        yield len(offsets) / total
    ifd_offset = position + position % 2
    stream.write(bytes(ifd_offset - position))
    ifd = tiff.encode_ifd(_entries(raster, layout, offsets, counts, False), ifd_offset,
                          bigtiff=False)
    bigtiff = ifd_offset + len(ifd) > layout.threshold
    if bigtiff:
        ifd = tiff.encode_ifd(_entries(raster, layout, offsets, counts, True), ifd_offset,
                              bigtiff=True)
    stream.write(ifd)
    stream.seek(0)
    stream.write(tiff.encode_header(ifd_offset, bigtiff=bigtiff))


def _entries(
    raster: Raster,
    layout: _Layout,
    offsets: list[int],
    counts: list[int],
    bigtiff: bool,
) -> list[tiff.IfdEntry]:
    grid = raster.grid
    profile = layout.profile
    pointer = tiff.LONG8 if bigtiff else tiff.LONG
    return [
        (tiff.IMAGE_WIDTH, tiff.LONG, [grid.ncols]),
        (tiff.IMAGE_LENGTH, tiff.LONG, [grid.nrows]),
        (tiff.BITS_PER_SAMPLE, tiff.SHORT, [profile.bits]),
        (tiff.COMPRESSION, tiff.SHORT, [COMPRESSION_DEFLATE]),
        (tiff.PHOTOMETRIC_INTERPRETATION, tiff.SHORT, [_PHOTOMETRIC_MIN_IS_BLACK]),
        (tiff.SAMPLES_PER_PIXEL, tiff.SHORT, [1]),
        (tiff.PLANAR_CONFIGURATION, tiff.SHORT, [_PLANAR_CONTIGUOUS]),
        (tiff.PREDICTOR, tiff.SHORT, [PREDICTOR_FLOATING_POINT]),
        (tiff.TILE_WIDTH, tiff.SHORT, [layout.tile]),
        (tiff.TILE_LENGTH, tiff.SHORT, [layout.tile]),
        (tiff.TILE_OFFSETS, pointer, offsets),
        (tiff.TILE_BYTE_COUNTS, pointer, counts),
        (tiff.SAMPLE_FORMAT, tiff.SHORT, [_SAMPLE_FORMAT_FLOAT]),
        (tiff.MODEL_PIXEL_SCALE, tiff.DOUBLE, [grid.dx, grid.dy, 0.0]),
        (tiff.MODEL_TIEPOINT, tiff.DOUBLE, [0.0, 0.0, 0.0, grid.west, grid.north, 0.0]),
        (tiff.GEO_KEY_DIRECTORY, tiff.SHORT, geokeys.encode_geokeys(_keys(raster))),
        (tiff.GDAL_NODATA, tiff.ASCII, geokeys.format_nodata(profile.nodata)),
    ]


def _keys(raster: Raster) -> dict[int, int]:
    keys = {
        geokeys.GT_MODEL_TYPE: geokeys.MODEL_PROJECTED,
        geokeys.GT_RASTER_TYPE: _PIXEL_IS_AREA,
        geokeys.PROJECTED_CS_TYPE: raster.crs.epsg,
    }
    vertical: VerticalRef = raster.vertical
    if vertical.kind == "epsg" and vertical.epsg is not None:
        keys[geokeys.VERTICAL_CS_TYPE] = vertical.epsg
    return keys
