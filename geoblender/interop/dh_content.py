# SPDX-License-Identifier: GPL-3.0-or-later
"""Lectores de contenido de los sondeos (spec 005, T39; RF-005-03, RF-005-12; RF-008-08,
RF-008-09, RF-008-14; ADR-0024 §4 a §7; plan 005 §5.6.2, D-15 y D-16).

Tres :class:`~..core.content.readers.ContentReader` de la 008, declarados aquí porque leer
formatos ajenos es de ``io`` y ``drillholes`` no puede importar ``interop`` (ARQ-07). Cada uno
es **una sola función** generadora, la misma al importar (en el trabajo de la importación), al
comprobar la entrada en el hilo de Blender y en el trabajo ``core_content_hash`` (este módulo
está en su lista estática): lee su fuente con las piezas del importador de la 005, escribe lo
que lee en el ``ContentHasher`` de su petición y da su progreso tras cada trozo (cada ``yield``
es un punto de cancelación). Lo que el importador no admite es el mismo error suyo
(``MappingError``, ``DeclarationError``, ``TableError``, ``RecminSchemaError``, ``MdbError``);
ninguno crea, cambia ni borra nada junto a su fuente (RF-005-03, RF-008-14).

- :data:`DH_CSV` (``io.dh_csv@1``) y :data:`DH_XLSX` (``io.dh_xlsx@1``): una tabla de un papel
  (bocas, desviaciones, litología, análisis en columnas o en filas, catálogo de litologías o de
  elementos) de un CSV o de una hoja de un libro XLSX; tipo ``drillholes`` las bocas y ``table``
  las demás (``drillholes.provenance.input_kind``). Se lee con ``interop.csv_tables`` o
  ``interop.xlsx_tables`` y se interpreta con ``interop.drillholes_tabular.read_role`` (la
  lectura del importador, D-15) con el papel, la correspondencia de columnas y las convenciones
  de las declaraciones (``DECL``) y los ajustes de lectura de la petición. Se hashea una tabla
  sin orden (``ordered = false``) con las columnas de su papel (:data:`COLUMNS`): los valores
  interpretados, en el CRS, el datum y los convenios declarados, sin transformar (números en
  float64, ausente ``null``; fechas; la marca de límite; la unidad canónica), sin el texto
  original de un valor ni de una unidad (el decimal y el formato son de lectura), y, por cada
  fila de la fuente con algún rechazo, una fila más con ``raw``, el JSON canónico de sus campos
  tal como están (las demás columnas, ``null``): una fila que no se importa cuenta con su texto.
  Las columnas sin papel en la correspondencia no se importan y no cuentan; las bocas, con la
  orientación en boca de su fila.
- :data:`RECMIN_MDB` (``io.recmin_mdb@1``, ``drillholes``, ``needs_copy``): una base de RecMin
  (MDB o ACCDB, Jet o ACE). Se copia siempre a una carpeta temporal privada (el motor de Access
  crea su fichero de bloqueo junto a la base que abre: la fuente no se toca, tampoco en el
  hilo), se extrae con el ``MdbExtractor`` (``interop.ports``; por defecto, el de
  ``adapters.registry.mdb_extractor()``, ADR-0018) en un hilo, con su avance y su cancelación
  (≤ 2 s, el ``powershell.exe`` hijo terminado), y se hashea un compuesto con **una parte por
  tabla que lee el importador** (``interop.recmin.schema.layout``: las conocidas de los
  esquemas 11 y 12 y las reconocidas por su forma; no ``NOTAS``, ``SECCIONES`` ni las
  desconocidas), con su nombre en la base: cada una, una tabla sin orden con sus columnas por
  nombre (sin mayúsculas) y el tipo de su ``DBTYPE`` (:data:`DBTYPE_FIELDS`): los Single por su
  decimal más corto (el valor que se guarda, RF-005-02), los decimales exactos y las fechas en
  ISO como texto. El motor (Jet 4 o ACE), el orden de las filas y de las columnas no cuentan.
  Una base sin la tabla de sondeos es ``dh.recmin_table_missing``; sin las declaraciones que
  necesita, ``dh.declaration_missing``.

**Declaraciones** (``DECL``, las de ``drillholes.provenance.source_declarations``): ``crs_h`` y
``crs_v`` (los de unas bocas o una base de RecMin; «no aplica» en las demás tablas) y
``conventions``: el papel (``role``) y la correspondencia de columnas (``mapping``) de una tabla
y lo de la declaración que es contenido de su papel (``ROLE_CONVENTIONS`` y
``RECMIN_CONVENTIONS``); otra convención es ``ValueError``. **Ajustes de lectura**
(``ReadRequest.settings``, los de la entrada): los de ``drillholes.provenance.READING_SETTINGS``
(``encoding``, ``separator`` y ``header_row`` en un CSV; ``sheet`` y ``header_row`` en un XLSX;
todos obligatorios), ``decimal`` (obligatorio en una tabla) y ``date_format``; pueden llevar
también las convenciones, que tienen que ser las de ``DECL``. El separador, el decimal, la
codificación, la hoja y la fila de cabecera no son contenido: el mismo CSV con «;» y coma o con
«,» y punto, y la misma tabla en un XLSX, dan el mismo hash.

Importar este módulo no registra nada (:data:`CONTENT_READERS` los reúne para que los registre
``bl/ops/dh.py``) y no carga lo que leen: ``interop.drillholes_tabular``, las hojas XLSX,
``interop.recmin`` y ``drillholes`` se importan al leer (habilitar Geoblender no paga su
importación). Python puro y numpy (ADR-0004).
"""

from __future__ import annotations

import datetime as dt
import math
import os
import queue
import tempfile
import threading
from collections.abc import Callable, Generator, Iterator, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import numpy as np

from ..core.content.encoder import FINISH_STEP, RowEncoder
from ..core.content.readers import MAIN_ROLE, ContentReader, ReadRequest
from ..core.hashing import canonical_json
from .ports import (
    DBTYPE_BOOL,
    DBTYPE_BYTES,
    DBTYPE_CY,
    DBTYPE_DATE,
    DBTYPE_DECIMAL,
    DBTYPE_I2,
    DBTYPE_I4,
    DBTYPE_NUMERIC,
    DBTYPE_R4,
    DBTYPE_R8,
    DBTYPE_UI1,
    DBTYPE_WSTR,
    MdbExtractor,
    RawTable,
)

if TYPE_CHECKING:
    from ..core.georef import CrsRef, VerticalRef
    from ..drillholes.model import SourceDeclaration
    from .csv_tables import Table
    from .drillholes_tabular import RoleRows

__all__ = [
    "COLUMNS",
    "CONTENT_READERS",
    "DBTYPE_FIELDS",
    "DH_CSV",
    "DH_XLSX",
    "RECMIN_MDB",
    "mdb_extractor",
    "read_dh_csv",
    "read_dh_xlsx",
    "read_recmin_mdb",
    "use_mdb_extractor",
]

# --- Las columnas que se hashean ----------------------------------------------------------------

_TEXT, _FLOAT, _INT, _BOOL, _DATE = "text", "float", "int", "bool", "date"
_RAW = ("raw", _TEXT)
COLUMNS: Mapping[str, tuple[tuple[str, str], ...]] = MappingProxyType({
    "collar": (
        ("name", _TEXT), ("x", _FLOAT), ("y", _FLOAT), ("z", _FLOAT), ("depth", _FLOAT),
        ("azimuth", _FLOAT), ("inclination", _FLOAT), ("hole_type", _TEXT),
        ("planned", _BOOL), ("grade_control", _BOOL), ("category", _INT),
        ("priority", _INT), ("sector", _TEXT), ("group", _TEXT), ("campaign", _TEXT),
        ("start_date", _DATE), ("end_date", _DATE), ("survey_method", _TEXT),
        ("external_id", _TEXT), ("comments", _TEXT), _RAW,
    ),
    "survey": (
        ("hole", _TEXT), ("depth", _FLOAT), ("azimuth", _FLOAT), ("inclination", _FLOAT),
        ("method", _TEXT), ("external_id", _TEXT), _RAW,
    ),
    "lithology": (
        ("hole", _TEXT), ("from_m", _FLOAT), ("to_m", _FLOAT), ("code", _TEXT),
        ("description", _TEXT), ("logged_by", _TEXT), ("external_id", _TEXT), _RAW,
    ),
    "assay": (
        ("hole", _TEXT), ("from_m", _FLOAT), ("to_m", _FLOAT), ("element", _TEXT),
        ("value", _FLOAT), ("unit", _TEXT), ("detection_flag", _TEXT), ("sample_id", _TEXT),
        ("lab", _TEXT), ("method", _TEXT), ("batch", _TEXT), ("external_id", _TEXT), _RAW,
    ),
    "lithology_catalog": (
        ("code", _TEXT), ("description", _TEXT), ("color", _TEXT), ("pattern", _TEXT),
        ("density", _FLOAT), ("sort_order", _INT), ("external_id", _TEXT), _RAW,
    ),
    "element_catalog": (
        ("code", _TEXT), ("name", _TEXT), ("unit", _TEXT), ("decimals", _INT),
        ("detection_limit", _FLOAT), ("sort_order", _INT), ("external_id", _TEXT), _RAW,
    ),
})
"""Las columnas de la tabla que hashean ``io.dh_csv@1`` e ``io.dh_xlsx@1``, por papel (los
análisis en columnas y en filas, las de ``"assay"``), en su orden: nunca cambian (ADR-0024 §6).
``raw`` es el texto de una fila con algún rechazo; ``null`` en las interpretadas."""
_COLUMNS_OF_ROLE: Mapping[str, str] = MappingProxyType({
    "collar": "collar", "survey": "survey", "lithology": "lithology",
    "assay_wide": "assay", "assay_long": "assay",
    "lithology_catalog": "lithology_catalog", "element_catalog": "element_catalog",
})
DBTYPE_FIELDS: Mapping[int, str] = MappingProxyType({
    DBTYPE_I2: _INT, DBTYPE_I4: _INT, DBTYPE_UI1: _INT,
    DBTYPE_R4: _FLOAT, DBTYPE_R8: _FLOAT,
    DBTYPE_BOOL: _BOOL,
    DBTYPE_CY: _TEXT, DBTYPE_DECIMAL: _TEXT, DBTYPE_NUMERIC: _TEXT,
    DBTYPE_DATE: _TEXT, DBTYPE_WSTR: _TEXT, DBTYPE_BYTES: _TEXT,
})
"""El tipo con que ``io.recmin_mdb@1`` hashea cada ``DBTYPE`` de una columna de RecMin; uno que
no está aquí, como texto (el texto invariante que da el extractor)."""

# --- Avance y estimación ------------------------------------------------------------------------

READ_SHARE = 0.25
"""La parte del avance de una tabla que es leer el fichero (el resto: interpretar y hashear)."""
INTERPRET_SHARE = 0.55
"""Hasta dónde llega el avance de una tabla al acabar de interpretarla."""
ROWS_SHARE = 0.9
"""La parte del hash de una tabla que es añadir sus filas (el resto, cerrarlo)."""
COPY_SHARE = 0.05
"""La parte del avance de una base de RecMin que es copiarla a la carpeta privada."""
EXTRACT_SHARE = 0.80
"""Hasta dónde llega el avance de una base de RecMin al acabar de extraerla."""
ROW_BYTES = 64
"""Lo que se cuenta por fila para repartir el hash en trozos de ``chunk_bytes``."""
POLL_S = 0.02
"""Cada cuánto da su avance el lector de RecMin mientras espera al extractor (un tic del hilo
de Blender)."""
CANCEL_WAIT_S = 10.0
"""Lo que se espera, como mucho, a que el extractor pare tras pedirle que cancele (lo hace en
≤ 2 s con su hijo terminado)."""
CSV_BYTES_PER_S = 500_000
"""Los bytes de un CSV de sondeos que lee, interpreta y hashea ``io.dh_csv@1`` por segundo, a
la baja: su estimación. Medido en el PC de referencia con V-ref: el peor, los análisis en
columnas (24 elementos, una fila hasheada por valor), 2,9 MB en 4,7 s (0,61 MB/s); la
litología, 2,6 MB/s."""
XLSX_BYTES_PER_S = 300_000
"""Ídem, ``io.dh_xlsx@1`` (medido: los análisis de V-ref en un XLSX de 2,8 MB, 6,6 s,
0,43 MB/s)."""
MDB_OVERHEAD_S = 1.5
"""Lo que tarda como poco ``io.recmin_mdb@1``: copiar, lanzar el ``powershell.exe`` y abrir la
base con el motor (más de :data:`~..core.content.readers.INLINE_LIMIT_S`: una base de RecMin
se hashea siempre en el trabajo ``core_content_hash`` si hay quien lo lance)."""
MDB_BYTES_PER_S = 3_000_000
"""Los bytes de una base de RecMin que extrae y hashea ``io.recmin_mdb@1`` por segundo, a la
baja (medido: una base ACE de 25 MB con 458 752 muestras, 6,4 s, 3,9 MB/s)."""
PRIVATE_PREFIX = "gbdh-"
"""El prefijo de la carpeta temporal privada de una base de RecMin (corto: rutas < 260)."""
EXTRACT_FOLDER = "crudo"
"""La carpeta de salida del extractor dentro de la carpeta privada."""

_ROLES = ("collar", "survey", "lithology", "assay_wide", "assay_long", "lithology_catalog",
          "element_catalog")
_EXTRA_SETTINGS = ("decimal", "date_format")
_RECMIN_SETTINGS = ("decimal",)
_ELLIPSOIDAL_ETRS89 = 4937
_PORTS: dict[str, MdbExtractor] = {}
_LOCK = threading.Lock()
_MDB = "mdb"
_DONE = object()


# --- El extractor de bases de Access (puerto) ---------------------------------------------------


def use_mdb_extractor(extractor: MdbExtractor | None) -> MdbExtractor | None:
    """Da a ``io.recmin_mdb@1`` el extractor de bases de Access con que lee (``None``: el de
    ``adapters.registry``) y devuelve el que tenía. Lo usan las pruebas y quien quiera otros
    motores."""
    if extractor is not None and not isinstance(extractor, MdbExtractor):
        raise TypeError(f"el extractor de bases de Access es un interop.ports.MdbExtractor, no "
                        f"{type(extractor).__name__}")
    with _LOCK:
        previous = _PORTS.pop(_MDB, None)
        if extractor is not None:
            _PORTS[_MDB] = extractor
    return previous


def mdb_extractor() -> MdbExtractor:
    """El extractor con que lee ``io.recmin_mdb@1``: el que le dieron con
    :func:`use_mdb_extractor` o, si no, el de ``adapters.registry.mdb_extractor()``."""
    found = _PORTS.get(_MDB)
    if found is not None:
        return found
    from ..adapters import registry  # ARQ-07: solo el registro, y dentro de una función

    return registry.mdb_extractor()


# --- Comunes ------------------------------------------------------------------------------------


def _main(request: ReadRequest) -> Path:
    """El fichero de la fuente; ``ValueError`` si llegan otros papeles."""
    extra = sorted(set(request.files) - {MAIN_ROLE})
    if extra:
        raise ValueError(f"el lector «{request.reader}» lee solo «{MAIN_ROLE}», no {extra}")
    return request.files[MAIN_ROLE]


def _conventions(request: ReadRequest) -> dict[str, Any]:
    found = request.declarations.get("conventions")
    if not isinstance(found, Mapping):
        raise ValueError(f"las declaraciones de «{request.reader}» no tienen sus convenciones "
                         "(«conventions»)")
    return dict(found)


def _check_keys(found: Mapping[str, Any], allowed: Sequence[str], what: str,
                reader_id: str) -> None:
    unknown = sorted(str(key) for key in found if key not in allowed)
    if unknown:
        raise ValueError(f"{what} desconocidas para «{reader_id}»: {unknown} (son "
                         f"{list(allowed)})")


def _settings(request: ReadRequest, reading: Sequence[str], required: Sequence[str],
              conventions: Mapping[str, Any]) -> Mapping[str, Any]:
    """Los ajustes de lectura: los de ``reading`` (los de ``required``, obligatorios) y, si
    vienen, las convenciones, que tienen que ser las de las declaraciones."""
    settings = request.settings
    _check_keys(settings, (*reading, *conventions), "ajustes de lectura", request.reader)
    missing = [key for key in required if key not in settings]
    if missing:
        raise ValueError(f"faltan ajustes de lectura de «{request.reader}»: {missing}")
    for key in conventions:
        if key in settings and canonical_json(settings[key]) != canonical_json(conventions[key]):
            raise ValueError(f"el ajuste «{key}» de «{request.reader}» no es el de sus "
                             "declaraciones: lo que se lee es lo que se hashea")
    return settings


def _horizontal(crs: object) -> CrsRef | None:
    """El CRS horizontal declarado (``{"epsg": n}``) del catálogo; ``None`` sin declarar o si
    no aplica."""
    if crs is None or (isinstance(crs, Mapping) and crs.get("not_applicable") is True):
        return None
    if isinstance(crs, Mapping) and set(crs) == {"epsg"}:
        from ..core.georef import load_catalog

        return load_catalog().horizontal(crs["epsg"])
    raise ValueError(f"el CRS horizontal declarado de unos sondeos es {{\"epsg\": n}}, no {crs!r}")


def _vertical(crs: object) -> VerticalRef | None:
    """El datum vertical declarado (``{"epsg": n}``, ``{"local": nota}`` o
    ``{"ellipsoidal": …}``); ``None`` sin declarar o si no aplica."""
    if crs is None or (isinstance(crs, Mapping) and crs.get("not_applicable") is True):
        return None
    if isinstance(crs, Mapping) and len(crs) == 1:
        from ..core.georef import VerticalRef, load_catalog

        ((form, value),) = crs.items()
        if form == "epsg":
            return load_catalog().vertical(value)
        if form == "local":
            return load_catalog().local_vertical(value)
        if form == "ellipsoidal" and value == _ELLIPSOIDAL_ETRS89:
            from ..gis.crs import ELLIPSOIDAL_ETRS89  # carga gis: solo con una cota elipsoidal

            return ELLIPSOIDAL_ETRS89
        if form == "ellipsoidal" and isinstance(value, str) and value.strip():
            return VerticalRef(kind="ellipsoidal", epsg=None, name=value, wkt2=None, note=None)
    raise ValueError(f"el datum vertical declarado de unos sondeos no se reconoce: {crs!r}")


def _declaration(declarations: Mapping[str, Any], conventions: Mapping[str, Any],
                 decimal: str, date_format: str | None,
                 inclination: str | None = None) -> SourceDeclaration:
    """La declaración con que se interpreta la fuente: la de las declaraciones (``DECL``) y los
    ajustes de lectura (decimal y formato de fecha)."""
    from ..drillholes.model import SourceDeclaration, ValueRules

    values: dict[str, Any] = dict(
        crs=_horizontal(declarations.get("crs_h")),
        vertical=_vertical(declarations.get("crs_v")),
        azimuth_ref=conventions.get("azimuth_ref"),
        declination_deg=conventions.get("declination_deg"),
        inclination_convention=conventions.get("inclination_convention", inclination),
        units=conventions.get("units") or {},
        value_rules=ValueRules(
            decimal_mark=decimal,
            sentinels=frozenset(conventions.get("sentinels") or ()),
            negative_is_below_dl=conventions.get("negative_is_below_dl", False),
        ),
        all_vertical=conventions.get("all_vertical", False),
        date_format=date_format,
    )
    if "density_kind" in conventions:
        values["density_kind"] = conventions["density_kind"]
    return SourceDeclaration(**values)


def _scaled(steps: Iterator[float], start: float, end: float) -> Generator[float, None, Any]:
    """Los pasos de ``steps`` (de 0 a 1) llevados a ``[start, end]``; devuelve su valor.
    Cerrarlo a medias cierra ``steps`` (lo que abrió se cierra)."""
    try:
        while True:
            try:
                fraction = next(steps)
            except StopIteration as stop:
                return stop.value
            yield start + (end - start) * fraction
    finally:
        close = getattr(steps, "close", None)
        if close is not None:
            close()


def _hash_rows(feed: RowEncoder, rows: Sequence[Sequence[object]], step: int, start: float,
               end: float) -> Generator[float, None, str]:
    """Añade ``rows`` a ``feed`` por lotes de ``step`` y cierra su hash por pasos, con el
    avance de ``start`` a ``end``; devuelve el hash de datos."""
    total = len(rows)
    middle = start + (end - start) * ROWS_SHARE
    for first in range(0, total, step):
        feed.update(rows[first:first + step])
        if first + step < total:
            yield start + (middle - start) * (first + step) / total
    return (yield from _scaled(feed.finish_steps(max(step, FINISH_STEP)), middle, end))


def _per_second(speed: int, overhead: float = 0.0) -> Callable[[int], float]:
    """La estimación de un lector que tarda ``overhead`` más ``speed`` bytes por segundo."""

    def estimate(size: int) -> float:
        return overhead + size / speed

    return estimate


# --- io.dh_csv@1 e io.dh_xlsx@1 -----------------------------------------------------------------


def _tabular(request: ReadRequest) -> tuple[str, Mapping[str, str], Mapping[str, Any],
                                             SourceDeclaration]:
    """El papel, la correspondencia, los ajustes de lectura y la declaración de una tabla,
    comprobados."""
    from ..drillholes import provenance

    conventions = _conventions(request)
    role = conventions.get("role")
    if role not in _ROLES:
        raise ValueError(f"el papel («role») de una tabla de «{request.reader}» es uno de "
                         f"{list(_ROLES)}, no {role!r}")
    expected = provenance.input_kind(request.reader, role)
    if request.kind != expected:
        raise ValueError(f"una tabla de «{role}» es una entrada «{expected}», no "
                         f"«{request.kind}»")
    _check_keys(conventions, ("role", "mapping", *provenance.ROLE_CONVENTIONS[role]),
                "convenciones", request.reader)
    mapping = conventions.get("mapping")
    if (not isinstance(mapping, Mapping) or not mapping
            or not all(isinstance(k, str) and isinstance(v, str) for k, v in mapping.items())):
        raise ValueError(f"la correspondencia de columnas («mapping») de una tabla de "
                         f"«{request.reader}» es {{campo: columna}}, no {mapping!r}")
    reading = provenance.READING_SETTINGS[request.reader]
    settings = _settings(request, (*reading, *_EXTRA_SETTINGS), (*reading, "decimal"),
                         conventions)
    decl = _declaration(request.declarations, conventions, settings["decimal"],
                        settings.get("date_format"))
    return role, mapping, settings, decl


def _floats(values: np.ndarray) -> list[float | None]:
    return [None if number != number else number for number in values.tolist()]


def _codes(values: np.ndarray, members: Sequence[Any]) -> list[str | None]:
    return [None if code < 0 else str(members[code]) for code in values.tolist()]


def _records(role: str, rows: RoleRows) -> list[tuple[object, ...]]:
    """Las filas interpretadas de una tabla de ``role``, en las columnas de :data:`COLUMNS`
    (``raw`` nulo)."""
    from ..drillholes.model import AssayColumns, CollarColumns

    if role == "collar":
        c = rows.collars
        stations = rows.surveys
        orientation = dict(zip(rows.lines["surveys"].tolist(),
                               zip(_floats(stations.azimuth), _floats(stations.inclination),
                                   strict=True), strict=True))
        oriented = [orientation.get(line, (None, None))
                    for line in rows.lines["collars"].tolist()]
        columns: list[list[object]] = [
            c.name.tolist(), _floats(c.x), _floats(c.y), _floats(c.z), _floats(c.depth),
            [pair[0] for pair in oriented], [pair[1] for pair in oriented],
            _codes(c.hole_type, CollarColumns.code_values("hole_type")),
            c.planned.tolist(), c.grade_control.tolist(), c.category.tolist(),
            c.priority.tolist(), c.sector.tolist(), c.group.tolist(), c.campaign.tolist(),
            c.start_date.tolist(), c.end_date.tolist(), c.survey_method.tolist(),
            c.external_id.tolist(), c.comments.tolist(),
        ]
    elif role == "survey":
        s = rows.surveys
        columns = [s.hole_name.tolist(), _floats(s.depth), _floats(s.azimuth),
                   _floats(s.inclination), s.method.tolist(), s.external_id.tolist()]
    elif role == "lithology":
        li = rows.lithology
        columns = [li.hole_name.tolist(), _floats(li.from_m), _floats(li.to_m),
                   li.code.tolist(), li.description.tolist(), li.logged_by.tolist(),
                   li.external_id.tolist()]
    elif role in ("assay_wide", "assay_long"):
        a = rows.assays
        columns = [a.hole_name.tolist(), _floats(a.from_m), _floats(a.to_m),
                   a.element.tolist(), _floats(a.value), a.unit.tolist(),
                   _codes(a.detection_flag, AssayColumns.code_values("detection_flag")),
                   a.sample_id.tolist(), a.lab.tolist(), a.method.tolist(), a.batch.tolist(),
                   a.external_id.tolist()]
    elif role == "lithology_catalog":
        codes = rows.catalogs.lithology
        columns = [[e.code for e in codes], [e.description for e in codes],
                   [e.color for e in codes], [e.pattern for e in codes],
                   [e.density for e in codes], [e.sort_order for e in codes],
                   [e.external_id for e in codes]]
    else:
        elements = rows.catalogs.elements
        columns = [[e.code for e in elements], [e.name for e in elements],
                   [e.unit for e in elements], [e.decimals for e in elements],
                   [e.detection_limit for e in elements], [e.sort_order for e in elements],
                   [e.external_id for e in elements]]
    count = len(columns[0])
    return list(zip(*columns, [None] * count, strict=True))


def _rejected(table: Table, rows: RoleRows, width: int) -> list[tuple[object, ...]]:
    """Una fila por fila de la fuente con algún rechazo: sus campos tal como están (``raw``)."""
    lines = sorted({rejection.row for rejection in rows.rejected})
    if not lines:
        return []
    index = {line: position for position, line in enumerate(table.lines)}
    empty = (None,) * (width - 1)
    return [(*empty, canonical_json([str(f) for f in table.rows[index[line]]]).decode("utf-8"))
            for line in lines]


def _read_table_steps(request: ReadRequest, load: Callable[[Mapping[str, Any]], Table]
                      ) -> Iterator[float]:
    """Lo común de ``io.dh_csv@1`` e ``io.dh_xlsx@1``: comprueba la petición, lee la tabla con
    ``load(ajustes)`` y la interpreta con su papel, y hashea sus filas."""
    from .drillholes_tabular import read_role

    role, mapping, settings, decl = _tabular(request)
    table = load(settings)
    yield READ_SHARE
    rows = read_role(role, table, mapping, decl)
    columns = COLUMNS[_COLUMNS_OF_ROLE[role]]
    found = _records(role, rows) + _rejected(table, rows, len(columns))
    yield INTERPRET_SHARE
    feed = request.hasher.begin_rows(columns, False)
    step = max(1, request.chunk_bytes // ROW_BYTES)
    yield from _hash_rows(feed, found, step, INTERPRET_SHARE, 1.0)
    yield 1.0


def read_dh_csv(request: ReadRequest) -> Iterator[float]:
    """El generador de ``io.dh_csv@1``: la tabla con ``interop.csv_tables.read_table`` (da su
    avance tras leerla y tras interpretarla) y sus filas por lotes de unos ``chunk_bytes``."""
    from .csv_tables import read_table

    path = _main(request)

    def load(settings: Mapping[str, Any]) -> Table:
        return read_table(path, encoding=settings["encoding"], separator=settings["separator"],
                          header_row=settings["header_row"])

    return _read_table_steps(request, load)


def read_dh_xlsx(request: ReadRequest) -> Iterator[float]:
    """El generador de ``io.dh_xlsx@1``: la hoja ``sheet`` con ``interop.xlsx_tables.
    read_sheet`` (sus números y fechas con el decimal y el formato de fecha de la lectura) y
    sus filas por lotes."""
    from .xlsx_tables import read_sheet

    path = _main(request)

    def load(settings: Mapping[str, Any]) -> Table:
        return read_sheet(path, settings["sheet"], header_row=settings["header_row"],
                          decimal_mark=settings["decimal"],
                          date_format=settings.get("date_format"))

    return _read_table_steps(request, load)


# --- io.recmin_mdb@1 ----------------------------------------------------------------------------


def _copy_steps(source: Path, target: Path, chunk_bytes: int) -> Iterator[float]:
    """Copia ``source`` en ``target`` por trozos, con el avance tras cada uno."""
    with open(source, "rb") as reader, open(target, "xb") as writer:
        total = os.fstat(reader.fileno()).st_size
        done = 0
        while chunk := reader.read(chunk_bytes):
            writer.write(chunk)
            done += len(chunk)
            yield done / total if total else 1.0


def _extract_steps(extractor: MdbExtractor, copy: Path,
                   out_dir: Path) -> Generator[float, None, list[RawTable]]:
    """Extrae la copia en un hilo con ``extractor`` y da su avance (de 0 a 1) cada
    :data:`POLL_S` como mucho; cerrar el generador a medias le pide cancelar y espera a que
    pare (≤ 2 s). Devuelve sus tablas; lo que lanza el extractor sale de aquí."""
    events: queue.SimpleQueue[object] = queue.SimpleQueue()
    stop = threading.Event()
    outcome: dict[str, Any] = {}

    def work() -> None:
        try:
            outcome["tables"] = extractor.extract(copy, out_dir, lambda f, _m: events.put(f),
                                                  stop.is_set)
        except BaseException as exc:  # noqa: BLE001 - sale en el generador
            outcome["error"] = exc
        finally:
            events.put(_DONE)

    thread = threading.Thread(target=work, name="geoblender-dh-mdb", daemon=True)
    thread.start()
    done = 0.0
    try:
        while True:
            try:
                event = events.get(timeout=POLL_S)
            except queue.Empty:
                yield done
                continue
            if event is _DONE:
                break
            if isinstance(event, float | int) and not isinstance(event, bool):
                number = float(event)
                if math.isfinite(number):
                    done = max(done, min(1.0, number))
            yield done
    finally:
        stop.set()  # a medias, el extractor cancela; si acabó, no hace nada
        thread.join(CANCEL_WAIT_S)
    if "error" in outcome:
        raise outcome["error"]
    return list(outcome["tables"])


def _cell_values(column: Sequence[object], kind: str, single: bool) -> Sequence[object]:
    """Los valores de una columna cruda con el tipo de su campo (:data:`DBTYPE_FIELDS`): los
    Single, por su decimal más corto; los enteros y los sí/no, tal cual (el codificador los
    comprueba: un 1,5 en un entero no se lee); los textos, con las fechas en ISO y los
    decimales exactos por su texto."""
    if kind == _FLOAT:
        missing = [value is None for value in column]
        numbers = np.array([math.nan if value is None else float(value)  # type: ignore[arg-type]
                            for value in column], dtype=np.float64)
        if single:
            from ..drillholes.values import from_single_column

            numbers = from_single_column(numbers)
        return [None if absent else number
                for absent, number in zip(missing, numbers.tolist(), strict=True)]
    if kind in (_INT, _BOOL):
        return column
    found: list[object] = []
    for value in column:
        if value is None or isinstance(value, str):
            found.append(value)
        elif isinstance(value, dt.date):  # también una fecha y hora
            found.append(value.isoformat())
        elif isinstance(value, bytes | bytearray | memoryview):
            found.append(None)  # las binarias no llegan
        else:
            found.append(str(value))  # un decimal exacto, o el texto de un tipo raro
    return found


def _raw_rows(table: RawTable) -> tuple[list[tuple[str, str]], list[tuple[object, ...]]]:
    """Las columnas (por nombre, sin mayúsculas) y las filas de una tabla cruda con el tipo de
    cada una."""
    order = sorted(range(len(table.columns)), key=lambda i: table.columns[i].name.casefold())
    columns: list[tuple[str, str]] = []
    values: list[Sequence[object]] = []
    for position in order:
        column = table.columns[position]
        kind = DBTYPE_FIELDS.get(column.type, _TEXT)
        columns.append((column.name, kind))
        values.append(_cell_values([row[position] for row in table.rows], kind,
                                   column.type == DBTYPE_R4))
    return columns, list(zip(*values, strict=True)) if values else []


def read_recmin_mdb(request: ReadRequest) -> Iterator[float]:
    """El generador de ``io.recmin_mdb@1``: copia la base a una carpeta temporal privada, la
    extrae (con el avance del extractor) y hashea una parte por tabla que lee el importador;
    la carpeta privada se borra al acabar, al fallar y al cancelar."""
    from ..drillholes import provenance
    from .base import require_declarations
    from .recmin.drillholes import INCLINATION_CONVENTION, needs
    from .recmin.schema import SOURCE_LABEL, index_tables, layout, require_collars

    path = _main(request)
    if request.kind != "drillholes":
        raise ValueError(f"una base de RecMin es una entrada «drillholes», no «{request.kind}»")
    conventions = _conventions(request)
    _check_keys(conventions, provenance.RECMIN_CONVENTIONS, "convenciones", request.reader)
    settings = _settings(request, _RECMIN_SETTINGS, (), conventions)
    decl = _declaration(request.declarations, conventions, settings.get("decimal", "."), None,
                        str(INCLINATION_CONVENTION))
    extractor = mdb_extractor()
    with tempfile.TemporaryDirectory(prefix=PRIVATE_PREFIX,
                                     ignore_cleanup_errors=True) as private:
        folder = Path(private)
        copy = folder / path.name
        yield from _scaled(_copy_steps(path, copy, request.chunk_bytes), 0.0, COPY_SHARE)
        tables = yield from _scaled(_extract_steps(extractor, copy, folder / EXTRACT_FOLDER),
                                    COPY_SHARE, EXTRACT_SHARE)
    indexed = index_tables(tables)
    found = layout({table.name: [c.name for c in table.columns] for table in tables})
    require_collars(found)
    require_declarations(decl, needs(indexed), obj=SOURCE_LABEL)
    total = sum(len(indexed[name.casefold()].rows) for name in found.names) or 1
    step = max(1, request.chunk_bytes // ROW_BYTES)
    parts: dict[str, tuple[str, str]] = {}
    done = 0
    for name in found.names:
        table = indexed[name.casefold()]
        columns, rows = _raw_rows(table)
        start = EXTRACT_SHARE + (1.0 - EXTRACT_SHARE) * done / total
        done += len(rows)
        end = EXTRACT_SHARE + (1.0 - EXTRACT_SHARE) * done / total
        feed = RowEncoder(columns, False)
        parts[table.name] = ("table", (yield from _hash_rows(feed, rows, step, start, end)))
    request.hasher.composite(parts)
    yield 1.0


# --- Los lectores -------------------------------------------------------------------------------

DH_CSV = ContentReader(
    "io.dh_csv", 1, ("drillholes", "table"), False, False, _per_second(CSV_BYTES_PER_S),
    read_dh_csv,
)
"""Una tabla de sondeos de un papel en un CSV."""
DH_XLSX = ContentReader(
    "io.dh_xlsx", 1, ("drillholes", "table"), False, False, _per_second(XLSX_BYTES_PER_S),
    read_dh_xlsx,
)
"""Una tabla de sondeos de un papel en una hoja de un libro XLSX."""
RECMIN_MDB = ContentReader(
    "io.recmin_mdb", 1, ("drillholes",), True, False,
    _per_second(MDB_BYTES_PER_S, MDB_OVERHEAD_S), read_recmin_mdb,
)
"""Una base de sondeos de RecMin (MDB o ACCDB), sobre una copia."""
CONTENT_READERS: tuple[ContentReader, ...] = (DH_CSV, DH_XLSX, RECMIN_MDB)
"""Los lectores de los sondeos, para registrarlos desde ``bl/`` y en el trabajo de hash."""
