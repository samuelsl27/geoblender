# SPDX-License-Identifier: GPL-3.0-or-later
"""Claves GeoTIFF y etiquetas de GDAL (spec 006; plan 006 §5.1 y §5.3.6; RF-006-04,
RF-006-08, RF-006-09; ADR-0020), con biblioteca estándar.

- :func:`parse_geokeys`: el ``GeoKeyDirectory`` (etiqueta 34735) con ``GeoDoubleParams``
  (34736) y ``GeoAsciiParams`` (34737) → clave → valor (``int`` si va en el propio
  directorio; tupla de ``float`` o de ``int``, o texto sin el «|» final, si va en otra
  etiqueta). Las claves que lee Geoblender (plan §5.3.6): ``GTModelTypeGeoKey`` (1024; 1 =
  proyectado), ``GTRasterTypeGeoKey`` (1025; 1 = *PixelIsArea*, 2 = *PixelIsPoint*),
  ``ProjectedCSTypeGeoKey`` (3072; código EPSG, 32767 = definido por el usuario),
  ``ProjLinearUnitsGeoKey`` (3076; 9001 = metro), ``VerticalCSTypeGeoKey`` (4096) y
  ``VerticalUnitsGeoKey`` (4099); las demás (citas, CRS geográfico base…) se ignoran.
- :func:`parse_nodata`: el sin dato de ``GDAL_NODATA`` (42113, texto: ``"-9999"``,
  ``"nan"``).
- :func:`parse_gdal_metadata`: escala, offset y unidad de las cotas de la banda 1 en
  ``GDAL_METADATA`` (42112, XML), leídos con expresiones regulares: sin analizador XML, sin
  entidades que expandir.

Un directorio mal formado (corto, de otra versión o que apunta fuera de su etiqueta) es
:class:`GeoKeyError` (``ValueError``), y un sin dato que no es un número, ``ValueError``;
el lector los convierte en errores para el usuario con el fichero.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

__all__ = [
    "GEOGRAPHIC_TYPE",
    "GT_MODEL_TYPE",
    "GT_RASTER_TYPE",
    "LINEAR_METRE",
    "MODEL_GEOGRAPHIC",
    "MODEL_PROJECTED",
    "PROJECTED_CS_TYPE",
    "PROJ_LINEAR_UNITS",
    "RASTER_PIXEL_IS_AREA",
    "RASTER_PIXEL_IS_POINT",
    "USER_DEFINED",
    "VERTICAL_CS_TYPE",
    "VERTICAL_UNITS",
    "GdalMetadata",
    "GeoKeyError",
    "GeoKeyValue",
    "parse_gdal_metadata",
    "parse_geokeys",
    "parse_nodata",
]

# Claves (GeoTIFF 1.1) ----------------------------------------------------------------------
GT_MODEL_TYPE = 1024
GT_RASTER_TYPE = 1025
GEOGRAPHIC_TYPE = 2048
PROJECTED_CS_TYPE = 3072
PROJ_LINEAR_UNITS = 3076
VERTICAL_CS_TYPE = 4096
VERTICAL_UNITS = 4099
# Valores -----------------------------------------------------------------------------------
MODEL_PROJECTED = 1
MODEL_GEOGRAPHIC = 2
RASTER_PIXEL_IS_AREA = 1
RASTER_PIXEL_IS_POINT = 2
USER_DEFINED = 32767
LINEAR_METRE = 9001  # EPSG: metro

_DIRECTORY_TAG = 34735
_DOUBLE_TAG = 34736
_ASCII_TAG = 34737
_HEADER = 4
_VERSION = 1

type GeoKeyValue = int | str | tuple[float, ...] | tuple[int, ...]

_ITEM = re.compile(r"<Item\b([^>]*)>([^<]*)</Item>", re.IGNORECASE)
_ATTRIBUTE = re.compile(r"""(\w+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")


class GeoKeyError(ValueError):
    """El ``GeoKeyDirectory`` está mal formado; el texto, en español, dice por qué."""


def parse_geokeys(
    directory: Sequence[int],
    *,
    doubles: Sequence[float] = (),
    ascii: str = "",
) -> dict[int, GeoKeyValue]:
    """Las claves de ``directory`` (el ``GeoKeyDirectory``), con sus valores en el propio
    directorio, en ``doubles`` (``GeoDoubleParams``) o en ``ascii`` (``GeoAsciiParams``).
    :class:`GeoKeyError` si está mal formado."""
    if len(directory) < _HEADER:
        raise GeoKeyError(
            f"GeoKeyDirectory tiene {len(directory)} valores, menos que su cabecera"
        )
    version, _revision, _minor, count = directory[:_HEADER]
    if version != _VERSION:
        raise GeoKeyError(f"versión {version} del GeoKeyDirectory (se admite la 1)")
    if len(directory) < _HEADER + 4 * count:
        raise GeoKeyError(
            f"GeoKeyDirectory declara {count} claves y solo tiene sitio para "
            f"{(len(directory) - _HEADER) // 4}"
        )
    keys: dict[int, GeoKeyValue] = {}
    for index in range(count):
        start = _HEADER + 4 * index
        key, location, number, value = directory[start : start + 4]
        if location == 0:
            if number != 1:
                raise GeoKeyError(f"la clave {key} va en el directorio con {number} valores")
            keys[key] = int(value)
        elif location == _DOUBLE_TAG:
            keys[key] = tuple(float(v) for v in _slice(doubles, value, number, key))
        elif location == _ASCII_TAG:
            keys[key] = str(_slice(ascii, value, number, key)).rstrip("|")
        elif location == _DIRECTORY_TAG:
            keys[key] = tuple(int(v) for v in _slice(directory, value, number, key))
        else:
            raise GeoKeyError(
                f"la clave {key} está en la etiqueta {location}, que no es de claves"
            )
    return keys


def _slice[T: Sequence[object]](values: T, start: int, number: int, key: int) -> T:
    if start < 0 or number < 0 or start + number > len(values):
        raise GeoKeyError(
            f"la clave {key} apunta a los valores {start} a {start + number} y su etiqueta "
            f"tiene {len(values)}"
        )
    return values[start : start + number]  # type: ignore[return-value]


def parse_nodata(text: str) -> float:
    """El sin dato de ``GDAL_NODATA`` (``"-9999"``, ``"nan"``, ``"-3.4e+38"``) como
    ``float``; ``ValueError`` si no es un número."""
    return float(text.strip())


@dataclass(frozen=True, slots=True)
class GdalMetadata:
    """Lo que Geoblender lee de ``GDAL_METADATA`` para la banda 1: ``scale`` y ``offset``
    de los valores (1 y 0 si no los hay) y ``unit``, la unidad de las cotas (``""`` si no
    la hay)."""

    scale: float = 1.0
    offset: float = 0.0
    unit: str = ""


def parse_gdal_metadata(text: str) -> GdalMetadata:
    """Escala, offset y unidad de la banda 1 (``sample="0"``) del XML de
    ``GDAL_METADATA``; ``ValueError`` si la escala o el offset no son números."""
    found: dict[str, str] = {}
    for attributes, content in _ITEM.findall(text):
        attrs = {m[0].lower(): m[1] or m[2] for m in _ATTRIBUTE.findall(attributes)}
        role = attrs.get("role", "").lower()
        if role in ("scale", "offset", "unittype") and attrs.get("sample", "0") == "0":
            found[role] = content.strip()
    scale = float(found["scale"]) if found.get("scale") else 1.0
    offset = float(found["offset"]) if found.get("offset") else 0.0
    if not (math.isfinite(scale) and math.isfinite(offset)):
        raise ValueError(f"escala {scale} u offset {offset} no finitos")
    return GdalMetadata(scale, offset, found.get("unittype", ""))
