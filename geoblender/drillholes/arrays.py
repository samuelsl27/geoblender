# SPDX-License-Identifier: GPL-3.0-or-later
"""Los sondeos en arrays de numpy, sin *pickle* (spec 005, T23; RF-005-04, RF-005-16,
RF-005-20; plan 005 §5.3.3 y §5.6.7; ARQ-16).

Lo que va del hilo de Blender a los trabajos de la 005 y vuelve (``drillholes.jobs``,
``interop.dh_jobs``) viaja en arrays de numpy que se leen con ``allow_pickle=False``: sueltos en
``in/`` (``JobDir.write_array``, ``launch_job(arrays=…)``) o juntos en un ``.npz``.

- **Columnas del modelo** (:func:`tables_arrays` y :func:`tables_of`): las de cada tabla de
  ``drillholes.model`` (``collars``, ``surveys``…, :data:`~.model.TABLES`) con el nombre
  ``<prefijo><tabla>_<campo>`` y los catálogos en ``<prefijo>catalogs``. Los números (float64,
  bits incluidos), los sí/no, los enteros y los códigos de las enumeraciones (int8) van tal
  cual; los textos, en UTF-8 (``S``) con su máscara de nulos ``…_null`` (solo si hay alguno);
  los enteros opcionales (``category``, ``priority``), en int64 con su máscara; las fechas, en
  ISO («AAAA-MM-DD»); ``extra``, su JSON canónico; los catálogos, un JSON
  (``uint8``). Las tablas sin filas no van. Una tabla grande se convierte por partes de
  :data:`PART_ROWS` filas (:func:`table_parts`, una por paso del hilo de Blender; T53,
  RNF-005-06) que :func:`merge_parts` junta en los mismos arrays, bit a bit. Así viajan un
  :class:`~.model.DrillholeSet`
  (:func:`set_arrays`, :func:`set_of`), lo importado de una entrada
  (:func:`entry_arrays`, :func:`entry_of`) y lo que lee una importación; los catálogos del
  proyecto en una petición, :func:`catalogs_json` y :func:`catalogs_of`; los arrays de la
  vista (``view_data.CurveArrays``…), :func:`dataclass_arrays` y :func:`dataclass_of`.
- **Filas de una tabla del proyecto** (:func:`rows_arrays` y :class:`TableRows`): las de
  ``schema.insert_rows`` de un ``TableLayout`` (la geometría, un blob GeoPackage), por columna
  y con su tipo de SQL: ``DOUBLE`` en float64 (``NULL``, NaN), ``INTEGER`` y ``BOOLEAN`` en
  int64, ``TEXT`` y ``DATE`` en UTF-8, cada una con su máscara de nulos, y la geometría en un
  bloque de bytes con sus ``offsets``. :class:`TableRows` es la secuencia de filas que se
  escribe (``BaseWriter``, ``SourceWriter``): decodifica cada trozo al pedirlo, así el hilo de
  Blender no convierte de una vez las 500 000 filas de V-ref.

Python puro y numpy (ADR-0004).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import math
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any, overload

import numpy as np

from ..core.hashing import canonical_json
from .model import (
    TABLES,
    Catalogs,
    CatalogEntry,
    DrillholeSet,
    Element,
    LithologyCode,
)

__all__ = [
    "CATALOGS",
    "NULL_SUFFIX",
    "PART_ROWS",
    "TableRows",
    "catalogs_json",
    "catalogs_of",
    "dataclass_arrays",
    "dataclass_of",
    "entry_arrays",
    "entry_of",
    "load_npz",
    "merge_parts",
    "rows_arrays",
    "save_npz",
    "set_arrays",
    "set_of",
    "table_parts",
    "tables_arrays",
    "tables_of",
]

NULL_SUFFIX = "_null"
"""La máscara de nulos de un array de textos (o de enteros de una tabla): ``<clave>_null``."""
CATALOGS = "catalogs"
"""La clave de los catálogos (``<prefijo>catalogs``): un JSON en UTF-8 (``uint8``)."""
PART_ROWS = 50_000
"""Las filas de una parte de :func:`table_parts` (T53): convertir 50 000 filas de los análisis
de V-ref cuesta en el hilo de Blender unas centésimas (las 500 000, 0,9 s; RNF-005-06)."""
GEOMETRY_OFFSETS = "_offsets"
"""Los ``offsets`` (n + 1) de los blobs de la geometría de unas filas (``geom_offsets``)."""

_DATES = frozenset({"start_date", "end_date"})
_EXTRA = "extra"
_EMPTY_EXTRA = "{}"
_NO_EXTRA: Mapping[str, Any] = MappingProxyType({})
_CATALOG_PARTS: tuple[tuple[str, type], ...] = (
    ("lithology", LithologyCode), ("elements", Element), ("sectors", CatalogEntry),
    ("groups", CatalogEntry), ("zones", CatalogEntry))
_FLOAT_TYPES = frozenset({"DOUBLE", "REAL", "FLOAT"})
_INT_TYPES = frozenset({"INTEGER", "BOOLEAN"})
_TEXT_TYPES = frozenset({"TEXT", "DATE"})
_NONE = type(None)
_STR = frozenset({str})
_NUMBERS = frozenset({float, int, _NONE})  # los de una columna de reales sin más comprobar
_INTEGERS = frozenset({int, bool, _NONE})  # ídem, de enteros


# --- Textos ------------------------------------------------------------------------------------


def _encode_texts(values: Sequence[Any], what: str) -> tuple[np.ndarray, np.ndarray | None]:
    """Unos textos (o ``None``) en UTF-8 (``S``) y su máscara de nulos (``None`` si no hay
    ninguno). ``TypeError`` con lo que no es un texto."""
    items = list(values)
    types = set(map(type, items))  # de una vez: el caso de casi todas las columnas (T52)
    nulls: np.ndarray | None = None
    if _NONE in types:
        nulls = np.array([item is None for item in items], dtype=np.bool_)
        items = ["" if item is None else item for item in items]
        types.discard(_NONE)
    if not types <= _STR:
        for item in items:
            if not isinstance(item, str):
                raise TypeError(f"{what} es un texto o None, no {item!r}")
    if not items:
        return np.zeros(0, dtype="S1"), nulls
    try:
        found = np.array(items, dtype=np.bytes_)  # ASCII, de una vez
    except UnicodeEncodeError:
        found = np.array([item.encode("utf-8") for item in items], dtype=np.bytes_)
    return found, nulls


def _decode_texts(array: np.ndarray, nulls: np.ndarray | None) -> list[str | None]:
    """Los textos de :func:`_encode_texts` (``None`` donde la máscara)."""
    if array.dtype.kind != "S":
        raise ValueError(f"unos textos van en UTF-8 (S), no en {array.dtype}")
    try:
        found: list[str | None] = array.astype(np.str_).tolist()  # ASCII, de una vez
    except UnicodeDecodeError:
        found = [item.decode("utf-8") for item in array.tolist()]
    if nulls is not None:
        for index in np.flatnonzero(nulls).tolist():
            found[index] = None
    return found


def _put_texts(arrays: dict[str, np.ndarray], key: str, values: Sequence[Any],
               what: str) -> None:
    found, nulls = _encode_texts(values, what)
    arrays[key] = found
    if nulls is not None:
        arrays[key + NULL_SUFFIX] = nulls


def _get_texts(arrays: Mapping[str, np.ndarray], key: str) -> list[str | None]:
    return _decode_texts(arrays[key], arrays.get(key + NULL_SUFFIX))


def _put_integers(arrays: dict[str, np.ndarray], key: str, values: Sequence[Any],
                  what: str) -> None:
    """Unos enteros opcionales (``int`` o ``None``, una columna ``object`` del modelo) en
    int64 con su máscara de nulos."""
    for value in values:
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
            raise TypeError(f"{what} es un entero o None, no {value!r}")
    arrays[key] = np.array([0 if value is None else value for value in values], dtype=np.int64)
    arrays[key + NULL_SUFFIX] = np.fromiter((value is None for value in values), dtype=np.bool_,
                                            count=len(values))


def _get_integers(arrays: Mapping[str, np.ndarray], key: str) -> list[int | None]:
    found: list[int | None] = arrays[key].tolist()
    nulls = arrays.get(key + NULL_SUFFIX)
    if nulls is not None:
        for index in np.flatnonzero(nulls).tolist():
            found[index] = None
    return found


def _json_array(value: Any) -> np.ndarray:
    return np.frombuffer(json.dumps(value, ensure_ascii=False, allow_nan=False)
                         .encode("utf-8"), dtype=np.uint8).copy()


def _json_of(array: np.ndarray) -> Any:
    return json.loads(np.asarray(array, dtype=np.uint8).tobytes().decode("utf-8"))


# --- Columnas del modelo -----------------------------------------------------------------------


def _objects(values: Sequence[Any]) -> np.ndarray:
    found = np.empty(len(values), dtype=object)
    found[:] = list(values)
    return found


def _extra_text(value: Any) -> str:
    return canonical_json(dict(value)).decode("utf-8") if value else _EMPTY_EXTRA


def _extra_of(text: str | None) -> Mapping[str, Any]:
    if text is None or text == _EMPTY_EXTRA:
        return _NO_EXTRA
    return MappingProxyType(json.loads(text))


def _put_columns(arrays: dict[str, np.ndarray], key: str, columns: Any,
                 rows: slice = slice(None)) -> None:
    """Las filas ``rows`` (todas, por defecto) de las columnas ``columns`` (una clase de
    columnas del modelo) con el prefijo ``key``."""
    for item in dataclasses.fields(columns):
        values = getattr(columns, item.name)[rows]
        name = f"{key}_{item.name}"
        if values.dtype != object:
            arrays[name] = np.ascontiguousarray(values)
        elif item.name == _EXTRA:
            arrays[name], _ = _encode_texts([_extra_text(v) for v in values.tolist()], name)
        elif item.name in _DATES:
            _put_texts(arrays, name, [None if day is None else day.isoformat()
                                      for day in values.tolist()], name)
        else:
            plain = values.tolist()
            # Un entero (no un sí/no) entre los valores, mirado por sus tipos (T52).
            if any(issubclass(kind, int) and not issubclass(kind, bool)
                   for kind in set(map(type, plain))):
                _put_integers(arrays, name, plain, name)  # un entero opcional
            else:
                _put_texts(arrays, name, plain, name)


def _get_columns(arrays: Mapping[str, np.ndarray], key: str, kind: type,
                 step: Callable[[], object]) -> Any:
    """Las columnas ``kind`` de los arrays con el prefijo ``key``; ``step()`` antes de cada
    una."""
    empty = kind.empty()
    values: dict[str, np.ndarray] = {}
    for item in dataclasses.fields(kind):
        step()
        name = f"{key}_{item.name}"
        dtype = getattr(empty, item.name).dtype
        if name not in arrays:
            raise ValueError(f"faltan los valores «{name}» de unas columnas de sondeos")
        if dtype != object:
            found = np.asarray(arrays[name])
            if found.dtype != dtype or found.ndim != 1:
                raise ValueError(f"«{name}» es {dtype} de una dimensión, no {found.dtype} "
                                 f"{found.shape}")
            values[item.name] = found
        elif item.name == _EXTRA:
            values[item.name] = _objects([_extra_of(text)
                                          for text in _decode_texts(arrays[name], None)])
        elif item.name in _DATES:
            values[item.name] = _objects([None if text is None else dt.date.fromisoformat(text)
                                          for text in _get_texts(arrays, name)])
        elif arrays[name].dtype.kind == "i":
            values[item.name] = _objects(_get_integers(arrays, name))
        else:
            values[item.name] = _objects(_get_texts(arrays, name))
    return kind(**values)


def catalogs_json(catalogs: Catalogs) -> dict[str, list[dict[str, Any]]]:
    """Los catálogos en JSON (los que tienen algo): cada registro con sus campos, las
    enumeraciones por su texto y ``extra`` como objeto. :func:`catalogs_of` los devuelve
    iguales (también en la petición de un trabajo: los catálogos del proyecto)."""
    if not isinstance(catalogs, Catalogs):
        raise TypeError(f"los catálogos son un Catalogs, no {catalogs!r}")
    found: dict[str, list[dict[str, Any]]] = {}
    for attribute, _kind in _CATALOG_PARTS:
        records = []
        for record in getattr(catalogs, attribute):
            values: dict[str, Any] = {}
            for item in dataclasses.fields(record):
                value = getattr(record, item.name)
                if isinstance(value, Mapping):
                    value = dict(value)
                elif isinstance(value, str):
                    value = str(value)  # también una enumeración: su texto
                elif isinstance(value, float) and math.isnan(value):
                    value = None
                values[item.name] = value
            records.append(values)
        if records:
            found[attribute] = records
    return found


def catalogs_of(value: object) -> Catalogs:
    """Los catálogos de :func:`catalogs_json`; ``ValueError`` o ``TypeError`` si no lo son."""
    if not isinstance(value, Mapping):
        raise ValueError(f"los catálogos son {{catálogo: registros}}, no {value!r}")
    kinds = dict(_CATALOG_PARTS)
    unknown = sorted(str(key) for key in value if key not in kinds)
    if unknown:
        raise ValueError(f"catálogos desconocidos: {unknown}")
    return Catalogs(**{attribute: tuple(kinds[attribute](**record) for record in records)
                       for attribute, records in value.items()})


def tables_arrays(tables: Mapping[str, Any], catalogs: Catalogs | None = None, *,
                  prefix: str = "") -> dict[str, np.ndarray]:
    """Los arrays de las tablas ``tables`` (nombre de :data:`~.model.TABLES` → sus columnas;
    las vacías no van) y los catálogos ``catalogs`` (si tienen algo), con las claves
    ``<prefix><tabla>_<campo>`` y ``<prefix>catalogs`` (véase el módulo). ``ValueError`` con
    una tabla que no es del modelo; ``TypeError`` con columnas de otra clase."""
    arrays: dict[str, np.ndarray] = {}
    for name, columns in tables.items():
        _check_table(name, columns)
        if len(columns):
            _put_columns(arrays, f"{prefix}{name}", columns)
    if catalogs is not None:
        if not isinstance(catalogs, Catalogs):
            raise TypeError(f"los catálogos son un Catalogs, no {catalogs!r}")
        found = catalogs_json(catalogs)
        if found:
            arrays[f"{prefix}{CATALOGS}"] = _json_array(found)
    return arrays


def _check_table(name: str, columns: Any) -> None:
    """``ValueError`` si ``name`` no es una tabla del modelo; ``TypeError`` si ``columns`` no
    son sus columnas."""
    kind = TABLES.get(name)
    if kind is None:
        raise ValueError(f"«{name}» no es una tabla de sondeos: es una de {list(TABLES)}")
    if type(columns) is not kind:
        raise TypeError(f"«{name}» son unas {kind.__name__}, no {columns!r}")


def table_parts(name: str, columns: Any, *, rows: int | None = None,
                prefix: str = "") -> Iterator[dict[str, np.ndarray]]:
    """Los arrays de :func:`tables_arrays` de la tabla ``name`` (sus columnas ``columns``)
    por partes de como mucho ``rows`` filas (por defecto, :data:`PART_ROWS`), en su orden:
    :func:`merge_parts` de todas da los de la tabla entera, bit a bit (T53: el hilo de
    Blender convierte una parte por paso; RNF-005-06). Una tabla vacía no da ninguna.
    ``ValueError`` o ``TypeError`` como :func:`tables_arrays`, también si una columna de
    enteros opcionales (``category``, ``priority``) trae un entero en una parte y un texto en
    otra; ``ValueError`` si ``rows`` no es un entero ≥ 1."""
    size = PART_ROWS if rows is None else rows
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise ValueError(f"las filas de una parte son un entero ≥ 1, no {size!r}")
    _check_table(name, columns)
    key = f"{prefix}{name}"
    optional = [f"{key}_{item.name}" for item in dataclasses.fields(columns)
                if getattr(columns, item.name).dtype == object
                and item.name != _EXTRA and item.name not in _DATES]
    kinds: dict[str, set[str]] = {column: set() for column in optional}
    for start in range(0, len(columns), size):
        arrays: dict[str, np.ndarray] = {}
        _put_columns(arrays, key, columns, slice(start, start + size))
        for column in optional:  # enteros en una parte y textos en otra: no se juntarían
            found = kinds[column]
            if arrays[column].dtype.kind == "i":
                found.add("i")
            elif not bool(np.all(arrays.get(column + NULL_SUFFIX, False))):
                found.add("S")  # algún texto (una parte sin ningún valor vale para las dos)
            if len(found) > 1:
                raise TypeError(f"{column} es un entero o None en unas filas y un texto en "
                                "otras")
        yield arrays


def merge_parts(parts: Sequence[Mapping[str, np.ndarray]]) -> dict[str, np.ndarray]:
    """Los arrays de una tabla juntos desde sus partes de :func:`table_parts` (en su orden):
    los de :func:`tables_arrays` de la tabla entera, bit a bit (los textos, con el ancho
    mayor; la máscara de nulos de una parte que no la trae, sin nulos; los enteros opcionales
    de una parte sin ninguno, ceros con su máscara). Sin partes, ninguno. ``ValueError`` si
    no son partes de una misma tabla."""
    if len(parts) < 2:
        return {key: value for part in parts for key, value in part.items()}
    sizes = []
    for part in parts:
        lengths = {len(array) for array in part.values()}
        if len(lengths) != 1:
            raise ValueError("una parte de una tabla tiene arrays de longitudes distintas")
        sizes.append(lengths.pop())
    keys = list(dict.fromkeys(key for part in parts for key in part))
    merged: dict[str, np.ndarray] = {}
    for key in keys:
        if key.endswith(NULL_SUFFIX) and key.removesuffix(NULL_SUFFIX) in keys:
            continue  # va con su columna
        if any(key not in part for part in parts):
            raise ValueError(f"a una parte de la tabla le falta «{key}»")
        masks = [part.get(key + NULL_SUFFIX) for part in parts]
        values = [np.asarray(part[key]) for part in parts]
        kinds = {array.dtype.kind for array in values}
        if kinds == {"i", "S"}:  # enteros opcionales y una parte sin ninguno
            for index, (array, mask) in enumerate(zip(values, masks, strict=True)):
                if array.dtype.kind == "S":
                    if mask is None or not bool(np.all(mask)):
                        raise ValueError(f"«{key}» trae enteros en unas partes y textos en "
                                         "otras")
                    values[index] = np.zeros(len(array), dtype=np.int64)
        elif len({array.dtype for array in values if array.dtype.kind != "S"}) > 1 or (
                "S" in kinds and len(kinds) > 1):
            raise ValueError(f"«{key}» tiene tipos distintos en sus partes")
        merged[key] = np.concatenate(values)
        if any(mask is not None for mask in masks):
            merged[key + NULL_SUFFIX] = np.concatenate([
                np.zeros(size, dtype=np.bool_) if mask is None else mask
                for mask, size in zip(masks, sizes, strict=True)])
    return merged


def tables_of(arrays: Mapping[str, np.ndarray], *, prefix: str = "",
              progress: Callable[[float], object] | None = None
              ) -> tuple[dict[str, Any], Catalogs]:
    """Las tablas (todas las del modelo: vacías las que no vienen) y los catálogos de
    :func:`tables_arrays`, bit a bit; ``progress(fracción)`` antes de cada columna (las de
    V-ref, 0,8 s: un trabajo da su avance y mira la cancelación). ``ValueError`` si a una
    tabla le falta un campo o tiene otro tipo."""
    present = {name: kind for name, kind in TABLES.items()
               if f"{prefix}{name}_{dataclasses.fields(kind)[0].name}" in arrays}
    total = sum(len(dataclasses.fields(kind)) for kind in present.values()) or 1
    done = [0]

    def step() -> None:
        if progress is not None:
            progress(done[0] / total)
        done[0] += 1

    tables: dict[str, Any] = {}
    for name, kind in TABLES.items():
        tables[name] = (_get_columns(arrays, f"{prefix}{name}", kind, step) if name in present
                        else kind.empty())
    raw = arrays.get(f"{prefix}{CATALOGS}")
    catalogs = Catalogs() if raw is None else catalogs_of(_json_of(raw))
    return tables, catalogs


def set_arrays(dset: DrillholeSet, *, prefix: str = "") -> dict[str, np.ndarray]:
    """Los arrays de un :class:`~.model.DrillholeSet` (sin su CRS ni su referencia vertical,
    que van en la petición): :func:`tables_arrays` de sus tablas y sus catálogos."""
    if not isinstance(dset, DrillholeSet):
        raise TypeError(f"se guarda un DrillholeSet, no {dset!r}")
    return tables_arrays({name: getattr(dset, name) for name in TABLES}, dset.catalogs,
                         prefix=prefix)


def set_of(arrays: Mapping[str, np.ndarray], *, crs: Any, vertical: Any, prefix: str = "",
           progress: Callable[[float], object] | None = None) -> DrillholeSet:
    """El :class:`~.model.DrillholeSet` de :func:`set_arrays` en ``crs`` y ``vertical``
    (``progress``, el de :func:`tables_of`)."""
    tables, catalogs = tables_of(arrays, prefix=prefix, progress=progress)
    return DrillholeSet(crs=crs, vertical=vertical, catalogs=catalogs, **tables)


def entry_arrays(entry: Any, *, prefix: str = "") -> dict[str, np.ndarray]:
    """Los arrays de lo importado de una entrada (un ``build_base.SourceEntry``): sus tablas y
    sus catálogos (su uid, su declaración y su nombre van en la petición)."""
    return tables_arrays({name: getattr(entry, name) for name in TABLES}, entry.catalogs,
                         prefix=prefix)


def entry_of(arrays: Mapping[str, np.ndarray], *, input_uid: str, declaration: Any,
             label: str | None = None, prefix: str = "",
             progress: Callable[[float], object] | None = None) -> Any:
    """El ``build_base.SourceEntry`` de :func:`entry_arrays` (las filas hijas, sin enlazar;
    ``progress``, el de :func:`tables_of`)."""
    from .build_base import SourceEntry

    tables, catalogs = tables_of(arrays, prefix=prefix, progress=progress)
    return SourceEntry(input_uid, declaration, catalogs=catalogs, label=label, **tables)


def dataclass_arrays(prefix: str, value: Any) -> dict[str, np.ndarray]:
    """Los arrays de un registro de arrays del dominio (``view_data.CurveArrays``,
    ``BarArrays``…): cada campo con la clave ``<prefix>_<campo>``; los arrays de textos
    (``object``), en UTF-8 con su máscara de nulos; un escalar, un array de dimensión 0."""
    arrays: dict[str, np.ndarray] = {}
    for item in dataclasses.fields(value):
        found = getattr(value, item.name)
        key = f"{prefix}_{item.name}"
        if isinstance(found, np.ndarray) and found.dtype == object:
            _put_texts(arrays, key, found.tolist(), key)
        else:
            arrays[key] = np.asarray(found)
    return arrays


def dataclass_of(arrays: Mapping[str, np.ndarray], prefix: str, kind: type) -> Any:
    """El registro ``kind`` de :func:`dataclass_arrays` (los arrays, bit a bit)."""
    values: dict[str, Any] = {}
    for item in dataclasses.fields(kind):
        key = f"{prefix}_{item.name}"
        found = arrays[key]
        if found.dtype.kind == "S":
            values[item.name] = _objects(_get_texts(arrays, key))
        elif found.ndim == 0:
            values[item.name] = found.item()
        else:
            values[item.name] = found
    return kind(**values)


# --- npz ---------------------------------------------------------------------------------------


def save_npz(path: Path | str, arrays: Mapping[str, np.ndarray]) -> None:
    """``arrays`` en el npz ``path``, sin comprimir (los ficheros de paso de un trabajo, como
    los de la 006) y sin objetos de Python (``ValueError``)."""
    for name, array in arrays.items():
        if not isinstance(array, np.ndarray) or array.dtype.hasobject:
            raise ValueError(f"«{name}» no es un array de numpy sin objetos de Python")
    with open(path, "wb") as stream:
        np.savez(stream, **arrays)


def load_npz(path: Path | str) -> dict[str, np.ndarray]:
    """Los arrays del npz ``path``, leídos sin *pickle* (ARQ-16); ``ValueError`` si no es un
    npz legible."""
    try:
        with np.load(path, allow_pickle=False) as data:
            return {key: data[key] for key in data.files}
    except (OSError, EOFError) as error:
        raise ValueError(f"«{Path(path).name}» no es un npz legible ({error})") from None


# --- Filas de una tabla del proyecto ---------------------------------------------------------


def _layout_columns(layout: Any) -> list[tuple[str, str]]:
    """(columna, tipo de SQL) de cada valor de una fila de ``layout``: la geometría y las
    columnas."""
    found = [("geom", "GEOMETRY")] if layout.geometry_type is not None else []
    found += [(column.name, column.sql_type.upper()) for column in layout.columns]
    return found


def rows_arrays(layout: Any, rows: Sequence[Sequence[Any]], *,
                progress: Callable[[float], object] | None = None) -> dict[str, np.ndarray]:
    """Los arrays de las filas ``rows`` de la tabla de ``layout`` (las de
    ``schema.insert_rows``), una entrada por columna (véase el módulo), con
    ``progress(fracción)`` antes de cada columna (las 500 000 filas de los análisis de V-ref,
    1 s). ``ValueError`` con una fila de otro ancho; ``TypeError`` con un valor que no es de
    su tipo."""
    columns = _layout_columns(layout)
    width = len(columns)
    for number, row in enumerate(rows, start=1):
        if len(row) != width:
            raise ValueError(f"la fila {number} de «{layout.name}» tiene {len(row)} valores y "
                             f"no {width}")
    values = [list(column) for column in zip(*rows, strict=True)] if rows else [
        [] for _ in columns]
    arrays: dict[str, np.ndarray] = {"rows": np.array([len(rows)], dtype=np.int64)}
    for number, ((name, sql_type), column) in enumerate(zip(columns, values, strict=True)):
        if progress is not None:
            progress(number / width)
        what = f"«{layout.name}.{name}»"
        if sql_type == "GEOMETRY":
            nulls = np.fromiter((value is None for value in column), dtype=np.bool_,
                                count=len(column))
            blobs = [b"" if value is None else bytes(value) for value in column]
            arrays[name] = np.frombuffer(b"".join(blobs), dtype=np.uint8).copy()
            arrays[name + GEOMETRY_OFFSETS] = np.concatenate(
                ([0], np.cumsum([len(blob) for blob in blobs], dtype=np.int64))).astype(np.int64)
            arrays[name + NULL_SUFFIX] = nulls
        elif sql_type in _FLOAT_TYPES:
            if not set(map(type, column)) <= _NUMBERS:  # de una vez si son de su tipo (T52)
                for value in column:
                    if value is not None and (isinstance(value, bool)
                                              or not isinstance(value, int | float)):
                        raise TypeError(f"{what} es un número o None, no {value!r}")
            arrays[name] = np.array([math.nan if value is None else value for value in column],
                                    dtype=np.float64)
        elif sql_type in _INT_TYPES:
            types = set(map(type, column))
            if types <= _INTEGERS:  # int, bool o None: de una vez (T52)
                plain = column if _NONE not in types else [0 if value is None else value
                                                           for value in column]
                arrays[name] = np.array(plain, dtype=np.int64)
            else:
                for value in column:
                    if value is not None and not isinstance(value, int | np.integer):
                        raise TypeError(f"{what} es un entero o None, no {value!r}")
                arrays[name] = np.array([0 if value is None else int(value)
                                         for value in column], dtype=np.int64)
            arrays[name + NULL_SUFFIX] = np.array([value is None for value in column],
                                                  dtype=np.bool_)
        elif sql_type in _TEXT_TYPES:
            _put_texts(arrays, name, column, what)
        else:  # pragma: no cover - un tipo de SQL nuevo en drillholes.schema
            raise ValueError(f"{what}: tipo de SQL sin codificación ({sql_type})")
    return arrays


class TableRows(Sequence[tuple[Any, ...]]):
    """Las filas de una tabla de ``layout`` desde los arrays de :func:`rows_arrays` (véase el
    módulo): una secuencia de solo lectura que decodifica cada trozo al pedirlo, con los
    mismos valores que se codificaron (un NaN de una columna ``DOUBLE``, ``None``: los dos se
    guardan como ``NULL``)."""

    def __init__(self, layout: Any, arrays: Mapping[str, np.ndarray]) -> None:
        self.layout = layout
        self._columns = _layout_columns(layout)
        try:
            self._count = int(np.asarray(arrays["rows"]).reshape(-1)[0])
            for name, sql_type in self._columns:
                found = arrays[name]
                expected = (self._count + 1 if sql_type == "GEOMETRY" else self._count)
                size = (len(arrays[name + GEOMETRY_OFFSETS]) if sql_type == "GEOMETRY"
                        else len(found))
                if size != expected:
                    raise ValueError(f"«{name}» tiene {size} valores y no {expected}")
        except KeyError as error:
            raise ValueError(f"a las filas de «{layout.name}» les falta {error}") from None
        self._arrays = arrays

    def __len__(self) -> int:
        return self._count

    @overload
    def __getitem__(self, index: int) -> tuple[Any, ...]: ...

    @overload
    def __getitem__(self, index: slice) -> list[tuple[Any, ...]]: ...

    def __getitem__(self, index: int | slice) -> tuple[Any, ...] | list[tuple[Any, ...]]:
        if isinstance(index, slice):
            start, stop, step = index.indices(self._count)
            if step != 1:
                return [self[i] for i in range(start, stop, step)]
            return self._rows(start, stop)
        position = index + self._count if index < 0 else index
        if not 0 <= position < self._count:
            raise IndexError(f"la fila {index} no está en «{self.layout.name}» "
                             f"({self._count} filas)")
        return self._rows(position, position + 1)[0]

    def __iter__(self) -> Iterator[tuple[Any, ...]]:
        step = 5000
        for first in range(0, self._count, step):
            yield from self._rows(first, min(first + step, self._count))

    def _rows(self, start: int, stop: int) -> list[tuple[Any, ...]]:
        if stop <= start:
            return []
        arrays = self._arrays
        values: list[list[Any]] = []
        for name, sql_type in self._columns:
            nulls = arrays.get(name + NULL_SUFFIX)
            part = None if nulls is None else nulls[start:stop]
            if sql_type == "GEOMETRY":
                offsets = arrays[name + GEOMETRY_OFFSETS]
                data = arrays[name]
                found: list[Any] = [
                    None if part[i] else data[offsets[row]:offsets[row + 1]].tobytes()
                    for i, row in enumerate(range(start, stop))]
            elif sql_type in _FLOAT_TYPES:
                found = [None if value != value else value
                         for value in arrays[name][start:stop].tolist()]
            elif sql_type in _INT_TYPES:
                found = arrays[name][start:stop].tolist()
                if part is not None:
                    for i in np.flatnonzero(part).tolist():
                        found[i] = None
            else:
                found = _decode_texts(arrays[name][start:stop], part)
            values.append(found)
        return list(zip(*values, strict=True))
