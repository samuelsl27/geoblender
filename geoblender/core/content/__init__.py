# SPDX-License-Identifier: GPL-3.0-or-later
"""Hash de contenido normalizado por tipo de dato (spec 008; RF-008-08; ADR-0024; plan 008
§5.3.1 y §5.4.1).

Cada entrada y cada dato tienen dos hashes: el **de datos** (``data_sha256``), de la forma
normalizada de lo que se lee, y el **de contenido** (``content_sha256``), que añade su tipo, su
normalizador y lo declarado al importar (CRS horizontal y vertical, convenios). Abrir y
guardar un GeoPackage en QGIS, recomprimir o volver a teselar una rejilla o leerla en float32
o en float64, renumerar las entidades de una capa o escribir su WKB en otro orden de bytes no
los cambia; una cota, un vértice, un píxel, un atributo, una fila, el sin dato, el tipo de
celda o el CRS declarado, sí, sin tolerancia (D-8). Detalle en :mod:`.encoder` y, la
geometría, en :mod:`.wkb`. Python puro y numpy (ADR-0004).
"""

from .encoder import (
    CELL_TYPES,
    FIELD_TYPES,
    GRID_CLASSES,
    GRID_KEYS,
    KINDS,
    MESH_META_KEYS,
    NORMALIZER,
    NORMALIZERS,
    ContentDigest,
    ContentHasher,
    DocumentEncoder,
    FeatureEncoder,
    GridEncoder,
    PointEncoder,
    RowEncoder,
    composite_sha256,
    content_sha256,
    mesh_sha256,
)
from .wkb import DIMS, GEOMETRY_TYPES, canonical_wkb

__all__ = [
    "CELL_TYPES",
    "DIMS",
    "FIELD_TYPES",
    "GEOMETRY_TYPES",
    "GRID_CLASSES",
    "GRID_KEYS",
    "KINDS",
    "MESH_META_KEYS",
    "NORMALIZER",
    "NORMALIZERS",
    "ContentDigest",
    "ContentHasher",
    "DocumentEncoder",
    "FeatureEncoder",
    "GridEncoder",
    "PointEncoder",
    "RowEncoder",
    "canonical_wkb",
    "composite_sha256",
    "content_sha256",
    "mesh_sha256",
]
