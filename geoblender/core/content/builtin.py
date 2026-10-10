# SPDX-License-Identifier: GPL-3.0-or-later
"""Lectores de contenido de ``core`` (spec 008; RF-008-08, RF-008-14, RF-008-21; ADR-0024 §4 y
§5; plan 008 §5.1 y §5.4.1).

Los formatos que ya escribe o lee ``core``, cada uno con su lector
(:class:`~.readers.ContentReader`): la misma función calcula el hash al importar y al
comprobar (ADR-0024 §5). Son generadores que dan su progreso tras cada trozo (cada ``yield``
es un punto de cancelación) y ninguno crea, cambia ni borra nada junto a su fuente
(RF-008-14).

- :data:`GPKG_LAYER` (``core.gpkg_layer@1``): una capa de entidades (``features`` en
  ``gpkg_contents``; tipo ``vector``) o una tabla (``attributes``; tipo ``table``) de un
  GeoPackage, del proyecto o externo. Ajustes de lectura (:data:`GPKG_SETTINGS_KEYS`):
  ``layer``, su nombre exacto en ``gpkg_contents``, y ``selector`` (opcional, el de
  ``gb_dataset.selector``): ``{"column": c, "equals": v}`` (lo importado de una entrada en una
  tabla común: solo sus filas) o ``{"column": c, "of": "current_inputs"}`` (un dato
  acumulado: las filas de las entradas vigentes de ``gb_input``, solo en ``project.gpkg``).
  Cuentan todas las columnas salvo la clave entera (``fid``, el número interno) y la de
  geometría, que va aparte con las dimensiones de ``gpkg_geometry_columns`` y el CRS de
  ``gpkg_spatial_ref_sys`` (``{"epsg": n}`` si es de EPSG; si no, ``None``). Cada columna se
  hashea con el tipo que declara (:data:`GPKG_TYPES`, los del estándar) y sus valores ya
  interpretados: un texto en una columna REAL o entera es el número que dice, con coma o
  punto decimal («1,5» y «1.50» son 1,5). Las filas no tienen orden (un multiconjunto, como
  las entidades). Una base en diario clásico se lee en su sitio y en solo lectura
  (``mode=ro``: no crea nada); una con ``-wal``, la cabecera en WAL o un diario caliente, sobre
  una copia privada en una carpeta temporal (``core.gpkg.wal.private_copy``, con lo que tenga
  pendiente su ``-wal``), que se borra al acabar y al cancelar: por eso ``needs_copy`` es
  falso, la copia la hace él. :func:`layer_steps` lee con una conexión ya abierta: la de la
  transacción que escribe una tabla del proyecto, que ve lo que aún no ha confirmado.
- :data:`DOCUMENT` (``core.document@1``): los bytes de un documento o un informe; su hash de
  datos es su huella (``core.hashing.sha256_file``).
- :data:`NPZ_MESH` (``core.npz_mesh@1``): una malla ``npz`` de ``meshes/``
  (``formato-proyecto.md`` §4.3), leída sin ``pickle``: cuentan sus arrays y, de su ``meta``
  (un texto JSON 0-d), solo ``kind``, ``crs_epsg`` y ``closed``; ``operation_uid``,
  ``volume_m3`` y lo demás no son contenido.

:data:`CONTENT_READERS` los reúne para que los registre ``bl/`` (y la lista estática del
trabajo de hash): importar este módulo no registra nada. Python puro, ``sqlite3`` y numpy
(ADR-0004).
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np

from ..errors import GeoblenderError, ValidationError
from ..gpkg.connection import GpkgConnection
from ..gpkg.wkb import geometry_wkb
from ..numbers import parse_decimal
from .readers import MAIN_ROLE, ContentReader, ReadRequest

GPKG_SETTINGS_KEYS: tuple[str, ...] = ("layer", "selector")
"""Los ajustes de lectura de ``core.gpkg_layer@1``: ``layer`` (obligatorio) y ``selector``."""
CURRENT_INPUTS = "current_inputs"
"""``{"column": c, "of": "current_inputs"}``: las filas de las entradas vigentes."""
INACTIVE_INPUT_STATUSES: tuple[str, ...] = ("superseded", "discarded")
"""Los estados de una entrada que no es vigente (los de ``core.provenance.schema``, que no se
importa aquí para no atar el contenido a la procedencia)."""
GPKG_TYPES: Mapping[str, str] = MappingProxyType(
    {
        "BOOLEAN": "bool",
        "TINYINT": "int",
        "SMALLINT": "int",
        "MEDIUMINT": "int",
        "INT": "int",
        "INTEGER": "int",
        "FLOAT": "float",
        "DOUBLE": "float",
        "REAL": "float",
        "TEXT": "text",
        "BLOB": "blob",
        "DATE": "date",
        "DATETIME": "datetime",
    }
)
"""Los tipos de columna del estándar GeoPackage (1.4, tabla 1) y el de su campo en ``gbch/1``,
sin distinguir mayúsculas y con o sin tamaño (``TEXT(20)``, ``BLOB(100)``). Otro tipo se
rechaza."""
LAYER_KINDS: Mapping[str, str] = MappingProxyType(
    {"features": "vector", "attributes": "table", "aspatial": "table"}
)
"""``gpkg_contents.data_type`` → tipo de dato (``aspatial``: las tablas del GDAL antiguo)."""
ROW_BYTES = 256
"""Lo que se cuenta por fila para repartir la lectura en trozos de ``chunk_bytes``."""
GPKG_BYTES_PER_S = 20_000_000
"""Los bytes del fichero que lee y hashea ``core.gpkg_layer@1`` por segundo, a la baja: su
estimación (medido en el PC de referencia: 41 MB, 100 000 polígonos de 20 vértices, en
1,56 s; 26 MB/s)."""
DOCUMENT_BYTES_PER_S = 100_000_000
"""Ídem, ``core.document@1`` (sha256 a unos 185 MB/s en el PC de referencia, más la lectura)."""
NPZ_BYTES_PER_S = 30_000_000
"""Ídem, ``core.npz_mesh@1`` (medido: 40 MB comprimidos, 1 M de vértices y 2 M de caras, en
0,60 s; una malla que se comprime más da menos bytes del fichero por segundo)."""
PRIVATE_PREFIX = "gb-gp-"
"""Prefijo de la carpeta temporal de la copia privada (corto: rutas de 259 caracteres)."""
META_ARRAY = "meta"
"""El array de una malla ``npz`` con su ``meta`` en JSON."""

_SQL_TYPE =re.compile(r"\s*([A-Za-z]+)\s*(\(\s*[0-9]+\s*\))?\s*")
_KIND_TEXT = {
    "vector": "una capa de entidades (vector)",
    "table": "una tabla sin geometría (table)",
}
_OBJ = "Capa de GeoPackage"


# --- core.gpkg_layer@1 ------------------------------------------------------------------------


@dataclass(frozen=True)
class _Layer:
    """Lo que se lee de una capa o tabla: su nombre, su tipo, la consulta de sus filas
    (clave, geometría si la tiene y columnas) y cómo se hashean."""

    name: str
    kind: str
    dims: str
    crs: dict[str, int] | None
    columns: tuple[tuple[str, str, str], ...]  # (nombre, tipo de campo, tipo SQL)
    numeric: tuple[int, ...]  # posición de las columnas REAL y enteras
    select: str
    count: str
    params: tuple[object, ...]


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _layer_error(code: str, reason: str, layer: str) -> ValidationError:
    return ValidationError(f"core.{code}", reason, obj=_OBJ, field="capa", value=layer)


def _layer_settings(request: ReadRequest) -> tuple[str, Mapping[str, Any] | None]:
    """La capa y el selector de los ajustes (``ValueError`` o ``TypeError`` si no valen)."""
    settings = request.settings
    unknown = sorted(str(key) for key in settings if key not in GPKG_SETTINGS_KEYS)
    if unknown:
        raise ValueError(
            f"ajustes de lectura desconocidos para «{request.reader}»: {unknown} (son "
            f"{list(GPKG_SETTINGS_KEYS)})"
        )
    if "layer" not in settings:
        raise ValueError(f"falta la capa o la tabla que lee «{request.reader}» («layer»)")
    layer = settings["layer"]
    if not isinstance(layer, str):
        raise TypeError(f"la capa («layer») es su nombre en texto, no {layer!r}")
    if not layer:
        raise ValueError("la capa («layer») no puede quedar vacía")
    selector = settings.get("selector")
    if selector is not None and not isinstance(selector, Mapping):
        raise TypeError(
            'el selector es un diccionario {"column", "equals"} o {"column", "of"} (o None), '
            f"no {selector!r}"
        )
    return layer, selector


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def _field_type(sql_type: object) -> str | None:
    """El tipo de campo de ``gbch/1`` de un tipo de columna del estándar, o ``None``."""
    match = _SQL_TYPE.fullmatch(sql_type) if isinstance(sql_type, str) else None
    if match is None:
        return None
    return GPKG_TYPES.get(match.group(1).upper())


def _crs(conn: sqlite3.Connection, srs_id: object) -> dict[str, int] | None:
    """``{"epsg": n}`` si el SRS de la capa es de EPSG; si no, ``None``."""
    row = conn.execute(
        "SELECT organization, organization_coordsys_id FROM gpkg_spatial_ref_sys "
        "WHERE srs_id = ?",
        (srs_id,),
    ).fetchone()
    if row is None:
        return None
    organization, code = row
    if (
        isinstance(organization, str)
        and organization.upper() == "EPSG"
        and type(code) is int
        and code > 0
    ):
        return {"epsg": code}
    return None


def _geometry_column(conn: sqlite3.Connection, layer: str) -> tuple[str, str, dict | None]:
    """La columna de geometría, las dimensiones y el CRS de una capa de entidades."""
    row = conn.execute(
        "SELECT column_name, srs_id, z, m FROM gpkg_geometry_columns WHERE table_name = ?",
        (layer,),
    ).fetchone()
    if row is None:
        raise _layer_error(
            "content_layer_invalid",
            "es una capa de entidades sin su columna de geometría en gpkg_geometry_columns",
            layer,
        )
    column, srs_id, z, m = row
    if z not in (0, 1, 2) or m not in (0, 1, 2) or not isinstance(column, str):
        raise _layer_error(
            "content_layer_invalid",
            f"gpkg_geometry_columns no es del estándar (z = {z!r}, m = {m!r}: 0, 1 o 2)",
            layer,
        )
    dims = "XY" + ("Z" if z else "") + ("M" if m else "")
    return column, dims, _crs(conn, srs_id)


def _selector(
    conn: sqlite3.Connection,
    selector: Mapping[str, Any] | None,
    names: Sequence[str],
    layer: str,
) -> tuple[str, tuple[object, ...]]:
    """La cláusula ``WHERE`` del selector y sus parámetros (vacía sin selector)."""
    if selector is None:
        return "", ()
    keys = set(selector)
    column = selector.get("column")
    if keys == {"column", "equals"}:
        value = selector["equals"]
        valid = isinstance(value, str | int) and not isinstance(value, bool)
    elif keys == {"column", "of"}:
        valid = selector["of"] == CURRENT_INPUTS
    else:
        valid = False
    if not valid or not isinstance(column, str) or not column:
        reason = (
            'el selector es {"column": <columna>, "equals": <texto o entero>} (lo importado '
            'de una entrada) o {"column": <columna>, "of": "current_inputs"} (las entradas '
            "vigentes)"
        )
    elif column not in names:
        reason = f"la tabla no tiene la columna «{column}»"
    elif "of" in keys and not _has_table(conn, "gb_input"):
        reason = (
            "el selector de entradas vigentes solo vale en el GeoPackage del proyecto, y este "
            "no tiene gb_input"
        )
    else:
        quoted = _quote(column)
        if "equals" in keys:
            return f" WHERE {quoted} = ?", (selector["equals"],)
        inactive = ", ".join(f"'{status}'" for status in INACTIVE_INPUT_STATUSES)
        return (
            f" WHERE {quoted} IN (SELECT uid FROM gb_input WHERE status NOT IN ({inactive}))",
            (),
        )
    raise ValidationError(
        "core.dataset_selector_invalid",
        reason,
        obj=f"{_OBJ} «{layer}»",
        field="selector",
        value=dict(selector),
    )


def _describe(conn: sqlite3.Connection, request: ReadRequest) -> _Layer:
    """Comprueba la capa de la petición en la base y dice cómo se lee."""
    layer, selector = _layer_settings(request)
    if not _has_table(conn, "gpkg_contents"):
        raise _layer_error(
            "content_not_gpkg", "la base no es un GeoPackage: no tiene gpkg_contents", layer
        )
    row = conn.execute(
        "SELECT data_type FROM gpkg_contents WHERE table_name = ?", (layer,)
    ).fetchone()
    if row is None:
        raise _layer_error(
            "content_layer_missing",
            "no está en gpkg_contents con ese nombre: la capa o la tabla ya no está en el "
            "GeoPackage o se llama de otra forma",
            layer,
        )
    kind = LAYER_KINDS.get(str(row[0]).lower())
    if kind is None:
        raise _layer_error(
            "content_layer_kind",
            f"es de tipo «{row[0]}»: solo se leen capas de entidades (features) y tablas "
            "(attributes)",
            layer,
        )
    if kind != request.kind:
        raise _layer_error(
            "content_layer_kind",
            f"es {_KIND_TEXT[kind]} y se pidió {_KIND_TEXT.get(request.kind, request.kind)}",
            layer,
        )
    info = conn.execute(
        "SELECT name, type, pk FROM pragma_table_info(?) ORDER BY cid", (layer,)
    ).fetchall()
    if not info:
        raise _layer_error(
            "content_layer_missing", "está en gpkg_contents, pero la tabla no existe", layer
        )
    geometry = dims = crs = None
    if kind == "vector":
        registered, dims, crs = _geometry_column(conn, layer)
        found = [name for name, _t, _p in info if name.lower() == registered.lower()]
        geometry = found[0] if found else None
        if geometry is None:
            raise _layer_error(
                "content_layer_invalid",
                f"la tabla no tiene la columna de geometría «{registered}»",
                layer,
            )
    keys = [(name, sql_type) for name, sql_type, pk in info if pk]
    alias = None  # la clave entera es el rowid: el número interno, que no es contenido
    if len(keys) == 1 and str(keys[0][1]).strip().upper() == "INTEGER":
        alias = keys[0][0]
    columns: list[tuple[str, str, str]] = []
    for name, sql_type, _pk in info:
        if name in (alias, geometry):
            continue
        field = _field_type(sql_type)
        if field is None:
            raise _layer_error(
                "content_layer_invalid",
                f"la columna «{name}» es de tipo «{sql_type}», que no es del estándar "
                f"GeoPackage (son {', '.join(GPKG_TYPES)})",
                layer,
            )
        columns.append((name, field, str(sql_type)))
    where, params = _selector(conn, selector, [name for name, _t, _p in info], layer)
    selected = [_quote(alias) if alias else "NULL"]
    selected += [_quote(geometry)] if geometry else []
    selected += [_quote(name) for name, _f, _s in columns]
    table = _quote(layer)
    return _Layer(
        name=layer,
        kind=kind,
        dims=dims or "XY",
        crs=crs,
        columns=tuple(columns),
        numeric=tuple(i for i, (_n, field, _s) in enumerate(columns) if field in ("float", "int")),
        select=f"SELECT {', '.join(selected)} FROM {table}{where}",
        count=f"SELECT count(*) FROM {table}{where}",
        params=params,
    )


def _number(layer: _Layer, index: int, value: str, where: str) -> float:
    """El número de un texto en una columna REAL o entera (coma o punto decimal)."""
    name, _field, sql_type = layer.columns[index]
    try:
        return parse_decimal(value, obj=layer.name, field=name)
    except ValidationError as error:
        raise ValidationError(
            "core.content_value_invalid",
            f"la columna es {sql_type} y su valor no es un número (con coma o punto decimal)",
            obj=f"{_OBJ} «{layer.name}»",
            field=f"«{name}» ({where})",
            value=value,
        ) from error


def _add(feed: Any, layer: _Layer, row: Sequence[Any], ordinal: int) -> None:
    """Añade una fila leída (clave, geometría si es una capa y columnas) a su codificador."""
    key = row[0]
    where = f"fid {key}" if key is not None else f"fila {ordinal}"
    first = 2 if layer.kind == "vector" else 1
    values = list(row[first:])
    for index in layer.numeric:
        if isinstance(values[index], str):
            values[index] = _number(layer, index, values[index], where)
    try:
        if layer.kind == "vector":
            blob = row[1]
            shape = None if blob is None else geometry_wkb(blob)
            names = (name for name, _f, _s in layer.columns)
            feed.add(shape, dict(zip(names, values, strict=True)))
        else:
            feed.add(values)
    except (TypeError, ValueError, GeoblenderError) as error:
        raise ValidationError(
            "core.content_value_invalid",
            f"no se puede leer: {error}",
            obj=f"{_OBJ} «{layer.name}»",
            field="fila",
            value=where,
            shown=where,
        ) from error


def layer_steps(conn: sqlite3.Connection, request: ReadRequest) -> Iterator[float]:
    """Los pasos de ``core.gpkg_layer@1`` con una conexión ya abierta (``sqlite3``): cuenta
    las filas, las lee por trozos de unos ``request.chunk_bytes`` y las escribe en el hasher
    de la petición; da el progreso (filas leídas / filas) y 1,0 cuando el hash está hecho. No
    abre ni confirma transacciones: con la conexión de una transacción de escritura, ve lo
    que aún no ha confirmado. ``ValidationError`` (``core.content_*``,
    ``core.dataset_selector_invalid``) si la capa no se puede leer."""
    if request.reader != GPKG_LAYER.id:
        raise ValueError(
            f"la petición es para el lector «{request.reader}», no para «{GPKG_LAYER.id}»"
        )
    layer = _describe(conn, request)
    total = int(conn.execute(layer.count, layer.params).fetchone()[0])
    fields = [[name, field] for name, field, _s in layer.columns]
    if layer.kind == "vector":
        feed: Any = request.hasher.begin_features(fields, layer.dims, layer.crs)
    else:
        feed = request.hasher.begin_rows(fields, False)
    step = max(1, request.chunk_bytes // ROW_BYTES)
    cursor = conn.execute(layer.select, layer.params)
    try:
        done = 0
        while rows := cursor.fetchmany(step):
            for row in rows:
                done += 1
                _add(feed, layer, row, done)
            if done < total:
                yield done / total
        feed.finish()
    finally:
        cursor.close()
    yield 1.0


def read_gpkg_layer(request: ReadRequest) -> Iterator[float]:
    """El generador de ``core.gpkg_layer@1``: abre el GeoPackage en solo lectura (en una
    copia privada temporal si tiene ``-wal``, la cabecera en WAL o un diario caliente), da 0
    tras abrirlo y sigue con :func:`layer_steps` en una sola instantánea de lectura."""
    path = _only_main(request)
    _layer_settings(request)  # antes de abrir nada
    with tempfile.TemporaryDirectory(prefix=PRIVATE_PREFIX) as private:
        with GpkgConnection.open_read(path, Path(private)) as db:
            conn = db.connection
            conn.execute("BEGIN")  # contar y leer en la misma instantánea
            yield 0.0
            yield from layer_steps(conn, request)


# --- core.document@1 --------------------------------------------------------------------------


def read_document(request: ReadRequest) -> Iterator[float]:
    """El generador de ``core.document@1``: los bytes del fichero en trozos de
    ``request.chunk_bytes``, con el progreso (bytes leídos / tamaño)."""
    path = _only_main(request)
    _no_settings(request)
    with open(path, "rb", buffering=0) as stream:
        total = os.fstat(stream.fileno()).st_size
        feed = request.hasher.begin_document()
        done = 0
        while chunk := stream.read(request.chunk_bytes):
            feed.update(chunk)
            done += len(chunk)
            if done < total:
                yield done / total
        feed.finish()
    yield 1.0


# --- core.npz_mesh@1 --------------------------------------------------------------------------


def _array(archive: Any, name: str, path: Path) -> np.ndarray:
    try:
        return archive[name]
    except ValueError as error:
        raise ValueError(
            f"«{path.name}»: el array «{name}» no se puede leer sin pickle ({error})"
        ) from error


def _meta(value: np.ndarray, path: Path) -> dict[str, Any]:
    """El ``meta`` de una malla: un texto JSON 0-d con un objeto."""
    if value.ndim != 0 or value.dtype.kind not in "US":
        raise ValueError(
            f"«{path.name}»: «{META_ARRAY}» es un texto JSON 0-d, no un array {value.dtype} de "
            f"forma {value.shape}"
        )
    text = value.item()
    try:
        meta = json.loads(text.decode("utf-8") if isinstance(text, bytes) else text)
    except ValueError as error:
        raise ValueError(f"«{path.name}»: «{META_ARRAY}» no es JSON ({error})") from error
    if not isinstance(meta, dict):
        raise ValueError(
            f"«{path.name}»: «{META_ARRAY}» es un objeto JSON, no {type(meta).__name__}"
        )
    return meta


def read_npz_mesh(request: ReadRequest) -> Iterator[float]:
    """El generador de ``core.npz_mesh@1``: lee los arrays uno a uno (progreso por array) sin
    ``pickle``, cierra el fichero y hashea la malla con ``ContentHasher.mesh``."""
    path = _only_main(request)
    _no_settings(request)
    arrays: dict[str, np.ndarray] = {}
    meta: dict[str, Any] = {}
    with open(path, "rb") as stream:
        if stream.read(2) != b"PK":
            raise ValueError(f"«{path.name}» no es una malla npz (un zip de numpy)")
        stream.seek(0)
        with np.load(stream, allow_pickle=False) as archive:
            names = list(archive.files)
            for index, name in enumerate(names, start=1):
                value = _array(archive, name, path)
                if name == META_ARRAY:
                    meta = _meta(value, path)
                else:
                    arrays[name] = value
                yield index / (len(names) + 1)
    request.hasher.mesh(arrays, meta)
    yield 1.0


# --- Comunes ----------------------------------------------------------------------------------


def _only_main(request: ReadRequest) -> Path:
    """El fichero principal: estos lectores leen uno solo."""
    if set(request.files) != {MAIN_ROLE}:
        raise ValueError(
            f"el lector «{request.reader}» lee un solo fichero («{MAIN_ROLE}»), no "
            f"{sorted(request.files)}"
        )
    return request.files[MAIN_ROLE]


def _no_settings(request: ReadRequest) -> None:
    if request.settings:
        raise ValueError(
            f"el lector «{request.reader}» no tiene ajustes de lectura: "
            f"{sorted(str(key) for key in request.settings)}"
        )


def _per_second(speed: int) -> Callable[[int], float]:
    """La estimación de un lector que lee ``speed`` bytes por segundo."""

    def estimate(size: int) -> float:
        return size / speed

    return estimate


GPKG_LAYER = ContentReader(
    "core.gpkg_layer",
    1,
    ("vector", "table"),
    False,
    True,
    _per_second(GPKG_BYTES_PER_S),
    read_gpkg_layer,
)
"""Una capa o una tabla de un GeoPackage, del proyecto o externo."""
DOCUMENT = ContentReader(
    "core.document",
    1,
    ("document", "report"),
    False,
    False,
    _per_second(DOCUMENT_BYTES_PER_S),
    read_document,
)
"""Los bytes de un documento o un informe."""
NPZ_MESH = ContentReader(
    "core.npz_mesh",
    1,
    ("mesh",),
    False,
    False,
    _per_second(NPZ_BYTES_PER_S),
    read_npz_mesh,
)
"""Una malla ``npz`` de ``meshes/``."""
CONTENT_READERS: tuple[ContentReader, ...] = (GPKG_LAYER, DOCUMENT, NPZ_MESH)
"""Los lectores de ``core``, para registrarlos desde ``bl/`` y en el trabajo de hash."""
