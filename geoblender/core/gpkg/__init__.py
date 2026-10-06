# SPDX-License-Identifier: GPL-3.0-or-later
"""GeoPackage del proyecto sin GDAL (spec 002; ADR-0006; plan 002 §5.1 y §5.2).

``project.gpkg`` se escribe con ``sqlite3`` de la biblioteca estándar y geometría propia
(cabecera ``GP`` + WKB ISO): QGIS 4.2 y GDAL 3.13 lo abren tal cual. Siempre en diario
clásico, nunca en WAL (ARQ-17): los proyectos de IMGA viven en una unidad de red.
"""

from .connection import BUSY_TIMEOUT_MS, GpkgConnection, sqlite_uri
from .header import SqliteHeader, read_header
from .wal import WalOutcome, WalRecovery, private_copy, to_classic_journal
from .wkb import Geometry, decode_geometry, encode_geometry

__all__ = [
    "BUSY_TIMEOUT_MS",
    "Geometry",
    "GpkgConnection",
    "SqliteHeader",
    "WalOutcome",
    "WalRecovery",
    "decode_geometry",
    "encode_geometry",
    "private_copy",
    "read_header",
    "sqlite_uri",
    "to_classic_journal",
]
