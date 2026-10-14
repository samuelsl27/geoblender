# SPDX-License-Identifier: GPL-3.0-or-later
"""GeoTIFF propio, con biblioteca estándar y numpy (spec 006; plan 006 §5.1, §5.2.1, §5.3.6
y §5.4 A3 y A4; ADR-0020): sin GDAL, tifffile ni otras dependencias.

- ``codecs``: LZW, PackBits, DEFLATE (zlib) y predictores 2 y 3, por tira o tesela.
- ``tiff``: cabecera TIFF y BigTIFF, primer IFD y sus etiquetas; para escribir, la cabecera
  y un IFD «II».
- ``geokeys``: claves GeoTIFF, ``GDAL_NODATA`` y ``GDAL_METADATA``.
- ``reader``: :func:`read_geotiff`, el MDT de un GeoTIFF en su rejilla de origen
  (``gis.raster.RasterSource``), con los rechazos de RF-006-09.
- ``writer``: :func:`write_geotiff`, un ``gis.raster.Raster`` con el perfil ``project``
  (Float64, NaN) o ``deliverable`` (Float32, −9999), con temporal y renombrado.
- :class:`GeoTiffIO`: implementa el puerto ``gis.ports.RasterIO`` con los dos.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..ports import Cancelled, Progress, WriteProfile
from ..raster import Raster, RasterSource
from .reader import read_geotiff
from .writer import BIGTIFF_THRESHOLD, check_bigtiff_threshold, write_geotiff

__all__ = ["GeoTiffIO", "read_geotiff", "write_geotiff"]


@dataclass(frozen=True, slots=True)
class GeoTiffIO:
    """Lectura y escritura de GeoTIFF de una banda (puerto ``gis.ports.RasterIO``;
    RF-006-08, RF-006-24). ``bigtiff_threshold``: tamaño total por encima del cual se
    escribe BigTIFF (por defecto, 4 GiB − 64 KiB; se inyecta en las pruebas)."""

    bigtiff_threshold: int = BIGTIFF_THRESHOLD

    def __post_init__(self) -> None:
        check_bigtiff_threshold(self.bigtiff_threshold)

    def read(
        self,
        path: Path,
        *,
        progress: Progress | None = None,
        cancelled: Cancelled | None = None,
    ) -> RasterSource:
        """El MDT de ``path`` en su rejilla de origen (``read_geotiff``)."""
        return read_geotiff(path, progress=progress, cancelled=cancelled)

    def write(
        self,
        raster: Raster,
        path: Path,
        *,
        profile: WriteProfile | str,
        progress: Progress | None = None,
        cancelled: Cancelled | None = None,
    ) -> None:
        """Escribe ``raster`` en ``path`` con ``profile`` (``write_geotiff``), con temporal
        y renombrado: nunca un fichero a medias."""
        write_geotiff(
            raster,
            path,
            profile=profile,
            bigtiff_threshold=self.bigtiff_threshold,
            progress=progress,
            cancelled=cancelled,
        )
