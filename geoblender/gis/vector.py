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

El papel que declara el usuario (puntos, líneas de rotura) lo aplica ``gis.points``.
"""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ..core.errors import DatabaseError, GeometryError, ValidationError
from ..core.georef import CrsCatalog, CrsRef, load_catalog
from ..core.gpkg import Geometry, GpkgConnection, decode_geometry, private_copy, read_header
from .messages import GisError, render
from .reports import Rejection, TopoReport

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
