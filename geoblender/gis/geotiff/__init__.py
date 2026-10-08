# SPDX-License-Identifier: GPL-3.0-or-later
"""GeoTIFF propio, con biblioteca estándar y numpy (spec 006; plan 006 §5.1, §5.2.1, §5.3.6
y §5.4 A3 y A4; ADR-0020): sin GDAL, tifffile ni otras dependencias.

- ``codecs``: LZW, PackBits, DEFLATE (zlib) y predictores 2 y 3, por tira o tesela.
- ``tiff``: cabecera TIFF y BigTIFF, primer IFD y sus etiquetas.
- ``geokeys``: claves GeoTIFF, ``GDAL_NODATA`` y ``GDAL_METADATA``.
- ``reader``: :func:`read_geotiff`, el MDT de un GeoTIFF en su rejilla de origen
  (``gis.raster.RasterSource``), con los rechazos de RF-006-09.

La tarea siguiente de la 006 añade el escritor (``writer``) y ``GeoTiffIO``, que
implementa el puerto ``gis.ports.RasterIO`` y se reexporta aquí.
"""

from .reader import read_geotiff

__all__ = ["read_geotiff"]
