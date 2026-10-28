# SPDX-License-Identifier: GPL-3.0-or-later
"""Capas de un GeoPackage de otro programa, leídas sobre una copia (spec 006; plan 006
§5.2.6, §5.3.2, §5.3.6 y A18; RF-006-10, RF-006-12).

El GeoPackage del usuario (de QGIS u otro programa) **nunca se abre**: abrirlo, aun en solo
lectura, crea ``-wal`` y ``-shm`` junto a una base en WAL, e ``immutable=1`` ignora un WAL
pendiente (plan §6, D9). :func:`copy_source` lo copia, con su ``-wal`` o su ``-journal``, a la
carpeta de importación de la caché del proyecto (:func:`import_dir`:
``Project.cache_dir()/import/<operación>/``, en disco local también con el proyecto en red),
lo consolida allí en diario clásico y comprueba su integridad (``core.gpkg.private_copy`` de
la 002); la carpeta de la fuente queda como estaba.

Sobre la copia:

- :func:`list_layers`: las capas vectoriales (:class:`LayerInfo`) con su tipo de geometría,
  Z y M (0 prohibida, 1 obligatoria, 2 opcional), SRS, número de entidades y campos. Una capa
  de curvas o colecciones, o en un CRS EPSG fuera del catálogo, no se puede importar
  (``problem``); una sin SRS EPSG, sí, pero sin CRS declarado: lo declara el usuario
  (RF-006-04).
- :func:`read_layer`: sus entidades (:class:`FeatureSet`) con las coordenadas ABSOLUTAS de
  cada geometría en float64, bit a bit (cabecera ``GP``, WKB ISO o EWKB, *little* o *big
  endian*; ``core.gpkg.decode_geometry(..., external=True)``), la M descartada con aviso,
  las vacías o nulas omitidas con aviso y las que no se pueden leer (curvas, colecciones,
  otro SRS) rechazadas con su número de entidad y su motivo.

El papel que declara el usuario (puntos, líneas de rotura) lo aplica ``gis.points``; el de
«dominios» (spec 011, T18; D-32), :func:`domains_from_features`: de cada Polygon o MultiPolygon,
su número, sus anillos y sus atributos (:class:`DomainSet`), con los campos de texto, enteros
y reales de la capa como columnas de la tabla del proyecto (:func:`field_columns`); el de
«entidades» (spec 012, T07; D-27), :func:`features_from_layer`: puntos, líneas o polígonos en
planta con sus atributos (:class:`FeatureLayer`), llevados al CRS del proyecto con
:func:`transform_features` si la capa está en otro.

**Entregables** (T31; RF-006-25; plan §5.3.2 y A18; D15): :func:`write_layers` escribe capas
(:class:`LayerToWrite`: puntos, líneas de rotura, curvas, contornos o un TIN como triángulos,
:func:`tin_layer`) en un GeoPackage nuevo con el CRS del proyecto: un temporal (``<destino>.tmp``
o el que da quien llama) en diario clásico (``DELETE``, ``core.gpkg``), una tabla por capa con el
nombre base del tipo de GeoPackage 1.4 y ``z = 1`` si lleva Z, la referencia vertical citada en
su descripción (:func:`z_description`) y su extensión, las filas por lotes de :data:`BATCH_ROWS`
(con avance y cancelación entre lotes), el índice R*Tree de cada capa (:data:`RTREE_EXTENSION`,
con los disparadores de GeoPackage 1.4) y el renombrado. Cada coordenada, la misma en float64
(``core.gpkg.encode_geometry``). Un destino abierto por otro programa es
``gis.raster_target_locked`` sin fichero a medias, como en los GeoTIFF. :class:`StoredLayer`:
las filas de una tabla del proyecto tal como están guardadas, que el trabajo de exportación
descodifica (:meth:`StoredLayer.decoded`). Una capa con estilo (``gis.styles.LayerStyle``: las
curvas de nivel, T55) lo lleva en la tabla ``layer_styles`` (:data:`STYLES_TABLE`), con el
esquema con que la crea QGIS 4.2 y como su estilo por defecto: QGIS lo aplica al añadir la capa.
"""

from __future__ import annotations

import os
import re
import sqlite3
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import numpy as np

from ..core.errors import DatabaseError, GeometryError, ValidationError
from ..core.georef import CrsCatalog, CrsRef, VerticalRef, load_catalog
from ..core.gpkg import Geometry, GpkgConnection, decode_geometry, private_copy, read_header
from ..core.gpkg.base import ColumnDef, create_base, create_feature_table
from ..core.gpkg.header import side_file
from ..core.gpkg.wkb import encode_geometry
from ..core.paths import check_path_length
from ..jobs.worker_api import JobCancelled
from .geotiff.writer import target_locked
from .messages import GisError, render
from .reports import Rejection, TopoReport
from .styles import LayerStyle

if TYPE_CHECKING:
    from .ports import Transform
    from .tin import Tin

IMPORT_DIR = "import"
"""Subcarpeta de la caché del proyecto con las copias de las fuentes SQLite (plan §5.2.6)."""

SUPPORTED_TYPES: tuple[str, ...] = (
    "POINT", "LINESTRING", "POLYGON", "MULTIPOINT", "MULTILINESTRING", "MULTIPOLYGON",
    "GEOMETRY",
)
"""Tipos de geometría de una capa que se leen (``GEOMETRY``: cualquiera, entidad a entidad)."""

_OPERATION_UID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", re.ASCII)
_EMPTY = "core.geometry_empty"
_LAYERS_SQL = (
    "SELECT c.table_name, COALESCE(c.identifier, ''), g.column_name, "
    "g.geometry_type_name, g.srs_id, g.z, g.m, s.organization, "
    "s.organization_coordsys_id, s.srs_name "
    "FROM gpkg_contents AS c "
    "JOIN gpkg_geometry_columns AS g ON g.table_name = c.table_name "
    "LEFT JOIN gpkg_spatial_ref_sys AS s ON s.srs_id = g.srs_id "
    "WHERE lower(c.data_type) = 'features'"
)


@dataclass(frozen=True, slots=True)
class LayerInfo:
    """Una capa vectorial de un GeoPackage: fichero, nombre (la tabla) e identificador;
    tipo de geometría (nombre de GeoPackage en mayúsculas), su columna y la del número de
    entidad (``""`` si la tabla no tiene clave entera); Z y M de
    ``gpkg_geometry_columns``; SRS (``"EPSG:25830"`` o su nombre) y el CRS del catálogo que
    declara (``None`` si no es EPSG: lo declara el usuario); entidades; campos (nombre y
    tipo, sin la clave ni la geometría). ``problem``: por qué no se puede importar (texto
    en español) o ``None``; ``notes``: avisos."""

    file: str
    name: str
    identifier: str
    geometry_type: str
    geometry_column: str
    fid_column: str
    z: int
    m: int
    srs_id: int
    srs: str
    declared_crs: CrsRef | None
    features: int
    fields: tuple[tuple[str, str], ...]
    problem: str | None = None
    notes: tuple[str, ...] = ()

    @property
    def importable(self) -> bool:
        """Verdadero si la capa se puede importar."""
        return self.problem is None


@dataclass(frozen=True, slots=True, eq=False)
class FeatureSet:
    """Las entidades leídas de una capa: su número (``fids``), su geometría (coordenadas
    ABSOLUTAS en float64, sin M) y sus atributos (por campo, en el mismo orden), con el
    informe de la lectura (``read`` = entidades de la tabla; rechazos y avisos). Las
    entidades omitidas o rechazadas no están."""

    layer: LayerInfo
    fids: tuple[int, ...]
    geometries: tuple[Geometry, ...]
    attributes: Mapping[str, tuple[Any, ...]]
    report: TopoReport

    def __len__(self) -> int:
        return len(self.fids)


@dataclass(frozen=True, slots=True)
class _Problem:
    code: str
    field: str
    value: object


def import_dir(cache_dir: Path, operation_uid: str) -> Path:
    """``<caché>/import/<operation_uid>/``: la carpeta de las copias de una importación.
    ``operation_uid`` es un nombre (letras, cifras, ``_``, ``-`` y ``.``), nunca una ruta:
    si no, ``ValueError``."""
    if not isinstance(operation_uid, str) or not _OPERATION_UID.fullmatch(operation_uid):
        raise ValueError(f"identificador de operación no válido: {operation_uid!r}")
    return Path(cache_dir) / IMPORT_DIR / operation_uid


def copy_source(source: Path, target_dir: Path) -> Path:
    """Copia el GeoPackage ``source`` (con su ``-wal`` o su ``-journal``) a ``target_dir``,
    la consolida en diario clásico y devuelve la ruta de la copia (RF-006-10).

    ``source`` y su carpeta no cambian. :class:`GisError` ``gis.gpkg_unreadable`` si no
    existe, no es una base SQLite o no se obtiene una copia íntegra (otro programa la
    escribe); ``ValueError`` si ``source`` ya está en ``target_dir`` (la copia la borraría).
    """
    source, target_dir = Path(source), Path(target_dir)
    target = target_dir / source.name
    if target.exists() and source.exists() and os.path.samefile(source, target):
        raise ValueError(f"«{source}» ya está en la carpeta de importación: no se copia")
    if not source.is_file():
        raise _unreadable(source.name, "no existe; compruebe la ruta")
    try:
        read_header(source)
        return private_copy(source, target_dir)
    except DatabaseError as error:
        raise _unreadable(source.name, error.reason) from error


def _unreadable(name: str, detail: str) -> GisError:
    return GisError("gis.gpkg_unreadable", obj=name, field="fichero", value=name,
                    file=name, detail=detail)


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _describe(
    conn: sqlite3.Connection, file: str, row: tuple[Any, ...], catalog: CrsCatalog
) -> tuple[LayerInfo, _Problem | None]:
    """La :class:`LayerInfo` de una fila de :data:`_LAYERS_SQL` y su problema, si lo hay."""
    name, identifier, column, kind, srs_id, z, m, organization, code, srs_name = row
    kind = str(kind).upper()
    table = conn.execute(f"PRAGMA table_info({_quote(name)})").fetchall()
    keys = [c[1] for c in table if c[5] == 1 and str(c[2]).upper() == "INTEGER"]
    fid_column = keys[0] if len(keys) == 1 else ""
    fields = tuple(
        (str(c[1]), str(c[2])) for c in table if c[1] not in (fid_column, column)
    )
    features = int(conn.execute(f"SELECT count(*) FROM {_quote(name)}").fetchone()[0])
    declared: CrsRef | None = None
    notes: tuple[str, ...] = ()
    problem: _Problem | None = None
    if str(organization or "").upper() == "EPSG" and isinstance(code, int):
        srs = f"EPSG:{code}"
        try:
            declared = catalog.horizontal(code)
        except ValidationError:
            problem = _Problem("gis.layer_crs_unsupported", "SRS", srs)
    else:
        srs = str(srs_name) if srs_name else f"SRS {srs_id}"
        notes = (render("gis.layer_crs_undeclared", layer=name, file=file, value=srs),)
    if kind not in SUPPORTED_TYPES:
        problem = _Problem("gis.layer_geometry_unsupported", "tipo de geometría", kind)
    info = LayerInfo(
        file=file,
        name=str(name),
        identifier=str(identifier),
        geometry_type=kind,
        geometry_column=str(column),
        fid_column=fid_column,
        z=int(z),
        m=int(m),
        srs_id=int(srs_id),
        srs=srs,
        declared_crs=declared,
        features=features,
        fields=fields,
        problem=None if problem is None else render(
            problem.code, layer=name, file=file, value=problem.value
        ),
        notes=notes,
    )
    return info, problem


def _open(path: Path) -> GpkgConnection:
    try:
        return GpkgConnection.open_read(path)
    except DatabaseError as error:
        raise _unreadable(path.name, error.reason) from error


def list_layers(gpkg_copy: Path, *, catalog: CrsCatalog | None = None) -> list[LayerInfo]:
    """Las capas vectoriales de la copia ``gpkg_copy`` (:func:`copy_source`), por orden
    alfabético (RF-006-12); ``catalog``: el de CRS (por defecto, el de Geoblender).
    :class:`GisError` ``gis.gpkg_unreadable`` si no es un GeoPackage legible."""
    path = Path(gpkg_copy)
    catalog = load_catalog() if catalog is None else catalog
    with _open(path) as gpkg:
        try:
            rows = gpkg.connection.execute(_LAYERS_SQL).fetchall()
            layers = [_describe(gpkg.connection, path.name, row, catalog)[0] for row in rows]
        except sqlite3.Error as error:
            raise _unreadable(path.name, str(error)) from error
    return sorted(layers, key=lambda info: (info.name.casefold(), info.name))


def _detail(error: GeometryError) -> str:
    return f"{error.field} = {error.shown}: {error.reason}"


def read_layer(
    gpkg_copy: Path, layer: str, *, catalog: CrsCatalog | None = None
) -> FeatureSet:
    """Las entidades de la capa ``layer`` de la copia ``gpkg_copy`` (RF-006-12), en el
    orden de su número de entidad.

    :class:`GisError`: ``gis.layer_not_found`` si no hay tal capa vectorial,
    ``gis.layer_geometry_unsupported`` o ``gis.layer_crs_unsupported`` si no se puede
    importar, ``gis.gpkg_unreadable`` si la base no se puede leer.
    """
    path = Path(gpkg_copy)
    catalog = load_catalog() if catalog is None else catalog
    with _open(path) as gpkg:
        conn = gpkg.connection
        try:
            row = conn.execute(_LAYERS_SQL + " AND c.table_name = ?", (layer,)).fetchone()
            if row is None:
                raise GisError("gis.layer_not_found", obj=path.name, field="capa",
                               value=layer, file=path.name)
            info, problem = _describe(conn, path.name, row, catalog)
            if problem is not None:
                raise GisError(problem.code, obj=f"{path.name} ▸ {info.name}",
                               field=problem.field, value=problem.value, layer=info.name,
                               file=path.name)
            return _read(conn, info)
        except sqlite3.Error as error:
            raise _unreadable(path.name, str(error)) from error


def _read(conn: sqlite3.Connection, info: LayerInfo) -> FeatureSet:
    names = [name for name, _kind in info.fields]
    fid_sql = _quote(info.fid_column) if info.fid_column else "NULL"
    order = f" ORDER BY {fid_sql}" if info.fid_column else ""
    columns = ", ".join([fid_sql, _quote(info.geometry_column), *map(_quote, names)])
    sql = f"SELECT {columns} FROM {_quote(info.name)}{order}"
    fids: list[int] = []
    geometries: list[Geometry] = []
    values: dict[str, list[Any]] = {name: [] for name in names}
    rejected: list[Rejection] = []
    read = omitted = 0
    had_m = False

    def reject(fid: int, code: str, **extra: object) -> None:
        text = render(code, layer=info.name, file=info.file, row=fid, **extra)
        rejected.append(Rejection(fid, text, code))

    for fid_value, blob, *attributes in conn.execute(sql):
        read += 1
        fid = read if fid_value is None else int(fid_value)
        if blob is None:
            omitted += 1
            continue
        if not isinstance(blob, bytes | bytearray | memoryview):
            reject(fid, "gis.feature_geometry_invalid", detail="no es una geometría binaria")
            continue
        try:
            geometry = decode_geometry(bytes(blob), external=True)
        except GeometryError as error:
            if error.code == _EMPTY:
                omitted += 1
            else:
                reject(fid, "gis.feature_geometry_invalid", detail=_detail(error))
            continue
        if geometry.srs_id != info.srs_id:
            reject(fid, "gis.feature_srs_mismatch", value=geometry.srs_id,
                   expected=info.srs_id)
            continue
        had_m = had_m or geometry.had_m
        fids.append(fid)
        geometries.append(geometry)
        for name, value in zip(names, attributes, strict=True):
            values[name].append(value)
    warnings: list[str] = []
    if had_m:
        warnings.append(render("gis.m_discarded", layer=info.name))
    if omitted:
        warnings.append(render("gis.features_without_geometry", layer=info.name,
                               file=info.file, value=omitted))
    report = TopoReport(
        source=f"{info.file} ▸ {info.name}",
        read=read,
        rejected=tuple(rejected),
        warnings=tuple(warnings),
    )
    return FeatureSet(
        layer=info,
        fids=tuple(fids),
        geometries=tuple(geometries),
        attributes=MappingProxyType({k: tuple(v) for k, v in values.items()}),
        report=report,
    )


# --- Entregables (T31; RF-006-25; plan A18) ----------------------------------------------------

EXPORT_TYPES: tuple[str, ...] = ("POINT", "LINESTRING", "POLYGON", "MULTIPOLYGON")
"""Los tipos de geometría de una capa entregable (nombre base de GeoPackage 1.4, D15)."""
BATCH_ROWS = 5_000
"""Filas que se insertan de una vez (entre dos lotes, el avance y la cancelación)."""
TEMPORARY_SUFFIX = ".tmp"
RTREE_EXTENSION = "gpkg_rtree_index"
"""La extensión del índice espacial de GeoPackage, en ``gpkg_extensions`` (``write-only``)."""
RTREE_DEFINITION = "http://www.geopackage.org/spec120/#extension_rtree"
GEOMETRY_COLUMN = "geom"
_FIELD_TARGET = "destino"
STYLES_TABLE = "layer_styles"
"""La tabla de los estilos de QGIS de un GeoPackage (la que QGIS lee al añadir una capa)."""
# Como la crea QGIS 4.2 al guardar un estilo en un GeoPackage (comprobado con PyQGIS 4.2.0).
_STYLES_DDL = (
    f'CREATE TABLE "{STYLES_TABLE}" ( "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, '
    '"f_table_catalog" TEXT(256), "f_table_schema" TEXT(256), "f_table_name" TEXT(256), '
    '"f_geometry_column" TEXT(256), "styleName" TEXT(30), "styleQML" TEXT, "styleSLD" TEXT, '
    '"useAsDefault" BOOLEAN, "description" TEXT, "owner" TEXT(30), "ui" TEXT(30), '
    '"update_time" DATETIME DEFAULT (strftime(\'%Y-%m-%dT%H:%M:%fZ\',\'now\')))'
)
_STYLES_INSERT = (
    f'INSERT INTO "{STYLES_TABLE}" (f_table_catalog, f_table_schema, f_table_name, '
    "f_geometry_column, styleName, styleQML, styleSLD, useAsDefault, description, owner) "
    "VALUES ('', '', ?, ?, ?, ?, '', 1, ?, '')"
)

# Los disparadores del índice R*Tree de GeoPackage 1.4 (anexo F.3; los que comprueba el
# validate_gpkg.py de GDAL): {t} la tabla, {c} la columna de geometría, {i} la clave y {r} el
# índice.
_NEW_BOX = ('VALUES (NEW."{i}", ST_MinX(NEW."{c}"), ST_MaxX(NEW."{c}"), ST_MinY(NEW."{c}"), '
            'ST_MaxY(NEW."{c}"))')
_NEW_FULL = '(NEW."{c}" NOTNULL AND NOT ST_IsEmpty(NEW."{c}"))'
_NEW_EMPTY = '(NEW."{c}" ISNULL OR ST_IsEmpty(NEW."{c}"))'
_RTREE_TRIGGERS: tuple[tuple[str, str], ...] = (
    ("insert", 'AFTER INSERT ON "{t}" WHEN (new."{c}" NOT NULL AND NOT ST_IsEmpty(NEW."{c}")) '
               'BEGIN INSERT OR REPLACE INTO "{r}" ' + _NEW_BOX + "; END"),
    ("update6", 'AFTER UPDATE OF "{c}" ON "{t}" WHEN OLD."{i}" = NEW."{i}" AND ' + _NEW_FULL
                + ' AND (OLD."{c}" NOTNULL AND NOT ST_IsEmpty(OLD."{c}")) BEGIN UPDATE "{r}" '
                'SET minx = ST_MinX(NEW."{c}"), maxx = ST_MaxX(NEW."{c}"), '
                'miny = ST_MinY(NEW."{c}"), maxy = ST_MaxY(NEW."{c}") WHERE id = NEW."{i}"; END'),
    ("update7", 'AFTER UPDATE OF "{c}" ON "{t}" WHEN OLD."{i}" = NEW."{i}" AND ' + _NEW_FULL
                + ' AND (OLD."{c}" ISNULL OR ST_IsEmpty(OLD."{c}")) BEGIN INSERT INTO "{r}" '
                + _NEW_BOX + "; END"),
    ("update2", 'AFTER UPDATE OF "{c}" ON "{t}" WHEN OLD."{i}" = NEW."{i}" AND ' + _NEW_EMPTY
                + ' BEGIN DELETE FROM "{r}" WHERE id = OLD."{i}"; END'),
    ("update5", 'AFTER UPDATE ON "{t}" WHEN OLD."{i}" != NEW."{i}" AND ' + _NEW_FULL
                + ' BEGIN DELETE FROM "{r}" WHERE id = OLD."{i}"; INSERT OR REPLACE INTO "{r}" '
                + _NEW_BOX + "; END"),
    ("update4", 'AFTER UPDATE ON "{t}" WHEN OLD."{i}" != NEW."{i}" AND ' + _NEW_EMPTY
                + ' BEGIN DELETE FROM "{r}" WHERE id IN (OLD."{i}", NEW."{i}"); END'),
    ("delete", 'AFTER DELETE ON "{t}" WHEN old."{c}" NOT NULL '
               'BEGIN DELETE FROM "{r}" WHERE id = OLD."{i}"; END'),
)


def z_description(vertical: VerticalRef) -> str:
    """Cómo se cita la referencia de las Z de una capa en ``gpkg_contents.description`` (plan
    §5.2.3): «Z en <nombre> (EPSG:n)», la elipsoidal por su nombre y una referencia local con
    su nota."""
    if vertical.epsg is not None:
        return f"Z en {vertical.name} (EPSG:{vertical.epsg})"
    if vertical.kind == "ellipsoidal":
        return f"Z en {vertical.name}"
    return f"Z referidas a «{vertical.note}» ({vertical.name})"


def _structure(geometry_type: str, coords: Any) -> Any:
    """``coords`` con la estructura de ``core.gpkg.wkb`` para ``geometry_type`` (arrays de
    numpy; los anillos y los polígonos, en listas), sin copiar lo que ya es un array."""
    if geometry_type in ("POINT", "LINESTRING"):
        return np.asarray(coords)
    if geometry_type == "POLYGON":
        return [np.asarray(ring) for ring in coords]
    return [[np.asarray(ring) for ring in polygon] for polygon in coords]


def _vertices(geometry_type: str, coords: Any) -> np.ndarray:
    """Todos los vértices de una geometría de :func:`_structure`, en filas."""
    if geometry_type in ("POINT", "LINESTRING"):
        return coords.reshape(-1, coords.shape[-1])
    if geometry_type == "POLYGON":
        return np.vstack(coords)
    return np.vstack([ring for polygon in coords for ring in polygon])


@dataclass(frozen=True, slots=True, eq=False)
class LayerToWrite:
    """Una capa de un GeoPackage entregable (RF-006-25): ``name``, su tabla (un identificador
    de GeoPackage en minúsculas); ``geometry_type``, uno de :data:`EXPORT_TYPES`; ``has_z``;
    ``geometries``, las coordenadas ABSOLUTAS en float64 de cada entidad con la estructura de
    ``core.gpkg.wkb`` (un punto ``(d,)``, una línea ``(n, d)``, un polígono su lista de anillos
    cerrados, un multipolígono su lista de polígonos); ``columns`` (``core.gpkg.ColumnDef``) y
    ``values``, por columna, un valor por entidad (``None``, texto, entero o número; un
    ``BOOLEAN``, 0 o 1); ``identifier`` (``gpkg_contents``; vacío: el nombre),
    ``description`` (vacía: el identificador) y ``style``, su estilo de QGIS por defecto
    (``gis.styles.LayerStyle``) o ``None``. ``ValueError`` o ``TypeError`` si no lo cumple
    (un error del programa)."""

    name: str
    geometry_type: str
    has_z: bool
    geometries: Sequence[Any]
    columns: tuple[ColumnDef, ...] = ()
    values: Mapping[str, Sequence[Any]] = field(default_factory=dict)
    identifier: str = ""
    description: str = ""
    style: LayerStyle | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError(f"el nombre de una capa es un texto no vacío, no {self.name!r}")
        kind = str(self.geometry_type).upper()
        if kind not in EXPORT_TYPES:
            raise ValueError(f"tipo de geometría {self.geometry_type!r} de la capa «{self.name}»: "
                             f"es uno de {', '.join(EXPORT_TYPES)}")
        object.__setattr__(self, "geometry_type", kind)
        if not isinstance(self.has_z, bool):
            raise TypeError(f"«has_z» es verdadero o falso, no {self.has_z!r}")
        object.__setattr__(self, "geometries", tuple(self.geometries))
        columns = tuple(self.columns)
        if not all(isinstance(column, ColumnDef) for column in columns):
            raise TypeError(f"las columnas de «{self.name}» son ColumnDef de core.gpkg")
        object.__setattr__(self, "columns", columns)
        names = [column.name for column in columns]
        if set(self.values) != set(names):
            raise ValueError(f"la capa «{self.name}» da valores de {sorted(self.values)} y sus "
                             f"columnas son {names}")
        count = len(self.geometries)
        values: dict[str, tuple[Any, ...]] = {}
        for column in names:
            found = tuple(self.values[column])
            if len(found) != count:
                raise ValueError(f"la columna «{column}» de «{self.name}» tiene {len(found)} "
                                 f"valores y la capa {count} entidades")
            values[column] = found
        object.__setattr__(self, "values", MappingProxyType(values))
        for text in ("identifier", "description"):
            if not isinstance(getattr(self, text), str):
                raise TypeError(f"«{text}» de una capa es un texto")
        if self.style is not None and not isinstance(self.style, LayerStyle):
            raise TypeError(f"el estilo de «{self.name}» es un LayerStyle de gis.styles o "
                            f"None, no {self.style!r}")


@dataclass(frozen=True, slots=True, eq=False)
class StoredLayer:
    """Una tabla del proyecto para exportarla tal como está guardada: el nombre con que se
    exporta, su tipo, Z y columnas, las geometrías de sus filas codificadas (cabecera ``GP`` +
    WKB, ``blobs``) y los valores de cada columna; ``identifier`` y ``description`` como en
    :class:`LayerToWrite`, y su estilo (``style``). Así ``bl`` la lee del proyecto sin
    descodificarla y el trabajo de exportación la descodifica (:meth:`decoded`)."""

    name: str
    geometry_type: str
    has_z: bool
    columns: tuple[ColumnDef, ...]
    blobs: tuple[bytes, ...]
    values: Mapping[str, Sequence[Any]]
    identifier: str = ""
    description: str = ""
    style: LayerStyle | None = None

    def decoded(self, srs_id: int) -> LayerToWrite:
        """La capa con las coordenadas de cada fila (``core.gpkg.decode_geometry``, bit a
        bit). ``ValueError`` si una fila no es de ``srs_id`` o no es de su tipo y su Z."""
        geometries: list[Any] = []
        kind = str(self.geometry_type).upper()
        for index, blob in enumerate(self.blobs, start=1):
            geometry = decode_geometry(bytes(blob))
            if geometry.srs_id != srs_id:
                raise ValueError(f"la fila {index} de «{self.name}» es del SRS {geometry.srs_id}, "
                                 f"no del {srs_id} de la exportación")
            if (geometry.geometry_type, geometry.has_z) != (kind, self.has_z):
                raise ValueError(f"la fila {index} de «{self.name}» es un "
                                 f"{geometry.geometry_type} (Z: {geometry.has_z}), no un {kind} "
                                 f"(Z: {self.has_z})")
            geometries.append(geometry.coords)
        return LayerToWrite(self.name, kind, self.has_z, geometries, tuple(self.columns),
                            dict(self.values), self.identifier, self.description, self.style)


def tin_layer(tin: Tin, name: str, *, identifier: str = "", description: str = "") -> LayerToWrite:
    """El TIN ``tin`` como capa de triángulos (RF-006-25; plan A18): un ``POLYGON`` con Z por
    triángulo, su anillo cerrado con sus tres vértices (los del TIN, ABSOLUTOS, bit a bit) en
    el orden de la cara (antihorario visto desde arriba)."""
    rings = tin.vertices[np.column_stack([tin.faces, tin.faces[:, :1]])]
    return LayerToWrite(name, "POLYGON", True, [[ring] for ring in rings],
                        identifier=identifier, description=description)


def _check_layers(layers: Sequence[LayerToWrite]) -> list[LayerToWrite]:
    chosen = list(layers)
    if not chosen:
        raise ValueError("un GeoPackage entregable lleva al menos una capa")
    seen: set[str] = set()
    labels: set[str] = set()
    for layer in chosen:
        if not isinstance(layer, LayerToWrite):
            raise TypeError(f"una capa entregable es un LayerToWrite, no {type(layer).__name__}")
        key = layer.name.casefold()
        label = layer.identifier or layer.name
        if key == STYLES_TABLE:
            raise ValueError(f"«{layer.name}» es la tabla de los estilos de QGIS: no es una capa")
        if key in seen or label in labels:
            raise ValueError(f"la capa «{layer.name}» ({label}) se repite: cada capa, con su "
                             "nombre y su identificador")
        seen.add(key)
        labels.add(label)
    return chosen


def _failed(name: str, detail: str) -> GisError:
    return GisError("gis.raster_write_failed", obj=name, field=_FIELD_TARGET, value=name,
                    file=name, detail=detail)


def _discard(*paths: Path) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def write_layers(
    path: Path | str,
    layers: Sequence[LayerToWrite],
    crs: CrsRef,
    vertical: VerticalRef,
    *,
    temporary: Path | str | None = None,
    replace: bool = True,
    progress: Callable[[float, str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> Path:
    """Escribe ``layers`` en el GeoPackage nuevo ``path`` (RF-006-25; plan A18; véase el
    módulo), con el CRS horizontal ``crs`` y la referencia vertical ``vertical`` citada en la
    descripción de cada capa con Z. ``temporary``: el temporal (por defecto
    ``<destino>.tmp``); con ``replace=False`` el fichero queda entero en él y ``path`` no se
    toca. Las capas con estilo lo llevan en ``layer_styles`` como su estilo por defecto
    (:func:`_write_styles`). Devuelve lo escrito: ``path`` o, sin ``replace``, el temporal.
    Nunca un fichero a medias: si algo falla o ``cancelled()`` pide parar entre lotes (``JobCancelled``), el
    temporal se borra y el destino anterior sigue intacto. ``GisError``
    ``gis.raster_target_locked`` si otro programa tiene abierto el destino y
    ``gis.raster_write_failed`` si falla el disco; ``ValueError``/``TypeError`` con una capa
    mal declarada (sin escribir nada)."""
    if not isinstance(crs, CrsRef) or not isinstance(vertical, VerticalRef):
        raise TypeError("el CRS y la referencia vertical son un CrsRef y un VerticalRef")
    if not isinstance(replace, bool):
        raise TypeError(f"«replace» es verdadero o falso, no {replace!r}")
    chosen = _check_layers(layers)
    path = Path(path)
    name = path.name
    temporary = (path.with_name(path.name + TEMPORARY_SUFFIX) if temporary is None
                 else Path(temporary))
    if temporary == path:
        raise ValueError(f"el temporal de «{name}» no puede ser el propio destino")
    journal = side_file(temporary, "-journal")
    check_path_length(journal, obj=name)
    _discard(temporary, journal)  # un resto de una exportación interrumpida
    total = max(1, sum(len(layer.geometries) for layer in chosen))
    done = 0

    def advance(count: int, layer: LayerToWrite) -> None:
        nonlocal done
        done += count
        if progress is not None:
            progress(min(done / total, 1.0),
                     f"Escribiendo «{name}»: capa {layer.name}, {done} de {total} entidades")

    try:
        with GpkgConnection.open_write(temporary, create=True) as gpkg:
            with gpkg.transaction() as conn:
                create_base(conn, crs)
                for layer in chosen:
                    _write_layer(conn, layer, crs, vertical, cancelled, advance)
                _write_styles(conn, chosen)
    except BaseException as error:
        _discard(temporary, journal)
        if isinstance(error, OSError):
            raise _failed(name, error.strerror or str(error)) from None
        if isinstance(error, sqlite3.Error | DatabaseError):
            raise _failed(name, str(error)) from None
        raise
    if progress is not None:
        progress(1.0, f"Escrito «{name}»")
    if not replace:
        return temporary
    try:
        os.replace(temporary, path)
    except OSError as error:
        _discard(temporary)
        if isinstance(error, PermissionError):  # Windows: otro programa lo tiene abierto
            raise target_locked(name) from None
        raise _failed(name, error.strerror or str(error)) from None
    return path


def _write_layer(
    conn: sqlite3.Connection,
    layer: LayerToWrite,
    crs: CrsRef,
    vertical: VerticalRef,
    cancelled: Callable[[], bool] | None,
    advance: Callable[[int, LayerToWrite], None],
) -> None:
    """Una capa en la transacción ``conn``: su tabla, sus filas por lotes, su extensión y su
    índice R*Tree."""
    identifier = layer.identifier or layer.name
    description = layer.description or identifier
    if layer.has_z:
        description = f"{description}; {z_description(vertical)}"
    create_feature_table(conn, layer.name, layer.geometry_type, crs.epsg, layer.has_z,
                         layer.columns, identifier, description)
    names = [column.name for column in layer.columns]
    insert = (f'INSERT INTO "{layer.name}" (fid, {GEOMETRY_COLUMN}'
              f'{"".join(f", {_quote(column)}" for column in names)}) '
              f'VALUES ({", ".join("?" for _ in range(len(names) + 2))})')
    count = len(layer.geometries)
    boxes = np.empty((count, 4), dtype=np.float64)
    for start in range(0, count, BATCH_ROWS):
        if cancelled is not None and cancelled():
            raise JobCancelled(f"Cancelado al escribir la capa «{layer.name}» en la entidad "
                               f"{start + 1} de {count}")
        rows: list[tuple[Any, ...]] = []
        for index in range(start, min(start + BATCH_ROWS, count)):
            coords = _structure(layer.geometry_type, layer.geometries[index])
            blob = encode_geometry(layer.geometry_type, coords, crs.epsg, layer.has_z)
            points = _vertices(layer.geometry_type, coords)
            boxes[index] = (points[:, 0].min(), points[:, 0].max(), points[:, 1].min(),
                            points[:, 1].max())
            rows.append((index + 1, blob, *(_plain(layer.values[column][index])
                                            for column in names)))
        conn.executemany(insert, rows)
        advance(len(rows), layer)
    if count:
        conn.execute("UPDATE gpkg_contents SET min_x = ?, min_y = ?, max_x = ?, max_y = ? "
                     "WHERE table_name = ?",
                     (float(boxes[:, 0].min()), float(boxes[:, 2].min()),
                      float(boxes[:, 1].max()), float(boxes[:, 3].max()), layer.name))
    _rtree(conn, layer.name, boxes)


def _write_styles(conn: sqlite3.Connection, layers: Sequence[LayerToWrite]) -> None:
    """Los estilos de ``layers`` en la tabla ``layer_styles`` (:data:`STYLES_TABLE`), con el
    esquema y los valores que escribe QGIS 4.2 al guardar el estilo por defecto de una capa
    de un GeoPackage (sin catálogo ni esquema, con la tabla y la columna de geometría de la
    capa y ``useAsDefault = 1``), registrada en ``gpkg_contents`` como ``attributes``. Sin
    ninguna capa con estilo, no se crea."""
    rows = [(layer.name, GEOMETRY_COLUMN, layer.style.name, layer.style.qml,
             layer.style.description) for layer in layers if layer.style is not None]
    if not rows:
        return
    conn.execute(_STYLES_DDL)
    conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, description) "
                 "VALUES (?, 'attributes', ?, '')", (STYLES_TABLE, STYLES_TABLE))
    conn.executemany(_STYLES_INSERT, rows)


def _plain(value: Any) -> Any:
    """Un valor de una columna como lo guarda SQLite (los de numpy, en su tipo de Python)."""
    if isinstance(value, np.generic):
        return value.item()
    return value


def _rtree(conn: sqlite3.Connection, table: str, boxes: np.ndarray) -> None:
    """El índice R*Tree de la capa ``table`` (extensión ``gpkg_rtree_index`` de GeoPackage):
    su tabla virtual con la caja de cada entidad, declarada ``write-only``, y sus disparadores
    (mantienen el índice si QGIS edita la capa; se crean tras llenarlo, porque necesitan las
    funciones ``ST_*`` de GDAL)."""
    rtree = f"rtree_{table}_{GEOMETRY_COLUMN}"
    conn.execute(f'CREATE VIRTUAL TABLE "{rtree}" USING rtree(id, minx, maxx, miny, maxy)')
    conn.executemany(f'INSERT INTO "{rtree}" VALUES (?, ?, ?, ?, ?)',
                     ((index + 1, *box) for index, box in enumerate(boxes.tolist())))
    for suffix, body in _RTREE_TRIGGERS:
        sql = body.format(t=table, c=GEOMETRY_COLUMN, i="fid", r=rtree)
        conn.execute(f'CREATE TRIGGER "{rtree}_{suffix}" {sql}')
    conn.execute("INSERT INTO gpkg_extensions (table_name, column_name, extension_name, "
                 "definition, scope) VALUES (?, ?, ?, ?, 'write-only')",
                 (table, GEOMETRY_COLUMN, RTREE_EXTENSION, RTREE_DEFINITION))


# --- Capa de dominios (spec 011, T18; RF-011-07; plan 011 D-32) ---------------------------------

DOMAIN_TYPES: tuple[str, ...] = ("POLYGON", "MULTIPOLYGON")
"""Las geometrías de una entidad de una capa de dominios (otra se rechaza con su número)."""
DOMAIN_COLUMN_TYPES: tuple[str, ...] = ("TEXT", "INTEGER", "DOUBLE")
"""Los tipos de las columnas de los atributos de una capa de dominios en el proyecto."""
COLUMN_CHARS = 63
"""El largo máximo del nombre de una columna (un identificador de ``core.gpkg``)."""
_SPECIAL_TYPES: Mapping[str, str] = MappingProxyType(
    {"BOOLEAN": "INTEGER", "DATE": "TEXT", "DATETIME": "TEXT"})
_TYPE_SIZE = re.compile(r"\s*\(.*\)\s*$")
_NON_COLUMN = re.compile(r"[^a-z0-9]+")
_RESERVED_COLUMNS = frozenset({"fid", GEOMETRY_COLUMN})
_BINARY = (bytes, bytearray, memoryview)


@dataclass(frozen=True, slots=True)
class FieldColumn:
    """Un campo de una capa de dominios como columna de su tabla en el proyecto: su nombre en
    la capa (``field``, tal cual: el título de la columna), su columna (``column``: un
    identificador de GeoPackage en minúsculas, :func:`column_name`) y su tipo (``sql_type``,
    uno de :data:`DOMAIN_COLUMN_TYPES`)."""

    field: str
    column: str
    sql_type: str

    def __post_init__(self) -> None:
        if self.sql_type not in DOMAIN_COLUMN_TYPES:
            raise ValueError(f"el tipo de la columna «{self.column}» es uno de "
                             f"{', '.join(DOMAIN_COLUMN_TYPES)}, no {self.sql_type!r}")


def column_type(declared: str) -> str | None:
    """El tipo de la columna de un campo declarado como ``declared`` en su capa (por la
    afinidad de SQLite y los nombres de GeoPackage): ``INTEGER`` (los enteros, como el
    ``MEDIUMINT`` de QGIS, y el lógico), ``TEXT`` (el texto, con o sin largo, y las fechas) o
    ``DOUBLE`` (los reales y los numéricos); ``None`` si es binario o no declara tipo (no se
    importa)."""
    kind = _TYPE_SIZE.sub("", str(declared)).strip().upper()
    if kind in _SPECIAL_TYPES:
        return _SPECIAL_TYPES[kind]
    if "INT" in kind:
        return "INTEGER"
    if any(text in kind for text in ("CHAR", "CLOB", "TEXT")):
        return "TEXT"
    if not kind or "BLOB" in kind:
        return None
    return "DOUBLE"


def column_name(field_name: str, taken: Iterable[str] = ()) -> str:
    """El nombre de la columna del campo ``field_name``: en minúsculas, sin tildes y con un «_»
    por cada tramo que no es una letra o una cifra ASCII (un nombre ya así no cambia), con
    «f_» delante si no empieza por una letra y :data:`COLUMN_CHARS` caracteres como mucho; si
    es ``fid`` o ``geom`` (las de la tabla) o está en ``taken``, con «_2», «_3»…"""
    plain = "".join(char for char in unicodedata.normalize("NFKD", str(field_name))
                    if not unicodedata.combining(char)).lower()
    slug = _NON_COLUMN.sub("_", plain).strip("_")
    if not slug[:1].isalpha():
        slug = f"f_{slug}".rstrip("_")
    slug = slug[:COLUMN_CHARS].rstrip("_")
    used = set(taken) | _RESERVED_COLUMNS
    found, number = slug, 2
    while found in used:
        suffix = f"_{number}"
        found = slug[:COLUMN_CHARS - len(suffix)] + suffix
        number += 1
    return found


def field_columns(fields: Iterable[tuple[str, str]],
                  ) -> tuple[tuple[FieldColumn, ...], tuple[tuple[str, str], ...]]:
    """Los campos ``(nombre, tipo declarado)`` de una capa (``LayerInfo.fields``) como columnas
    de su tabla de dominios, en su orden (:func:`column_type`, :func:`column_name`), y los que
    no se importan (los binarios y los que no declaran tipo), con su tipo."""
    columns: list[FieldColumn] = []
    skipped: list[tuple[str, str]] = []
    for name, declared in fields:
        sql_type = column_type(declared)
        if sql_type is None:
            skipped.append((str(name), str(declared)))
            continue
        columns.append(FieldColumn(str(name), column_name(name, (c.column for c in columns)),
                                   sql_type))
    return tuple(columns), tuple(skipped)


@dataclass(frozen=True, slots=True, eq=False)
class DomainSet:
    """Las entidades de una capa de dominios (spec 011, D-32): su número en la capa
    (``fids``), sus polígonos (de cada entidad, sus polígonos y, de cada uno, sus anillos en
    planta, X e Y ABSOLUTOS en float64 tal como llegan; el primero, el exterior), sus campos
    como columnas (``columns``, :class:`FieldColumn`) y el valor de cada uno por entidad
    (``values``, por columna: ``None``, texto, entero o real). ``ValueError`` si no casan."""

    fids: tuple[int, ...]
    polygons: tuple[tuple[tuple[np.ndarray, ...], ...], ...]
    columns: tuple[FieldColumn, ...]
    values: Mapping[str, tuple[Any, ...]]

    def __post_init__(self) -> None:
        object.__setattr__(self, "fids", tuple(int(fid) for fid in self.fids))
        object.__setattr__(self, "polygons", tuple(
            tuple(tuple(ring for ring in polygon) for polygon in feature)
            for feature in self.polygons))
        object.__setattr__(self, "columns", tuple(self.columns))
        count = len(self.fids)
        if len(self.polygons) != count or len(set(self.fids)) != count:
            raise ValueError(f"{count} números de entidad (sin repetir) y {len(self.polygons)} "
                             "entidades con sus polígonos")
        names = [column.column for column in self.columns]
        if set(self.values) != set(names) or len(set(names)) != len(names):
            raise ValueError(f"los valores son de {sorted(self.values)} y las columnas, "
                             f"{names} (sin repetir)")
        values = {name: tuple(self.values[name]) for name in names}
        if any(len(found) != count for found in values.values()):
            raise ValueError(f"cada columna tiene un valor por cada una de las {count} "
                             "entidades")
        object.__setattr__(self, "values", MappingProxyType(values))

    def __len__(self) -> int:
        return len(self.fids)

    @property
    def column_defs(self) -> tuple[ColumnDef, ...]:
        """Las columnas de los atributos en su tabla del proyecto (``core.gpkg.ColumnDef``)."""
        return tuple(ColumnDef(column.column, column.sql_type) for column in self.columns)

    @property
    def titles(self) -> dict[str, str]:
        """El nombre en la capa de cada columna que no se llama igual (columna → título)."""
        return {column.column: column.field for column in self.columns
                if column.column != column.field}


def domains_from_features(features: FeatureSet) -> tuple[DomainSet, TopoReport]:
    """Los dominios de una capa con ese papel (spec 011, T18; RF-011-07; D-32): de cada Polygon
    o MultiPolygon, su número de entidad, sus polígonos y sus anillos en planta tal como llegan
    (float64; la Z, si la hay, no cuenta) y sus atributos de texto, enteros y reales
    (:func:`field_columns`). Una entidad de otra geometría (``gis.feature_role_mismatch``) o
    con un anillo de menos de tres vértices (``gis.feature_geometry_invalid``) se rechaza con
    su número; un campo binario, o con algún valor binario, no se importa
    (``gis.domain_field_skipped``, un aviso). El informe conserva los rechazos y avisos de la
    lectura; la validez de los polígonos como dominios (solapes, sin área, sin valor) la
    comprueba la cubicación (RF-011-08)."""
    info = features.layer
    found_columns, skipped = field_columns(info.fields)
    columns: list[FieldColumn] = []
    omitted = list(skipped)
    for column in found_columns:
        if any(isinstance(value, _BINARY) for value in features.attributes[column.field]):
            omitted.append((column.field, "BLOB"))
        else:
            columns.append(column)
    rejected: list[Rejection] = []
    fids: list[int] = []
    polygons: list[tuple[tuple[np.ndarray, ...], ...]] = []
    kept: list[int] = []
    for index, fid in enumerate(features.fids):
        geometry = features.geometries[index]
        if geometry.geometry_type not in DOMAIN_TYPES:
            code = "gis.feature_role_mismatch"
            text = render(code, layer=info.name, row=fid, value=geometry.geometry_type,
                          role="dominios", expected=" y ".join(DOMAIN_TYPES))
            rejected.append(Rejection(fid, text, code))
            continue
        parts = ([geometry.coords] if geometry.geometry_type == "POLYGON"
                 else list(geometry.coords))
        rings = tuple(tuple(np.ascontiguousarray(np.asarray(ring, dtype=np.float64)[:, :2])
                            for ring in polygon) for polygon in parts)
        if not rings or any(not polygon or any(len(ring) < 3 for ring in polygon)
                            for polygon in rings):
            code = "gis.feature_geometry_invalid"
            text = render(code, layer=info.name, file=info.file, row=fid,
                          detail="un anillo tiene menos de 3 vértices")
            rejected.append(Rejection(fid, text, code))
            continue
        fids.append(fid)
        polygons.append(rings)
        kept.append(index)
    values = {column.column: tuple(features.attributes[column.field][index] for index in kept)
              for column in columns}
    warnings = tuple(render("gis.domain_field_skipped", layer=info.name, value=name, kind=kind)
                     for name, kind in omitted)
    every = sorted((*features.report.rejected, *rejected), key=lambda item: item.row)
    report = replace(features.report, rejected=tuple(every),
                     warnings=(*features.report.warnings, *warnings))
    return DomainSet(tuple(fids), tuple(polygons), tuple(columns), values), report


# --- Capa de entidades (spec 012, T07; RF-012-01, RF-012-08, RF-012-26; plan 012 D-27) ---------

FEATURE_KINDS: Mapping[str, str] = MappingProxyType({
    "POINT": "point", "MULTIPOINT": "point",
    "LINESTRING": "line", "MULTILINESTRING": "line",
    "POLYGON": "polygon", "MULTIPOLYGON": "polygon",
})
"""La geometría (``point``, ``line`` o ``polygon``, los valores de
``core.constraints.GeometryKind``) de cada tipo de entidad de GeoPackage."""
FEATURE_TABLE_TYPES: Mapping[str, str] = MappingProxyType(
    {"point": "MULTIPOINT", "line": "MULTILINESTRING", "polygon": "MULTIPOLYGON"})
"""El tipo de la tabla del proyecto de una capa de entidades, por su geometría."""
_MIN_VERTICES: Mapping[str, int] = MappingProxyType({"point": 1, "line": 2, "polygon": 3})


@dataclass(frozen=True, slots=True, eq=False)
class Feature:
    """Una entidad de una capa de entidades: su número en la capa, sus atributos (columna →
    valor) y sus partes (de cada una, sus anillos, su camino o su punto ``(1, 2)``, X e Y
    ABSOLUTAS en float64)."""

    fid: int
    attributes: Mapping[str, Any]
    parts: tuple[tuple[np.ndarray, ...], ...]


@dataclass(frozen=True, slots=True, eq=False)
class FeatureLayer:
    """Las entidades de una capa con el papel «entidades» (spec 012, D-27): su geometría
    (``kind``: ``point``, ``line`` o ``polygon``, :data:`FEATURE_KINDS`), el número de cada una
    en la capa (``fids``), sus partes (``parts``: por entidad, por parte, sus anillos —el
    primero, el exterior—, su camino o su punto ``(1, 2)``, en planta, X e Y ABSOLUTAS en
    float64), sus campos como columnas (``columns``, :class:`FieldColumn`) y el valor de cada
    uno por entidad (``values``, por columna). ``ValueError`` si no casan."""

    kind: str
    fids: tuple[int, ...]
    parts: tuple[tuple[tuple[np.ndarray, ...], ...], ...]
    columns: tuple[FieldColumn, ...]
    values: Mapping[str, tuple[Any, ...]]

    def __post_init__(self) -> None:
        if self.kind not in FEATURE_TABLE_TYPES:
            raise ValueError(f"la geometría de una capa de entidades es una de "
                             f"{', '.join(FEATURE_TABLE_TYPES)}, no {self.kind!r}")
        # Las mismas comprobaciones que unos dominios (números, partes y columnas que casan).
        checked = DomainSet(self.fids, self.parts, self.columns, self.values)
        object.__setattr__(self, "fids", checked.fids)
        object.__setattr__(self, "parts", checked.polygons)
        object.__setattr__(self, "columns", checked.columns)
        object.__setattr__(self, "values", checked.values)

    def __len__(self) -> int:
        return len(self.fids)

    @property
    def geometry_type(self) -> str:
        """El tipo de su tabla en el proyecto (``MULTIPOINT``, ``MULTILINESTRING`` o
        ``MULTIPOLYGON``)."""
        return FEATURE_TABLE_TYPES[self.kind]

    @property
    def column_defs(self) -> tuple[ColumnDef, ...]:
        """Las columnas de los atributos en su tabla del proyecto (``core.gpkg.ColumnDef``)."""
        return tuple(ColumnDef(column.column, column.sql_type) for column in self.columns)

    @property
    def titles(self) -> dict[str, str]:
        """El nombre en la capa de cada columna que no se llama igual (columna → título)."""
        return {column.column: column.field for column in self.columns
                if column.column != column.field}

    def feature(self, index: int) -> Feature:
        """La entidad ``index`` (en el orden de ``fids``) con sus atributos y sus partes."""
        return Feature(self.fids[index], MappingProxyType(
            {name: found[index] for name, found in self.values.items()}), self.parts[index])


def _plan_xy(coords: Any) -> np.ndarray:
    """Las X e Y de unas coordenadas leídas, ``(k, 2)`` float64 contiguas (la Z no cuenta)."""
    values = np.asarray(coords, dtype=np.float64)
    return np.ascontiguousarray(values.reshape(-1, values.shape[-1])[:, :2])


def feature_parts(geometry_type: str, coords: Any) -> tuple[tuple[np.ndarray, ...], ...]:
    """Las partes en planta de una geometría de GeoPackage (``POINT``…``MULTIPOLYGON``): un
    punto ``(1, 2)`` por parte, un camino por parte o los anillos de cada polígono."""
    if geometry_type in ("POINT", "MULTIPOINT"):
        return tuple((np.ascontiguousarray(point[None, :]),) for point in _plan_xy(coords))
    if geometry_type == "LINESTRING":
        return ((_plan_xy(coords),),)
    if geometry_type == "MULTILINESTRING":
        return tuple((_plan_xy(line),) for line in coords)
    if geometry_type == "POLYGON":
        return (tuple(_plan_xy(ring) for ring in coords),)
    if geometry_type == "MULTIPOLYGON":
        return tuple(tuple(_plan_xy(ring) for ring in polygon) for polygon in coords)
    raise ValueError(f"{geometry_type!r} no es la geometría de una entidad: es una de "
                     f"{', '.join(FEATURE_KINDS)}")


def features_from_layer(features: FeatureSet) -> tuple[FeatureLayer, TopoReport]:
    """Las entidades de una capa con el papel «entidades» (spec 012, T07; RF-012-01,
    RF-012-08, RF-012-26; D-27): su geometría es la de la capa (o, si es ``GEOMETRY``, la de su
    primera entidad que la tenga; sin ninguna, ``polygon``); de cada entidad de esa geometría,
    simple o múltiple, su número, sus partes en planta tal como llegan (:func:`feature_parts`;
    la Z no cuenta) y sus atributos de texto, enteros y reales (la fecha, como texto:
    :func:`field_columns`). Una entidad de otra geometría (``gis.feature_role_mismatch``) o sin
    los vértices de la suya (``gis.feature_geometry_invalid``) se rechaza con su número; un
    campo binario, o con algún valor binario, no se importa (``gis.feature_field_skipped``, un
    aviso). El informe conserva los rechazos y avisos de la lectura."""
    info = features.layer
    kind = FEATURE_KINDS.get(info.geometry_type) or next(
        (FEATURE_KINDS[g.geometry_type] for g in features.geometries
         if g.geometry_type in FEATURE_KINDS), "polygon")
    found_columns, skipped = field_columns(info.fields)
    columns: list[FieldColumn] = []
    omitted = list(skipped)
    for column in found_columns:
        if any(isinstance(value, _BINARY) for value in features.attributes[column.field]):
            omitted.append((column.field, "BLOB"))
        else:
            columns.append(column)
    expected = [name for name, found in FEATURE_KINDS.items() if found == kind]
    rejected: list[Rejection] = []
    fids: list[int] = []
    parts: list[tuple[tuple[np.ndarray, ...], ...]] = []
    kept: list[int] = []
    for index, fid in enumerate(features.fids):
        geometry = features.geometries[index]
        if FEATURE_KINDS.get(geometry.geometry_type) != kind:
            code = "gis.feature_role_mismatch"
            text = render(code, layer=info.name, row=fid, value=geometry.geometry_type,
                          role="entidades", expected=" y ".join(expected))
            rejected.append(Rejection(fid, text, code))
            continue
        found = feature_parts(geometry.geometry_type, geometry.coords)
        if not found or any(not part or any(len(item) < _MIN_VERTICES[kind] for item in part)
                            for part in found):
            code = "gis.feature_geometry_invalid"
            text = render(code, layer=info.name, file=info.file, row=fid,
                          detail=f"tiene menos de {_MIN_VERTICES[kind]} vértices")
            rejected.append(Rejection(fid, text, code))
            continue
        fids.append(fid)
        parts.append(found)
        kept.append(index)
    values = {column.column: tuple(features.attributes[column.field][index] for index in kept)
              for column in columns}
    warnings = tuple(render("gis.feature_field_skipped", layer=info.name, value=name,
                            kind=declared) for name, declared in omitted)
    every = sorted((*features.report.rejected, *rejected), key=lambda item: item.row)
    report = replace(features.report, rejected=tuple(every),
                     warnings=(*features.report.warnings, *warnings))
    return FeatureLayer(kind, tuple(fids), tuple(parts), tuple(columns), values), report


def transform_features(layer: FeatureLayer, transform: Transform) -> FeatureLayer:
    """Las entidades ``layer`` en el CRS de destino de ``transform`` (la de la 006,
    ``gis.crs.transformation_for``; RF-006-05, D-27): cada vértice, con su X y su Y
    transformadas (la cota, cero, no cuenta), en una sola llamada; la geometría, los números,
    las partes y los atributos, los mismos. ``layer`` no cambia; ``ValueError`` si algún
    vértice no tiene una posición finita en el destino."""
    arrays = [array for feature in layer.parts for part in feature for array in part]
    if not arrays:
        return layer
    xy = np.concatenate(arrays)
    moved = np.asarray(transform.apply(np.column_stack(
        [xy, np.zeros(len(xy), dtype=np.float64)])), dtype=np.float64)
    if moved.shape != (len(xy), 3) or not np.all(np.isfinite(moved[:, :2])):
        raise ValueError("la transformación no da una posición finita para cada vértice")
    ends = np.cumsum([len(array) for array in arrays])[:-1]
    pieces = iter(np.split(moved[:, :2], ends))
    parts = tuple(tuple(tuple(np.ascontiguousarray(next(pieces)) for _array in part)
                        for part in feature) for feature in layer.parts)
    return FeatureLayer(layer.kind, layer.fids, parts, layer.columns, layer.values)
