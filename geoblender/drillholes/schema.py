# SPDX-License-Identifier: GPL-3.0-or-later
"""Las tablas de los sondeos en el proyecto y su hash (spec 005, T37; RF-005-01, RF-005-02;
plan 005 §5.2, §5.2.1 y §5.6.1, D17).

Cada tabla se declara con su :class:`TableLayout`: su nombre, su nombre visible en QGIS
(``gpkg_contents.identifier``), su geometría (``POINT`` o ``LINESTRING`` con Z en el CRS del
proyecto, o ninguna: una tabla de atributos), sus columnas (``core.gpkg.ColumnDef``, sin
``fid`` ni ``geom``), el título en español de cada columna (el alias que muestra QGIS,
RF-005-01; todos en :data:`ALIASES`) y sus índices. Hay tres grupos (plan §5.6.1):

- **la base** (:data:`BASE_TABLES`): ``dh_collar`` (capa de puntos con Z) y diez tablas, con el
  DDL del plan §5.2 salvo lo que cambia §5.6.1 (sin ``REFERENCES``; los ``CHECK`` de
  enumeraciones y claves, en Python; ``uid`` determinista, :func:`hole_uid`, y
  ``survey_sha256`` en ``dh_collar``; nombres y códigos únicos sin distinguir mayúsculas con un
  índice ``NOCASE``). Las escribe solo ``dh.build_base`` desde lo importado vigente;
- **lo calculado** (:data:`COMPUTED_TABLES`): ``dh_trace`` (capa de líneas 3D, con
  ``survey_sha256``), ``dh_validation_issue`` y ``dh_import_log``; las dos primeras sin
  ``operation_uid`` ni ``stale``, que los da la procedencia de la 008. Una incidencia lleva el
  elemento y el código del catálogo en texto (``element``, ``catalog_code``): uno que no está en
  su catálogo (DH-E11) no tiene id;
- **lo importado** (:data:`SOURCE_ROLES`): por cada entrada y papel, una tabla de atributos
  ``dh_src_<rol>_<nombre>_<entrada8>`` (:func:`source_table`) con las filas de la fuente ya
  interpretadas en el CRS, el datum y los convenios declarados, sin transformar, con el sondeo
  por su nombre (``hole_name``), ``external_id`` y ``extra`` (las columnas, las del modelo de
  ``drillholes.model``; el sector y el grupo de una boca, ``sector_code`` y ``group_code``).

Ninguna tabla se crea al abrir ni al migrar un proyecto (sin paso de esquema, RF-008-62):
:func:`create_table` crea la que escribe una operación, en su transacción, con ``core.gpkg``
(``create_feature_table`` o ``create_attribute_table``, ``set_column_titles`` y
``create_index``); :func:`insert_rows` escribe sus filas (en el orden de
:attr:`TableLayout.insert_columns`: la geometría, un blob GeoPackage de
``core.gpkg.wkb.encode_geometry``, y las columnas). :func:`table_digest` da el hash de contenido
de una tabla (``core.gpkg_layer@1``, el lector con que la hashea el registro de la 008) sin
escribirla en el proyecto, como ``gis.store.table_digest``: así lo calcula un trabajo y el hilo
de Blender no vuelve a leer la tabla al incorporarla (plan §5.6.5 y §5.6.7). Una tabla sin
geometría la hashea sin pasar por SQLite, con lo que SQLite haría con cada valor (T52); lo que
no sabe emular, por :func:`stored_digest` (un GeoPackage en memoria), con el mismo hash.

**Valores** (RF-005-02; plan §5.2.2): los números, en float64 tal como llegan (el Single de
RecMin, por su decimal más corto, ``drillholes.values.from_single``); un NaN se guarda como
``NULL`` (SQLite no guarda NaN), por eso las columnas de números medidos admiten ``NULL``; los
textos, tal como venían; sí/no, 0 o 1; las fechas, «AAAA-MM-DD»; las enumeraciones, su texto;
``extra``, un JSON. El ``fid`` (el número interno) no es contenido, pero ``hole_id`` y los
demás identificadores que lo citan sí: que los ``fid`` de la base sean deterministas (las bocas
por nombre; lo demás por sondeo y profundidad) es cosa de ``dh.build_base``.

Python puro y ``sqlite3`` (ADR-0004).
"""

from __future__ import annotations

import itertools
import math
import re
import sqlite3
import unicodedata
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ..core.content.builtin import GPKG_LAYER, GPKG_TYPES, layer_steps
from ..core.content.encoder import NORMALIZER, ContentDigest, ContentHasher
from ..core.datasets.model import DATASET_DECLARATIONS
from ..core.errors import ValidationError
from ..core.georef import CrsRef
from ..core.gpkg.base import (
    GEOMETRY_COLUMN,
    ColumnDef,
    create_attribute_table,
    create_base,
    create_feature_table,
    create_index,
    set_column_titles,
)
from ..jobs.worker_api import JobCancelled
from .model import LITHOLOGY_LOG_SET, name_key

__all__ = [
    "ALIASES",
    "BASE_TABLES",
    "COMPUTED_TABLES",
    "DIGEST_ROWS",
    "INSERT_ROWS",
    "LAYOUTS",
    "MAX_SLUG_CHARS",
    "MAX_TABLE_CHARS",
    "SOURCE_PREFIX",
    "SOURCE_ROLES",
    "IndexDef",
    "TableLayout",
    "create_table",
    "hole_uid",
    "input_tag",
    "insert_rows",
    "layout_of",
    "slug",
    "source_layout",
    "source_name",
    "source_table",
    "stored_digest",
    "table_digest",
]

MAX_TABLE_CHARS = 63
"""El largo máximo del nombre de una tabla (el de un identificador de ``core.gpkg``)."""
MAX_SLUG_CHARS = 30
"""El largo máximo del nombre de la orden en el de una tabla de lo importado: con el papel más
largo (``zone_interval``) y el uid corto de la entrada, 60 caracteres (plan §5.6.1)."""
SOURCE_PREFIX = "dh_src_"
"""El comienzo del nombre de lo importado: ``dh_src_<rol>_<nombre>_<entrada8>``."""
INSERT_ROWS = 500
"""Las filas de cada ``INSERT`` de :func:`insert_rows` (como ``gis.store.INSERT_ROWS``: con una
sentencia por fila, cada una reescribe ``sqlite_sequence`` del proyecto)."""
TAG_CHARS = 8
"""Las cifras del uid de una entrada en el nombre de lo importado (D22 de la 006)."""
DIGEST_ROWS = 1 << 14
"""Las filas de cada trozo de :func:`table_digest` sin SQLite (un punto de cancelación y de
avance; unos 0,1 s con las 20 columnas de ``dh_assay``)."""

_NON_SLUG = re.compile(r"[^a-z0-9]+")
_HEX = re.compile(r"[0-9a-f]+")
_DATE_TEXT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_NONE = type(None)
_INT64_MIN = -(1 << 63)
_INT64_MAX = (1 << 63) - 1
_OBJ = "Tabla de sondeos"
_DATA_OBJ = "Datos de sondeos"


# --- Declaración de las tablas -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IndexDef:
    """Un índice de una tabla: sus columnas en orden, si es único y las que se comparan sin
    distinguir mayúsculas (``core.gpkg.create_index``)."""

    columns: tuple[str, ...]
    unique: bool = False
    nocase: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TableLayout:
    """Una tabla de los sondeos (véase el módulo): su nombre (en lo importado, el comienzo
    ``dh_src_<rol>`` del de cada tabla), su nombre visible (``label``: el
    ``gpkg_contents.identifier`` es «<label> (<tabla>)»), su geometría (``POINT``,
    ``LINESTRING`` o ``None``), sus columnas sin ``fid`` ni ``geom``, el título en español de
    cada una (``titles``, en el orden de las columnas), sus índices y, en lo importado, su
    papel (``role``)."""

    name: str
    label: str
    geometry_type: str | None
    columns: tuple[ColumnDef, ...]
    titles: Mapping[str, str]
    indexes: tuple[IndexDef, ...] = ()
    role: str | None = None

    @property
    def source(self) -> bool:
        """Si es lo importado de una entrada (``dh_src_*``)."""
        return self.role is not None

    @property
    def kind(self) -> str:
        """Su tipo de dato (``core.datasets``): ``vector`` una capa y ``table`` una tabla."""
        return "table" if self.geometry_type is None else "vector"

    @property
    def has_z(self) -> bool:
        """Si su geometría lleva Z (las dos capas la llevan)."""
        return self.geometry_type is not None

    @property
    def column_names(self) -> tuple[str, ...]:
        """Los nombres de sus columnas, sin ``fid`` ni ``geom``."""
        return tuple(column.name for column in self.columns)

    @property
    def insert_columns(self) -> tuple[str, ...]:
        """Las columnas de una fila de :func:`insert_rows` y :func:`table_digest`, en orden:
        ``geom`` (en una capa) y las demás."""
        head = (GEOMETRY_COLUMN,) if self.geometry_type is not None else ()
        return head + self.column_names


def _c(name: str, sql_type: str, title: str, *, not_null: bool = False,
       default: str | None = None) -> tuple[ColumnDef, str]:
    """Una columna y su título."""
    return ColumnDef(name, sql_type, not_null=not_null, default=default), title


def _layout(name: str, label: str, geometry_type: str | None,
            columns: Sequence[tuple[ColumnDef, str]], indexes: Sequence[IndexDef] = (), *,
            role: str | None = None) -> TableLayout:
    return TableLayout(name, label, geometry_type, tuple(column for column, _ in columns),
                       MappingProxyType({column.name: title for column, title in columns}),
                       tuple(indexes), role)


# Columnas comunes.
_EXTRA = _c("extra", "TEXT", "Otros campos", not_null=True, default="'{}'")
_EXTERNAL = _c("external_id", "TEXT", "Id. externo")
_INPUT = _c("input_uid", "TEXT", "Entrada", not_null=True)
_HOLE_ID = _c("hole_id", "INTEGER", "Id. del sondeo", not_null=True)
_HOLE_NAME = _c("hole_name", "TEXT", "Sondeo", not_null=True)
_FROM = _c("from_m", "DOUBLE", "Desde (m)")
_TO = _c("to_m", "DOUBLE", "Hasta (m)")
_DEPTH = _c("depth", "DOUBLE", "Profundidad (m)")
_DESCRIPTION = _c("description", "TEXT", "Descripción")
_COMMENTS = _c("comments", "TEXT", "Comentarios")
_CODE = _c("code", "TEXT", "Código", not_null=True)
_LOG_SET = _c("log_set", "TEXT", "Esquema de logueo", not_null=True,
              default=f"'{LITHOLOGY_LOG_SET}'")
_DENSITY = _c("density", "DOUBLE", "Densidad (t/m³)")
_DENSITY_KIND = _c("density_kind", "TEXT", "Tipo de densidad")
_SURVEY_SHA256 = _c("survey_sha256", "TEXT", "Huella de la desviación", not_null=True)

# Las columnas de una boca, de una estación… que son las mismas en la base y en lo importado.
_COLLAR_XYZ = (
    _c("x", "DOUBLE", "X (m)"),
    _c("y", "DOUBLE", "Y (m)"),
    _c("z", "DOUBLE", "Z (m)"),
    _DEPTH,
    _c("depth_kind", "TEXT", "Tipo de profundidad", not_null=True, default="'MEDIDO'"),
    _c("hole_type", "TEXT", "Tipo de sondeo"),
    _c("planned", "BOOLEAN", "Planificado", not_null=True, default="0"),
    _c("grade_control", "BOOLEAN", "Control de leyes", not_null=True, default="0"),
    _c("category", "INTEGER", "Categoría"),
    _c("priority", "INTEGER", "Prioridad"),
)
_COLLAR_DATES = (
    _c("campaign", "TEXT", "Campaña"),
    _c("start_date", "DATE", "Fecha de inicio"),
    _c("end_date", "DATE", "Fecha de fin"),
    _c("survey_method", "TEXT", "Método de levantamiento"),
)
_STATION_SOURCE = _c("source", "TEXT", "Origen de la estación", not_null=True,
                     default="'measured'")
_STATION_METHOD = _c("method", "TEXT", "Método de medida")
_LITHOLOGY_TEXTS = (_DESCRIPTION, _c("logged_by", "TEXT", "Descrito por"))
_ASSAY_VALUE = (
    _c("value", "DOUBLE", "Valor"),
    _c("unit", "TEXT", "Unidad", not_null=True),
    _c("detection_flag", "TEXT", "Marca de detección", not_null=True, default="'ok'"),
)
_ASSAY_SAMPLE = (
    _c("lab", "TEXT", "Laboratorio"),
    _c("method", "TEXT", "Método de análisis"),
    _c("sample_id", "TEXT", "Muestra"),
    _c("batch", "TEXT", "Lote"),
    _c("qaqc_type", "TEXT", "Tipo de muestra", not_null=True, default="'sample'"),
    _c("crm_code", "TEXT", "Material de referencia"),
    _c("parent_sample_id", "TEXT", "Muestra original"),
    _c("is_primary", "BOOLEAN", "Primaria", not_null=True, default="1"),
)
_ASSAY_REPORTED = (
    _c("reported_value", "TEXT", "Valor del laboratorio"),
    _c("reported_unit", "TEXT", "Unidad del laboratorio"),
)
_ANGLE = _c("angle_deg", "DOUBLE", "Ángulo (°)")
_STRUCTURE = (
    _DEPTH,
    _c("structure_type", "TEXT", "Tipo de estructura", not_null=True),
    _c("dip", "DOUBLE", "Buzamiento (°)"),
    _c("dip_direction", "DOUBLE", "Dirección de buzamiento (°)"),
    _c("alpha", "DOUBLE", "Alfa (°)"),
    _c("beta", "DOUBLE", "Beta (°)"),
    _c("orientation_source", "TEXT", "Origen de la orientación", not_null=True,
       default="'measured'"),
)
_STRUCTURE_TEXTS = (_c("confidence", "TEXT", "Confianza"), _COMMENTS)
_LITHOLOGY_CODE = (
    _c("color", "TEXT", "Color (sRGB)", not_null=True, default="'#808080'"),
    _c("pattern", "TEXT", "Trama"),
    _DENSITY,
    _DENSITY_KIND,
    _c("sort_order", "INTEGER", "Orden", not_null=True, default="0"),
    _c("show_in_legend", "BOOLEAN", "En la leyenda", not_null=True, default="1"),
)
_ELEMENT = (
    _c("name", "TEXT", "Nombre"),
    _c("unit", "TEXT", "Unidad", not_null=True),
    _c("decimals", "INTEGER", "Decimales", not_null=True, default="2"),
    _c("sort_order", "INTEGER", "Orden", not_null=True, default="0"),
    _c("show_in_tables", "BOOLEAN", "En las tablas", not_null=True, default="1"),
    _c("use_in_calc", "BOOLEAN", "En los cálculos", not_null=True, default="1"),
    _c("detection_limit", "DOUBLE", "Límite de detección"),
    _c("expression", "TEXT", "Expresión"),
    _c("color_legend", "TEXT", "Leyenda de colores"),
)
_UNIQUE_CODE = IndexDef(("code",), unique=True, nocase=("code",))


def _catalog(name: str, label: str, *more: tuple[ColumnDef, str]) -> TableLayout:
    """Un catálogo de agrupación (sectores, grupos, zonas): su código único sin mayúsculas."""
    return _layout(name, label, None,
                   (_CODE, _DESCRIPTION, *more, _EXTERNAL, _EXTRA), (_UNIQUE_CODE,))


_BASE: tuple[TableLayout, ...] = (
    _layout("dh_collar", "Sondeos: bocas", "POINT", (
        _c("uid", "TEXT", "Identificador", not_null=True),
        _c("name", "TEXT", "Sondeo", not_null=True),
        *_COLLAR_XYZ,
        _c("sector_id", "INTEGER", "Id. del sector"),
        _c("group_id", "INTEGER", "Id. del grupo"),
        *_COLLAR_DATES,
        _EXTERNAL, _INPUT, _COMMENTS, _EXTRA, _SURVEY_SHA256,
    ), (IndexDef(("uid",), unique=True), IndexDef(("name",), unique=True, nocase=("name",)))),
    _layout("dh_survey", "Sondeos: desviaciones", None, (
        _HOLE_ID, _DEPTH,
        _c("azimuth", "DOUBLE", "Azimut de cuadrícula (°)"),
        _c("inclination", "DOUBLE", "Inclinación (°)"),
        _c("azimuth_measured", "DOUBLE", "Azimut medido (°)"),
        _c("azimuth_ref", "TEXT", "Referencia del azimut", not_null=True),
        _c("declination_deg", "DOUBLE", "Declinación magnética (°)"),
        _c("convergence_deg", "DOUBLE", "Convergencia de cuadrícula (°)"),
        _STATION_SOURCE, _STATION_METHOD, _INPUT, _EXTERNAL, _EXTRA,
    ), (IndexDef(("hole_id", "depth")),)),
    _layout("dh_lithology", "Sondeos: litología", None, (
        _HOLE_ID, _FROM, _TO, _LOG_SET,
        _c("lithology_id", "INTEGER", "Id. de la litología", not_null=True),
        *_LITHOLOGY_TEXTS, _INPUT, _EXTERNAL, _EXTRA,
    ), (IndexDef(("hole_id", "log_set", "from_m")),)),
    _layout("dh_assay", "Sondeos: análisis", None, (
        _c("hole_id", "INTEGER", "Id. del sondeo"), _FROM, _TO,
        _c("element_id", "INTEGER", "Id. del elemento", not_null=True),
        *_ASSAY_VALUE, *_ASSAY_SAMPLE, *_ASSAY_REPORTED, _INPUT, _EXTERNAL, _EXTRA,
    ), (IndexDef(("hole_id", "element_id", "from_m")), IndexDef(("sample_id",)))),
    _layout("dh_zone_interval", "Sondeos: intersecciones de zonas", None, (
        _HOLE_ID, _FROM, _TO,
        _c("zone_id", "INTEGER", "Id. de la zona", not_null=True),
        _ANGLE, _INPUT, _EXTERNAL, _EXTRA,
    )),
    _layout("dh_structure", "Sondeos: estructuras", None, (
        _HOLE_ID, *_STRUCTURE,
        _c("zone_id", "INTEGER", "Id. de la zona"),
        *_STRUCTURE_TEXTS, _INPUT, _EXTERNAL, _EXTRA,
    )),
    _layout("dh_lithology_code", "Sondeos: catálogo de litologías", None, (
        _CODE, _LOG_SET, _DESCRIPTION, *_LITHOLOGY_CODE, _EXTERNAL, _EXTRA,
    ), (IndexDef(("log_set", "code"), unique=True, nocase=("log_set", "code")),)),
    _layout("dh_element", "Sondeos: catálogo de elementos", None, (
        _CODE, *_ELEMENT, _EXTERNAL, _EXTRA,
    ), (_UNIQUE_CODE,)),
    _catalog("dh_sector", "Sondeos: catálogo de sectores"),
    _catalog("dh_group", "Sondeos: catálogo de grupos"),
    _catalog("dh_zone", "Sondeos: catálogo de zonas", _DENSITY, _DENSITY_KIND),
)

_COMPUTED: tuple[TableLayout, ...] = (
    _layout("dh_trace", "Sondeos: trayectorias", "LINESTRING", (
        _HOLE_ID,
        _c("method", "TEXT", "Método de cálculo", not_null=True),
        _c("length_m", "DOUBLE", "Longitud (m)", not_null=True),
        _c("end_x", "DOUBLE", "X del fondo (m)", not_null=True),
        _c("end_y", "DOUBLE", "Y del fondo (m)", not_null=True),
        _c("end_z", "DOUBLE", "Z del fondo (m)", not_null=True),
        _SURVEY_SHA256,
    ), (IndexDef(("hole_id",), unique=True),)),
    _layout("dh_validation_issue", "Sondeos: incidencias de la validación", None, (
        _c("hole_id", "INTEGER", "Id. del sondeo"),
        _c("hole_name", "TEXT", "Sondeo"),
        _c("code", "TEXT", "Código", not_null=True),
        _c("level", "TEXT", "Nivel", not_null=True),
        _c("scope", "TEXT", "Alcance"),
        _c("table_name", "TEXT", "Tabla", not_null=True),
        _c("row_fid", "INTEGER", "Fila (fid)"),
        _c("log_set", "TEXT", "Esquema de logueo"),
        _c("element", "TEXT", "Elemento"),
        _c("catalog_code", "TEXT", "Código del catálogo"),
        _c("depth_from", "DOUBLE", "Desde (m)"),
        _c("depth_to", "DOUBLE", "Hasta (m)"),
        _c("field", "TEXT", "Campo"),
        _c("value", "TEXT", "Valor"),
        _c("message", "TEXT", "Mensaje", not_null=True),
    ), (IndexDef(("hole_id", "code")),)),
    _layout("dh_import_log", "Sondeos: informe de las importaciones", None, (
        _c("operation_uid", "TEXT", "Operación", not_null=True),
        _c("input_uid", "TEXT", "Entrada"),
        _c("table_role", "TEXT", "Tabla", not_null=True),
        _c("kind", "TEXT", "Tipo de línea", not_null=True),
        _c("n_read", "INTEGER", "Leídos"),
        _c("n_imported", "INTEGER", "Importados"),
        _c("n_rejected", "INTEGER", "Rechazados"),
        _c("n_replaced", "INTEGER", "Sustituidos"),
        _c("row_number", "INTEGER", "Fila"),
        _c("field", "TEXT", "Campo"),
        _c("value", "TEXT", "Valor"),
        _c("reason", "TEXT", "Motivo"),
    )),
)


def _source(role: str, label: str, columns: Sequence[tuple[ColumnDef, str]]) -> TableLayout:
    """La tabla de lo importado de un papel (sin índices: ``dh.build_base`` la lee entera)."""
    return _layout(f"{SOURCE_PREFIX}{role}", f"Sondeos importados: {label}", None,
                   (*columns, _EXTERNAL, _EXTRA), role=role)


_SOURCES: tuple[TableLayout, ...] = (
    _source("collar", "bocas", (
        _c("name", "TEXT", "Sondeo", not_null=True),
        *_COLLAR_XYZ,
        _c("sector_code", "TEXT", "Sector"),
        _c("group_code", "TEXT", "Grupo"),
        *_COLLAR_DATES,
        _COMMENTS,
    )),
    _source("survey", "desviaciones", (
        _HOLE_NAME, _DEPTH,
        _c("azimuth", "DOUBLE", "Azimut (°)"),
        _c("inclination", "DOUBLE", "Inclinación (°)"),
        _STATION_SOURCE, _STATION_METHOD,
    )),
    _source("lithology", "litología", (
        _HOLE_NAME, _FROM, _TO,
        _c("code", "TEXT", "Litología", not_null=True),
        _LOG_SET, *_LITHOLOGY_TEXTS,
    )),
    _source("assay", "análisis", (
        _c("hole_name", "TEXT", "Sondeo"), _FROM, _TO,
        _c("element", "TEXT", "Elemento", not_null=True),
        *_ASSAY_VALUE, *_ASSAY_REPORTED, *_ASSAY_SAMPLE,
    )),
    _source("catalog", "catálogos", (
        _c("catalog", "TEXT", "Catálogo", not_null=True),
        _CODE,
        _c("log_set", "TEXT", "Esquema de logueo"),
        _c("name", "TEXT", "Nombre"),
        _DESCRIPTION,
        _c("unit", "TEXT", "Unidad"),
        _c("decimals", "INTEGER", "Decimales"),
        _c("color", "TEXT", "Color (sRGB)"),
        _c("pattern", "TEXT", "Trama"),
        _DENSITY,
        _DENSITY_KIND,
        _c("sort_order", "INTEGER", "Orden"),
        _c("show_in_legend", "BOOLEAN", "En la leyenda"),
        _c("show_in_tables", "BOOLEAN", "En las tablas"),
        _c("use_in_calc", "BOOLEAN", "En los cálculos"),
        _c("detection_limit", "DOUBLE", "Límite de detección"),
        _c("expression", "TEXT", "Expresión"),
        _c("color_legend", "TEXT", "Leyenda de colores"),
    )),
    _source("zone_interval", "intersecciones de zonas", (
        _HOLE_NAME, _FROM, _TO,
        _c("zone", "TEXT", "Zona", not_null=True),
        _ANGLE,
    )),
    _source("structure", "estructuras", (
        _HOLE_NAME, *_STRUCTURE,
        _c("zone", "TEXT", "Zona"),
        *_STRUCTURE_TEXTS,
    )),
)

BASE_TABLES: tuple[str, ...] = tuple(layout.name for layout in _BASE)
"""Las once tablas de la base de los sondeos (las escribe ``dh.build_base``)."""
COMPUTED_TABLES: tuple[str, ...] = tuple(layout.name for layout in _COMPUTED)
"""Las tablas de lo calculado: trayectorias, incidencias de la validación e informe de las
importaciones."""
SOURCE_ROLES: tuple[str, ...] = tuple(str(layout.role) for layout in _SOURCES)
"""Los papeles de lo importado (``dh_src_<rol>_…``), en el orden del plan §5.6.1."""
LAYOUTS: Mapping[str, TableLayout] = MappingProxyType(
    {layout.name: layout for layout in (*_BASE, *_COMPUTED, *_SOURCES)})
"""Las tablas por nombre (lo importado, por el comienzo ``dh_src_<rol>``): la base, lo
calculado y lo importado, en ese orden."""
ALIASES: Mapping[tuple[str, str], str] = MappingProxyType({
    (layout.name, column): title
    for layout in LAYOUTS.values() for column, title in layout.titles.items()})
"""El título en español de cada columna, por (tabla, columna): el alias que muestra QGIS
(RF-005-01; plan §5.2.1)."""
_SOURCES_BY_ROLE: Mapping[str, TableLayout] = MappingProxyType(
    {str(layout.role): layout for layout in _SOURCES})
_SOURCE_TABLE = re.compile(
    rf"{SOURCE_PREFIX}(?P<role>{'|'.join(sorted(SOURCE_ROLES, key=len, reverse=True))})"
    rf"_[a-z0-9]+(?:_[a-z0-9]+)*_[0-9a-f]{{{TAG_CHARS}}}")


# --- Nombres ---------------------------------------------------------------------------------


def source_layout(role: str) -> TableLayout:
    """El ``TableLayout`` de lo importado del papel ``role`` (:data:`SOURCE_ROLES`);
    ``ValueError`` si no es uno de ellos."""
    found = _SOURCES_BY_ROLE.get(role) if isinstance(role, str) else None
    if found is None:
        raise ValueError(f"{role!r} no es un papel de lo importado de los sondeos: es uno de "
                         f"{', '.join(SOURCE_ROLES)}")
    return found


def layout_of(table: str) -> TableLayout:
    """El ``TableLayout`` de la tabla ``table`` del proyecto: una de la base o de lo calculado,
    por su nombre, o una de lo importado (``dh_src_<rol>_<nombre>_<entrada8>``). ``ValueError``
    si no es una tabla de los sondeos."""
    if isinstance(table, str):
        found = LAYOUTS.get(table)
        if found is not None and not found.source:
            return found
        match = _SOURCE_TABLE.fullmatch(table)
        if match is not None and len(table) <= MAX_TABLE_CHARS:
            return _SOURCES_BY_ROLE[match["role"]]
    raise ValueError(f"{table!r} no es una tabla de los sondeos: es una de "
                     f"{', '.join(BASE_TABLES + COMPUTED_TABLES)} o "
                     f"«{SOURCE_PREFIX}<papel>_<nombre>_<entrada8>»")


def slug(name: str) -> str:
    """El nombre de la orden ``name`` en el de una tabla de lo importado: en minúsculas, sin
    tildes («ñ» → «n») y con un «_» por cada tramo que no es una letra o una cifra ASCII, sin
    «_» a los lados y con :data:`MAX_SLUG_CHARS` caracteres como mucho (un nombre ya en esa
    forma no cambia). ``ValidationError`` ``dh.dataset_name_invalid`` si no queda ninguna letra
    ni cifra; ``TypeError`` si no es un texto."""
    if not isinstance(name, str):
        raise TypeError(f"el nombre de unos datos de sondeos es un texto, no {name!r}")
    plain = "".join(char for char in unicodedata.normalize("NFKD", name)
                    if not unicodedata.combining(char)).lower()
    found = _NON_SLUG.sub("_", plain).strip("_")[:MAX_SLUG_CHARS].rstrip("_")
    if not found:
        raise ValidationError("dh.dataset_name_invalid",
                              "el nombre necesita al menos una letra o una cifra",
                              obj=_DATA_OBJ, field="nombre", value=name)
    return found


def input_tag(input_uid: str) -> str:
    """El uid corto de una entrada en el nombre de lo importado: las :data:`TAG_CHARS`
    primeras cifras hexadecimales de su uid (un UUID en texto), en minúsculas. ``ValueError``
    si no es un uid así; ``TypeError`` si no es un texto."""
    if not isinstance(input_uid, str):
        raise TypeError(f"el uid de una entrada es un texto, no {input_uid!r}")
    head = input_uid.lower().partition("-")[0]
    if len(head) != TAG_CHARS or _HEX.fullmatch(head) is None or "-" not in input_uid:
        raise ValueError(f"{input_uid!r} no es el uid de una entrada (un UUID en texto, como "
                         "«3f2b9c1d-8e7a-4b6c-9d0e-1a2b3c4d5e6f»)")
    return head


def source_name(role: str, name: str) -> str:
    """El nombre del dato de lo importado del papel ``role`` con la orden llamada ``name``:
    ``dh_src_<rol>_<nombre>`` (:func:`slug`)."""
    return f"{source_layout(role).name}_{slug(name)}"


def source_table(role: str, name: str, input_uid: str) -> str:
    """La tabla de lo importado del papel ``role`` de la entrada ``input_uid`` con la orden
    llamada ``name``: ``dh_src_<rol>_<nombre>_<entrada8>`` (:func:`source_name` y
    :func:`input_tag`), de :data:`MAX_TABLE_CHARS` caracteres como mucho."""
    return f"{source_name(role, name)}_{input_tag(input_uid)}"


def hole_uid(project_uid: str, name: str) -> str:
    """El ``uid`` de la boca ``name`` en ``dh_collar`` del proyecto ``project_uid``: el uuid5
    del uid del proyecto y el nombre sin espacios a los lados ni mayúsculas
    (``drillholes.model.name_key``), el mismo en cada reconstrucción de la base (plan §5.6.1).
    ``ValueError`` si ``project_uid`` no es un UUID o el nombre queda vacío."""
    key = name_key(name)
    if not key:
        raise ValueError("el nombre de un sondeo no puede quedar vacío")
    return str(uuid.uuid5(uuid.UUID(project_uid), key))


# --- Crear, escribir y hashear --------------------------------------------------------------


def _check_layout(layout: object) -> TableLayout:
    if not isinstance(layout, TableLayout):
        raise TypeError(f"la tabla se declara con un TableLayout de drillholes.schema, no "
                        f"{layout!r}")
    return layout


def _create(conn: sqlite3.Connection, layout: TableLayout, name: str, srs: int | None,
            description: str, *, decorated: bool) -> None:
    """Crea la tabla ``name`` con la estructura de ``layout`` y, si ``decorated``, sus
    títulos y sus índices."""
    identifier = f"{layout.label} ({name})"
    if layout.geometry_type is None:
        create_attribute_table(conn, name, layout.columns, identifier, description)
    else:  # un SRS que no es un EPSG del GeoPackage lo rechaza core.gpkg (srs_unknown)
        create_feature_table(conn, name, layout.geometry_type, srs, layout.has_z,
                             layout.columns, identifier, description)
    if not decorated:
        return
    set_column_titles(conn, name, layout.titles)
    for index in layout.indexes:
        create_index(conn, name, index.columns, unique=index.unique, nocase=index.nocase)


def create_table(conn: sqlite3.Connection, layout: TableLayout, name: str, srs: int | None, *,
                 description: str = "") -> None:
    """Crea en la transacción de ``conn`` la tabla ``name`` de los sondeos con la estructura
    de ``layout`` (RF-005-01): una capa (``features``, su geometría con Z en el SRS ``srs``,
    el EPSG del proyecto, que ya está en ``gpkg_spatial_ref_sys``) o una tabla
    (``attributes``; ``srs`` no se usa), registrada en ``gpkg_contents`` con el identificador
    «<label> (<tabla>)» y la descripción ``description`` (la referencia de las Z de una
    capa), con el título de cada columna (``core.gpkg.set_column_titles``) y sus índices
    (``core.gpkg.create_index``). No confirma la transacción.

    ``name`` es el de ``layout`` (la base y lo calculado) o, en lo importado,
    ``dh_src_<rol>_<nombre>_<entrada8>`` de su papel (:func:`source_table`); si no,
    ``ValueError`` (un error del programa). ``ValidationError`` ``dh.table_exists`` si ya hay
    en la base una tabla (o un índice, una vista…) con ese nombre, sin distinguir
    mayúsculas, y las de ``core.gpkg`` (un SRS que no está, ``core.gpkg_srs_unknown``…), sin
    crear nada; ``TypeError`` si ``layout`` no es un :class:`TableLayout`."""
    _check_layout(layout)
    try:
        found = layout_of(name)
    except ValueError:
        found = None
    if found is not layout:
        raise ValueError(f"{name!r} no es el nombre de una tabla «{layout.name}»: "
                         + ("es «dh_src_<papel>_<nombre>_<entrada8>» (source_table)"
                            if layout.source else f"es «{layout.name}»"))
    taken = conn.execute("SELECT type FROM sqlite_master WHERE name = ? COLLATE NOCASE",
                         (name,)).fetchone()
    if taken is not None:
        raise ValidationError("dh.table_exists",
                              f"ya hay en el GeoPackage del proyecto un objeto ({taken[0]}) "
                              "con ese nombre: se crea al escribirla por primera vez",
                              obj=_OBJ, field="tabla", value=name)
    _create(conn, layout, name, srs, description, decorated=True)


def insert_rows(conn: sqlite3.Connection, layout: TableLayout, name: str,
                rows: Sequence[Sequence[Any]]) -> None:
    """Inserta ``rows`` (en su orden) en la tabla ``name`` de ``layout``: cada fila, sus
    valores en el orden de :attr:`TableLayout.insert_columns` (la geometría de una capa, un
    blob GeoPackage o ``None``, y las columnas), en sentencias de :data:`INSERT_ROWS` filas
    (las que quepan en el límite de variables de SQLite). ``ValueError`` si una fila no tiene
    ese número de valores, sin escribir nada."""
    _check_layout(layout)
    names = layout.insert_columns
    width = len(names)
    for number, row in enumerate(rows, start=1):
        if len(row) != width:
            raise ValueError(f"la fila {number} de «{name}» tiene {len(row)} valores y no "
                             f"{width} ({', '.join(names)})")
    limit = conn.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER)
    size = max(1, min(INSERT_ROWS, limit // width))
    quoted = ", ".join(f'"{column}"' for column in names)
    head = f'INSERT INTO "{name}" ({quoted}) VALUES '
    one = "(" + ", ".join("?" * width) + ")"
    full = head + ", ".join([one] * size)
    for first in range(0, len(rows), size):
        chunk = rows[first:first + size]
        sql = full if len(chunk) == size else head + ", ".join([one] * len(chunk))
        conn.execute(sql, list(itertools.chain.from_iterable(chunk)))


def table_digest(
    layout: TableLayout,
    rows: Sequence[Sequence[Any]],
    crs: CrsRef,
    *,
    progress: Callable[[float, str], object] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ContentDigest:
    """El ``ContentDigest`` (``core.gpkg_layer@1``, sin declaraciones: el de un dato del
    proyecto) de la tabla de ``layout`` con las filas ``rows`` (las de :func:`insert_rows`) y
    las coordenadas de su geometría en ``crs``, sin escribirla en el proyecto: el hash que da
    la tabla escrita en el proyecto y leída con ``core.content.builtin.layer_steps``, la
    función con que el registro de la 008 hashea una tabla del proyecto (ADR-0024 §5); el
    ``fid`` no cuenta, ni el orden de las filas, y el de una tabla sin geometría no depende de
    ``crs``.

    Una tabla sin geometría cuyos valores SQLite guarda tal como llegan se hashea sin pasar por
    él (spec 005, T52; RNF-005-01): sus columnas, con lo que SQLite haría al guardarlas (un NaN
    en una columna de números es ``NULL``; un sí/no, 0 o 1), por lotes de
    :data:`DIGEST_ROWS` filas con ``RowEncoder.update_columns``. Lo demás —una capa, un valor
    de otro tipo que SQLite convertiría (un entero en una columna de reales, un texto en una
    de sí/no…), un nulo en una columna ``NOT NULL``, una fila de otro largo— va por
    :func:`stored_digest`, que lo guarda de verdad en un GeoPackage en memoria; el hash es el
    mismo por los dos caminos, y también los errores. ``progress(fracción, texto)`` tras cada
    trozo; ``JobCancelled`` si ``cancelled()`` pide parar entre trozos; ``TypeError`` si
    ``layout`` no es un :class:`TableLayout` o ``crs`` no es un ``CrsRef``; ``ValueError`` si
    una fila no tiene el número de valores de la tabla."""
    _check_layout(layout)
    if not isinstance(crs, CrsRef):
        raise TypeError(f"el CRS de las coordenadas es un CrsRef del catálogo, no {crs!r}")
    columns = _stored_columns(layout, rows)
    if columns is None:
        return stored_digest(layout, rows, crs, progress=progress, cancelled=cancelled)
    try:
        return _columns_digest(layout, columns, len(rows), progress, cancelled)
    except (TypeError, ValueError, ArithmeticError):
        # Un valor que no vale (un texto con un sustituto suelto…): el error, el de SQLite.
        return stored_digest(layout, rows, crs, cancelled=cancelled)


def _stored_columns(layout: TableLayout,
                    rows: Sequence[Sequence[Any]]) -> list[Sequence[Any]] | None:
    """Las columnas de ``rows`` como las devuelve SQLite tras guardarlas en una tabla de
    ``layout`` sin geometría, o ``None`` si eso no se sabe sin SQLite (véase
    :func:`table_digest`)."""
    if layout.geometry_type is not None:
        return None
    width = len(layout.columns)
    try:
        if len(rows) and set(map(len, rows)) != {width}:
            return None
        values = list(zip(*rows, strict=True)) if len(rows) else [()] * width
    except TypeError:
        return None
    found: list[Sequence[Any]] = []
    for column, column_values in zip(layout.columns, values, strict=True):
        stored = _stored_values(column, column_values)
        if stored is None:
            return None
        found.append(stored)
    return found


def _stored_values(column: ColumnDef, values: Sequence[Any]) -> Sequence[Any] | None:
    """Los valores de una columna como los devuelve SQLite tras guardarlos, si los guarda tal
    cual o se sabe cómo (un NaN en una de reales es ``NULL``; un sí/no, 0 o 1), o ``None``."""
    types = set(map(type, values))
    nulls = _NONE in types
    types.discard(_NONE)
    sql_type = column.sql_type
    stored: Sequence[Any] = values
    if sql_type == "DOUBLE":
        if not types <= {float}:
            return None
        if nulls or any(map(math.isnan, values)):
            stored = [None if value != value else value for value in values]  # NaN → NULL
            nulls = nulls or None in stored
    elif sql_type == "INTEGER":
        if not types <= {int}:
            return None
        numbers = [value for value in values if value is not None] if nulls else values
        if numbers and (min(numbers) < _INT64_MIN or max(numbers) > _INT64_MAX):
            return None
    elif sql_type == "BOOLEAN":
        if not types <= {bool, int}:
            return None
        if int in types:  # 0 o 1, como sí/no
            if any(value not in (0, 1) for value in values if value is not None):
                return None
            stored = [None if value is None else value == 1 for value in values]
    elif sql_type in ("TEXT", "DATE"):
        if not types <= {str}:
            return None
        if sql_type == "DATE" and not all(_DATE_TEXT.fullmatch(value) for value in values
                                          if value is not None):
            return None  # SQLite tomaría por número algún otro texto
    else:
        return None
    if column.not_null and nulls:
        return None  # SQLite no lo guarda: su error
    return stored


def _columns_digest(layout: TableLayout, columns: Sequence[Sequence[Any]], count: int,
                    progress: Callable[[float, str], object] | None,
                    cancelled: Callable[[], bool] | None) -> ContentDigest:
    """El hash de una tabla sin geometría con sus columnas ya como las guarda SQLite."""
    name = layout.name
    text = f"Calculando el hash de contenido de la tabla «{name}»…"
    hasher = ContentHasher(layout.kind, declarations=DATASET_DECLARATIONS, reader=GPKG_LAYER.id,
                           normalizer=NORMALIZER)
    feed = hasher.begin_rows([[column.name, GPKG_TYPES[column.sql_type]]
                              for column in layout.columns], False)
    pieces = max(1, -(-count // DIGEST_ROWS))
    total = pieces + 1
    for index, first in enumerate(range(0, count, DIGEST_ROWS), start=1):
        _check_cancelled(cancelled, name, index)
        feed.update_columns([column[first:first + DIGEST_ROWS] for column in columns])
        if progress is not None:
            progress(index / total, text)
    steps = feed.finish_steps(DIGEST_ROWS)
    try:
        while True:
            _check_cancelled(cancelled, name, pieces + 1)
            try:
                done = next(steps)
            except StopIteration:
                break
            if progress is not None:
                progress((pieces + done) / total, text)
    finally:
        steps.close()
    if progress is not None:
        progress(1.0, text)
    return hasher.digest()


def _check_cancelled(cancelled: Callable[[], bool] | None, name: str, index: int) -> None:
    if cancelled is not None and cancelled():
        raise JobCancelled(f"Cancelado al calcular el hash de la tabla «{name}» en el trozo "
                           f"{index}")


def stored_digest(
    layout: TableLayout,
    rows: Sequence[Sequence[Any]],
    crs: CrsRef,
    *,
    progress: Callable[[float, str], object] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ContentDigest:
    """El hash de :func:`table_digest` con las filas guardadas de verdad: van a un GeoPackage
    en memoria con la misma estructura (``create_base`` con ``crs`` y la tabla con sus
    columnas y su geometría; los títulos y los índices no cuentan) y se leen con
    ``core.content.builtin.layer_steps``. Lo usa :func:`table_digest` con lo que no sabe
    hashear sin SQLite (las capas, los valores que SQLite convierte, las filas que no valen);
    los errores, los mismos."""
    _check_layout(layout)
    if not isinstance(crs, CrsRef):
        raise TypeError(f"el CRS de las coordenadas es un CrsRef del catálogo, no {crs!r}")
    name = layout.name
    text = f"Calculando el hash de contenido de la tabla «{name}»…"
    conn = sqlite3.connect(":memory:")
    try:
        create_base(conn, crs)
        _create(conn, layout, name, crs.epsg, "", decorated=False)
        insert_rows(conn, layout, name, rows)
        request = GPKG_LAYER.request(layout.kind, DATASET_DECLARATIONS, {"main": Path(name)},
                                     {"layer": name}, normalizer=NORMALIZER)
        steps = layer_steps(conn, request)
        try:
            for index, done in enumerate(steps, start=1):
                if cancelled is not None and cancelled():
                    raise JobCancelled(f"Cancelado al calcular el hash de la tabla «{name}» en "
                                       f"el trozo {index}")
                if progress is not None:
                    progress(done, text)
        finally:
            steps.close()
        return request.hasher.digest()
    finally:
        conn.close()
