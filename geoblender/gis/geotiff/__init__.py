# SPDX-License-Identifier: GPL-3.0-or-later
"""GeoTIFF propio, con biblioteca estándar y numpy (spec 006; plan 006 §5.1, §5.2.1, §5.3.6
y §5.4 A3 y A4; ADR-0020): sin GDAL, tifffile ni otras dependencias.

- ``codecs``: LZW, PackBits, DEFLATE (zlib) y predictores 2 y 3, por tira o tesela.

Las tareas siguientes de la 006 añaden la cabecera y los IFD (``tiff``), las claves GeoTIFF
(``geokeys``), el lector y el escritor (``reader``, ``writer``) y ``GeoTiffIO``, que
implementa el puerto ``gis.ports.RasterIO`` y se reexporta aquí.
"""
