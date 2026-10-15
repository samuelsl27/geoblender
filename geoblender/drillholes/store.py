# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo importado y la base de los sondeos en el proyecto, sobre la 008 (spec 005, T38;
RF-005-01, RF-005-04, RF-005-11, RF-005-12, RF-005-22; RF-008-07, RF-008-17 a RF-008-19,
RF-008-52 a RF-008-54; plan 005 §5.6.1 y §5.6.5, D17).

Los sondeos se guardan en dos niveles (plan §5.6.1) y siempre con la API de procedencia de la
008, nunca escribiendo en las tablas ``gb_*``:

- **Lo importado** (:class:`SourceWriter`): una orden de importación con uno o varios ficheros
  (D-15: una entrada por fichero, por hoja de un XLSX; la base de RecMin, una) son varias
  operaciones de importación (``dh.import_tabular`` o ``dh.import_recmin``, cada una con su
  ``OperationHandle``) que se confirman **en la misma transacción** (RF-005-04). Antes de
  escribir nada, cada entrada se clasifica (:meth:`SourceWriter.add`, ``classify_import``,
  RF-008-54): la misma entrada con los mismos ajustes se **reutiliza** (su importación queda
  «cancelada» con el aviso y no se escribe nada de ella); los mismos datos con otros ajustes
  (otra referencia del azimut, otra declinación…) son una **sustitución**, que necesita la
  entrada a la que sustituye y el motivo (RF-008-11; si no, ``core.input_substitution_required``
  sin escribir nada); si no, una entrada **nueva**. Después, :meth:`SourceWriter.steps`, por
  pasos y en una transacción de ``Project.write_transaction`` sostenida entre ellos: por cada
  entrada, la sustituida marcada (``supersede``), la entrada registrada (``register_input``, con
  su hash de contenido, sus CRS declarados y la huella de cada fichero), una tabla de atributos
  ``dh_src_<rol>_<nombre>_<entrada8>`` por papel con sus filas (las de :func:`source_tables`: lo
  leído, ya interpretado, en el CRS, el datum y los convenios declarados, sin transformar, con
  el sondeo por su nombre), su informe en ``dh_import_log`` (RF-005-12, :class:`LogLine`) y
  ``OperationHandle.complete`` con las ``DatasetSpec`` de ``drillholes.provenance`` (lo
  importado, inmutable con su entrada: escribir en su tabla desde otra conexión aborta con el
  nombre de la entrada, RF-008-52) y el hash de cada tabla que dio el trabajo
  (``schema.table_digest``; sin él, lo calcula el registro). Confirmada, el original de cada
  fichero se guarda desde la copia verificada del trabajo (:meth:`SourceWriter.originals`,
  ``store_originals_steps``, RF-008-53), nunca desde la fuente.
- **La base y lo calculado** (:class:`BaseWriter`): ``dh.build_base`` escribe las once tablas
  de la base (las de ``build_base.BaseTables.rows``), ``dh.validate`` ``dh_validation_issue`` y
  ``dh.desurvey`` ``dh_trace``, cada una **reescrita** (borrada y creada de nuevo: sus ``fid``
  empiezan en 1, y el mismo contenido da las mismas filas y el mismo hash, RF-008-26) por pasos
  en una transacción, con su ``DatasetSpec`` y, en ``dh_collar``, el detalle de los sondeos
  cuya huella de la desviación cambió (``build_base.changed_holes``, RF-005-22).

**Pasos** (plan §5.6.5 y §5.6.7): cada paso dura como mucho ``budget_s`` (:data:`STEP_BUDGET_S`)
más una sentencia de :data:`~drillholes.schema.INSERT_ROWS` filas; tras cada uno, el avance
(0–1). ``cancelled()`` se consulta entre pasos: si pide parar, ``JobCancelled``. Un fallo o una
cancelación antes del ``COMMIT`` deshacen la transacción (ni tablas, ni filas, ni entradas, ni
datos nuevos) y dejan cada operación «fallida» o «cancelada» con su motivo; el proyecto sigue
en escritura (RF-005-04, RF-008-19). Cerrar los pasos sin terminarlos (al desregistrar) deshace
la transacción y no escribe nada más: la operación sigue «en curso» y quedará «interrumpida» al
abrir el proyecto (como las incorporaciones de ``bl/ops/gis.py``).

**Lectura**: :func:`read_steps` lee la base por pasos a un ``DrillholeSet`` en el CRS y el
datum del proyecto (el de ``dh.validate``, ``dh.desurvey`` y la vista); :func:`existing_holes`,
los sondeos de la base (los que una importación pregunta si sustituir, RF-005-11), y
:func:`read_catalogs`, sus catálogos (con los que una importación compara sus códigos,
RF-005-10); :func:`stale_holes`, los de trazas obsoletas: su huella de la desviación
(``survey_sha256``) en ``dh_collar`` no es la que usó su traza en ``dh_trace`` (RF-005-22).
:func:`source_entry` es lo contrario de :func:`source_tables`: las filas de lo importado de una
entrada como el ``SourceEntry`` de ``dh.build_base``; (T25) :func:`live_sources` da lo importado
vigente, entrada a entrada en el orden en que se registraron, y :func:`source_entry_steps` lee
el de una, por pasos, como su ``SourceEntry``; (T27) :func:`stored_validation`, el informe de
la última validación (``dh_validation_issue`` y lo que su operación dice que no se evaluó), el
que enseña la lista de la pestaña «Sondeos» y se exporta; (T28) :func:`survey_hashes`, la
huella de la desviación de cada boca, :func:`kept_traces`, las trazas que conserva un cálculo
de «solo las obsoletas», y :func:`source_holes`, los sondeos de lo importado de una entrada (los
que su reimportación sustituye sin preguntar).

**Valores** (plan §5.2.2): los números, en float64 tal como llegan (NaN = ``NULL``; −0 = 0);
sí/no, 0 o 1; las enumeraciones, su texto; las fechas, «AAAA-MM-DD»; ``extra``, su JSON
canónico. Lo importado guarda las estaciones medidas y las de la orientación en boca; las
verticales declaradas las crea ``dh.build_base`` con «todos verticales» de su entrada. Ninguna
ruta absoluta llega a ``gb_*``: las entradas guardan su ancla (``core.inputs.locate_source``).
Python puro, numpy y ``sqlite3`` (ADR-0004).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import time
from collections.abc import Callable, Generator, Iterator, Mapping, Sequence
from dataclasses import dataclass, fields
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

import numpy as np

from ..core.content.builtin import DOCUMENT
from ..core.content.encoder import ContentDigest
from ..core.content.readers import MAIN_ROLE, ReadCancelled, read_content
from ..core.datasets.model import DATASET_DECLARATIONS, LIVE_STATUSES, DatasetRecord, DatasetSpec
from ..core.datasets.registry import get as get_dataset
from ..core.errors import GeoblenderError, ValidationError
from ..core.georef import CrsRef, VerticalRef, load_catalog
from ..core.hashing import HashCancelled, canonical_json
from ..core.inputs.model import InputRecord, InputSpec, InputStatus
from ..core.inputs.originals import store_originals_steps
from ..core.inputs.registry import (
    Classification,
    Reuse,
    Substitute,
    classify_import,
    register_input,
    reuse_input,
    supersede,
)
from ..core.inputs.registry import get as get_input
from ..core.project.model import Progress as ProjectProgress
from ..core.provenance.messages import ProvenanceError
from ..core.provenance.operations import (
    OperationHandle,
    OperationProject,
    OperationStatus,
    cancel_reason,
    failure_reason,
)
from ..jobs.worker_api import JobCancelled
from .build_base import BaseTables, SourceEntry, changed_holes
from .model import (
    AssayColumns,
    Catalogs,
    CatalogEntry,
    CollarColumns,
    DrillholeSet,
    Element,
    IntervalColumns,
    LithologyCode,
    Rejection,
    SourceDeclaration,
    StationSource,
    StructureColumns,
    SurveyColumns,
    ZoneColumns,
    name_key,
)
from . import report
from .provenance import (
    BUILD_BASE,
    DESURVEY,
    EXPORT_KIND,
    EXPORT_VALIDATION,
    IMPORTS,
    MODULE,
    OPERATION_TYPES_BY_NAME,
    VALIDATE,
    dataset_spec,
    export_spec,
    input_declaration,
    source_spec,
)
from .schema import (
    BASE_TABLES,
    INSERT_ROWS,
    LAYOUTS,
    SOURCE_PREFIX,
    SOURCE_ROLES,
    TableLayout,
    create_table,
    insert_rows,
    layout_of,
    source_layout,
    source_name,
    source_table,
)
from .validate import Note, no_dem_note

__all__ = [
    "IMPORT_LOG",
    "LOG_KINDS",
    "STEP_BUDGET_S",
    "VALIDATION_TABLE",
    "BaseWriter",
    "LiveSource",
    "LogLine",
    "SourceInput",
    "SourceWriter",
    "StoreProject",
    "StoredValidation",
    "existing_holes",
    "export_report",
    "kept_traces",
    "live_sources",
    "read_catalogs",
    "read_steps",
    "source_entry",
    "source_entry_steps",
    "source_holes",
    "source_tables",
    "stale_holes",
    "stored_validation",
    "survey_hashes",
]

STEP_BUDGET_S = 0.05
"""Lo que se planea que dure un paso (s): con la última sentencia, menos de 0,15 s (plan
§5.6.5; RNF-005-06)."""
IMPORT_LOG = "dh_import_log"
"""La tabla del informe de las importaciones (RF-005-12): cada importación añade sus líneas."""
LOG_KINDS: tuple[str, ...] = ("summary", "rejected", "warning")
"""Las clases de línea del informe: el resumen de una tabla, un registro rechazado (con su
motivo) y un aviso."""
READ_ROWS = 5_000
"""Las filas de cada lectura de :func:`read_steps` (entre dos, se mira el presupuesto)."""
CANCELLATIONS: tuple[type[BaseException], ...] = (JobCancelled, ReadCancelled, HashCancelled)
"""Los errores con que se para a petición de la persona: la operación queda «cancelada»."""

_OBJ = "Sondeos del proyecto"
_DATES = frozenset({"start_date", "end_date"})
_EMPTY_EXTRA = "{}"
_NO_EXTRA: Mapping[str, Any] = MappingProxyType({})
_SOURCE_PARTS: Mapping[str, tuple[str, type]] = MappingProxyType({
    "collar": ("collars", CollarColumns),
    "survey": ("surveys", SurveyColumns),
    "lithology": ("lithology", IntervalColumns),
    "assay": ("assays", AssayColumns),
    "zone_interval": ("zones", ZoneColumns),
    "structure": ("structures", StructureColumns),
})
"""El papel de lo importado de cada tabla de un ``SourceEntry`` (salvo los catálogos)."""
_SOURCE_COLUMNS: Mapping[tuple[str, str], str] = MappingProxyType({
    ("collar", "sector"): "sector_code",
    ("collar", "group"): "group_code",
})
"""Los campos del modelo que en lo importado tienen otro nombre de columna (``group`` es una
palabra de SQL)."""
_SOURCE_FIELDS: Mapping[tuple[str, str], str] = MappingProxyType(
    {(role, column): name for (role, name), column in _SOURCE_COLUMNS.items()})
"""Lo contrario: el campo del modelo de cada una de esas columnas."""
_CATALOG_PARTS: tuple[tuple[str, str, type], ...] = (
    ("lithology", "lithology", LithologyCode),
    ("elements", "element", Element),
    ("sectors", "sector", CatalogEntry),
    ("groups", "group", CatalogEntry),
    ("zones", "zone", CatalogEntry),
)
"""(atributo de ``Catalogs``, valor de la columna ``catalog``, registro) de cada catálogo."""
_BASE_CATALOGS: Mapping[str, tuple[str, type]] = MappingProxyType({
    "dh_lithology_code": ("lithology", LithologyCode),
    "dh_element": ("elements", Element),
    "dh_sector": ("sectors", CatalogEntry),
    "dh_group": ("groups", CatalogEntry),
    "dh_zone": ("zones", CatalogEntry),
})
_BASE_PARTS: tuple[tuple[str, str, type], ...] = (
    ("dh_survey", "surveys", SurveyColumns),
    ("dh_lithology", "lithology", IntervalColumns),
    ("dh_assay", "assays", AssayColumns),
    ("dh_zone_interval", "zones", ZoneColumns),
    ("dh_structure", "structures", StructureColumns),
)
_CATALOG_ID: Mapping[str, tuple[str, str, str]] = MappingProxyType({
    "dh_lithology": ("lithology_id", "code", "dh_lithology_code"),
    "dh_assay": ("element_id", "element", "dh_element"),
    "dh_zone_interval": ("zone_id", "zone", "dh_zone"),
    "dh_structure": ("zone_id", "zone", "dh_zone"),
})
"""En la base, el id del catálogo de cada tabla hija, el campo del modelo que da y su
catálogo."""
_STATIONS = SurveyColumns.code_values("source")
_DECLARED_VERTICAL = _STATIONS.index(StationSource.DECLARED_VERTICAL)
_BASE_TYPES: tuple[str, ...] = (BUILD_BASE, VALIDATE, DESURVEY)
_BOOL_FIELDS = frozenset({"show_in_legend", "show_in_tables", "use_in_calc"})


class StoreProject(OperationProject, Protocol):
    """Lo que usa del proyecto (``core.project.Project``): lo de las operaciones y las entradas
    de la 008."""


# --- Valores ---------------------------------------------------------------------------------


def _floats_sql(values: np.ndarray) -> list[Any]:
    """Unos números como se guardan: float64 sin −0,0 y ``None`` por NaN."""
    found = np.asarray(values, dtype=np.float64) + 0.0
    shown = found.astype(object)
    shown[np.isnan(found)] = None
    return shown.tolist()


def _extra_sql(values: Sequence[Any]) -> list[str]:
    """El JSON canónico de cada ``extra`` («{}» los vacíos)."""
    return [canonical_json(value).decode("utf-8") if value else _EMPTY_EXTRA
            for value in values]


def _column_sql(columns: type, name: str, values: np.ndarray) -> list[Any]:
    """Los valores que se guardan de la columna ``name`` de una clase de columnas del
    modelo."""
    dtype = values.dtype
    if dtype == np.float64:
        return _floats_sql(values)
    if dtype == np.bool_:
        return values.astype(np.int64).tolist()
    if dtype == np.int8:
        texts = np.array([*(str(member) for member in columns.code_values(name)), None],
                         dtype=object)
        return texts[values].tolist()
    if dtype.kind in "iu":
        return values.astype(np.int64).tolist()
    if name == "extra":
        return _extra_sql(values.tolist())
    if name in _DATES:
        return [None if day is None else day.isoformat() for day in values.tolist()]
    return values.tolist()


def _value_sql(value: Any) -> Any:
    """Un valor de un registro de catálogo como se guarda."""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, str):
        return str(value)  # también una enumeración (StrEnum): su texto
    if isinstance(value, float):
        return value + 0.0
    if isinstance(value, Mapping):
        return _extra_sql([value])[0]
    return value


def _objects(values: Sequence[Any]) -> np.ndarray:
    found = np.empty(len(values), dtype=object)
    found[:] = list(values)
    return found


def _extra_of(text: Any) -> Mapping[str, Any]:
    if text is None or text == _EMPTY_EXTRA:
        return _NO_EXTRA
    return MappingProxyType(json.loads(text))


def _column_values(columns: type, name: str, values: Sequence[Any],
                   dtype: np.dtype) -> np.ndarray:
    """La columna ``name`` (del ``dtype`` de su clase de columnas) desde lo guardado: lo
    contrario de :func:`_column_sql`."""
    if dtype == np.float64:
        return np.fromiter((np.nan if value is None else value for value in values),
                           dtype=np.float64, count=len(values))
    if dtype == np.bool_:
        return np.array([bool(value) for value in values], dtype=np.bool_)
    if dtype == np.int8:
        index = {str(member): code for code, member in enumerate(columns.code_values(name))}
        return np.array([-1 if value is None else index[value] for value in values],
                        dtype=np.int8)
    if dtype.kind in "iu":
        return np.array(values, dtype=np.int64)
    if name == "extra":
        return _objects([_extra_of(value) for value in values])
    if name in _DATES:
        return _objects([None if value is None else dt.date.fromisoformat(value)
                         for value in values])
    return _objects(values)


def _absent(dtype: np.dtype, count: int) -> np.ndarray:
    """Una columna sin valores: NaN, −1 (sin código) o ``None``."""
    if dtype == np.float64:
        return np.full(count, np.nan)
    if dtype == np.int8:
        return np.full(count, -1, dtype=np.int8)
    return np.full(count, None, dtype=object)


def _transpose(rows: Sequence[Sequence[Any]], width: int) -> list[list[Any]]:
    """Las columnas de unas filas de ``width`` valores."""
    if not rows:
        return [[] for _ in range(width)]
    return [list(column) for column in zip(*rows, strict=True)]


# --- Lo importado: filas ↔ columnas -------------------------------------------------------------


def _source_rows(role: str, part: Any) -> list[tuple[Any, ...]]:
    """Las filas de ``dh_src_<role>`` de las columnas ``part`` del modelo."""
    layout = source_layout(role)
    columns = type(part)
    values = []
    for column in layout.column_names:
        name = _SOURCE_FIELDS.get((role, column), column)
        values.append(_column_sql(columns, name, getattr(part, name)))
    return list(zip(*values, strict=True))


def _catalog_rows(catalogs: Catalogs) -> list[tuple[Any, ...]]:
    """Las filas de ``dh_src_catalog``: cada código con su catálogo (``catalog``)."""
    names = source_layout("catalog").column_names
    rows: list[tuple[Any, ...]] = []
    for attribute, kind, _ in _CATALOG_PARTS:
        for record in getattr(catalogs, attribute):
            values = {"catalog": kind, **{item.name: getattr(record, item.name)
                                          for item in fields(record)}}
            rows.append(tuple(_value_sql(values.get(name)) for name in names))
    return rows


def _check_source_surveys(surveys: SurveyColumns) -> SurveyColumns:
    """Las estaciones de lo importado: en lo declarado (sin convertir); las verticales
    declaradas no se guardan (las crea ``dh.build_base``)."""
    converted = ((surveys.azimuth_ref >= 0) | np.isfinite(surveys.azimuth_measured)
                 | np.isfinite(surveys.declination_deg) | np.isfinite(surveys.convergence_deg))
    if converted.any():
        raise ValueError("lo importado guarda las estaciones en lo declarado, sin convertir: "
                         "sin azimut medido, referencia, declinación ni convergencia (los "
                         "pone dh.build_base con la declaración de su entrada)")
    return surveys.take(np.flatnonzero(surveys.source != _DECLARED_VERTICAL))


def source_tables(
    *,
    collars: CollarColumns | None = None,
    surveys: SurveyColumns | None = None,
    lithology: IntervalColumns | None = None,
    assays: AssayColumns | None = None,
    zones: ZoneColumns | None = None,
    structures: StructureColumns | None = None,
    catalogs: Catalogs | None = None,
) -> dict[str, list[tuple[Any, ...]]]:
    """Las filas de lo importado de una entrada (plan §5.6.1) por papel
    (``drillholes.schema.SOURCE_ROLES``), solo los papeles con filas, en el orden de
    ``TableLayout.insert_columns`` de su ``dh_src_<rol>`` (las de ``schema.insert_rows`` y
    ``schema.table_digest``): las columnas que da su lectura (``read_role`` de ``interop`` o las
    tablas de un ``SourceEntry``), en el CRS, el datum y los convenios declarados, con el
    sondeo por su nombre; los catálogos, en ``dh_src_catalog`` con su clase (``lithology``,
    ``element``, ``sector``, ``group`` o ``zone``). Las estaciones van sin convertir (si no,
    ``ValueError``); las verticales declaradas no se guardan. ``TypeError`` con columnas de
    otra clase."""
    given = {"collar": collars, "survey": surveys, "lithology": lithology, "assay": assays,
             "zone_interval": zones, "structure": structures}
    found: dict[str, list[tuple[Any, ...]]] = {}
    for role, part in given.items():
        if part is None:
            continue
        expected = _SOURCE_PARTS[role][1]
        if type(part) is not expected:
            raise TypeError(f"lo importado «{role}» son unas {expected.__name__}, no {part!r}")
        if role == "survey":
            part = _check_source_surveys(part)
        if len(part):
            found[role] = _source_rows(role, part)
    if catalogs is not None:
        if not isinstance(catalogs, Catalogs):
            raise TypeError(f"los catálogos son un Catalogs, no {catalogs!r}")
        rows = _catalog_rows(catalogs)
        if rows:
            found["catalog"] = rows
    return {role: found[role] for role in SOURCE_ROLES if role in found}


def _record(kind: type, values: Mapping[str, Any]) -> Any:
    """Un registro de catálogo desde sus valores guardados (los que tiene su tabla)."""
    chosen: dict[str, Any] = {}
    for item in fields(kind):
        if item.name not in values:
            continue
        value = values[item.name]
        if item.name == "extra":
            value = dict(_extra_of(value))
        elif item.name in _BOOL_FIELDS and value is not None:
            value = bool(value)
        chosen[item.name] = value
    return kind(**chosen)


def _catalogs_of(rows: Sequence[Sequence[Any]]) -> Catalogs:
    names = source_layout("catalog").column_names
    kinds = {kind: (attribute, record) for attribute, kind, record in _CATALOG_PARTS}
    found: dict[str, list[Any]] = {attribute: [] for attribute, _, _ in _CATALOG_PARTS}
    for row in rows:
        values = dict(zip(names, row, strict=True))
        attribute, record = kinds[values["catalog"]]
        found[attribute].append(_record(record, values))
    return Catalogs(**found)


def _source_columns(role: str, rows: Sequence[Sequence[Any]]) -> Any:
    """Las columnas del modelo de las filas de ``dh_src_<role>`` (sin enlazar: ``hole`` −1)."""
    layout = source_layout(role)
    columns = _SOURCE_PARTS[role][1]
    stored = dict(zip(layout.column_names, _transpose(rows, len(layout.column_names)),
                      strict=True))
    empty = columns.empty()
    count = len(rows)
    values: dict[str, np.ndarray] = {}
    for item in fields(columns):
        dtype = getattr(empty, item.name).dtype
        column = _SOURCE_COLUMNS.get((role, item.name), item.name)
        if item.name == "hole":
            values[item.name] = np.full(count, -1, dtype=np.int64)
        elif column in stored:
            values[item.name] = _column_values(columns, item.name, stored[column], dtype)
        else:
            values[item.name] = _absent(dtype, count)
    return columns(**values)


def source_entry(input_uid: str, declaration: SourceDeclaration,
                 tables: Mapping[str, Sequence[Sequence[Any]]], *,
                 label: str | None = None) -> SourceEntry:
    """El ``SourceEntry`` de ``dh.build_base`` de la entrada ``input_uid`` (con lo que declara
    su entrada, ``declaration``) desde las filas de lo importado de cada papel (``tables``,
    ``{rol: filas}`` en el orden de las columnas de su ``dh_src_<rol>``, como las da
    :func:`source_tables` o la tabla del proyecto): lo contrario de :func:`source_tables`, con
    los mismos valores (bit a bit en los números) y las estaciones sin convertir.
    ``ValueError`` con un papel que no es de lo importado."""
    parts: dict[str, Any] = {}
    catalogs = Catalogs()
    for role, rows in tables.items():
        if role == "catalog":
            catalogs = _catalogs_of(rows)
        elif role in _SOURCE_PARTS:
            parts[_SOURCE_PARTS[role][0]] = _source_columns(role, rows)
        else:
            raise ValueError(f"{role!r} no es un papel de lo importado de los sondeos: es uno "
                             f"de {', '.join(SOURCE_ROLES)}")
    return SourceEntry(input_uid, declaration, catalogs=catalogs, label=label, **parts)


# --- El informe de una importación (RF-005-12) ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class LogLine:
    """Una línea del informe de una importación en ``dh_import_log`` (RF-005-12): la tabla de la
    fuente (``table_role``: su papel, o la tabla de RecMin), su clase (:data:`LOG_KINDS`) y,
    según ella, los recuentos (leídos, importados, rechazados y sustituidos) o el registro
    rechazado (fila, campo, valor y motivo) o el aviso (``reason``). La operación y la entrada
    las pone :class:`SourceWriter`."""

    table_role: str
    kind: str
    n_read: int | None = None
    n_imported: int | None = None
    n_rejected: int | None = None
    n_replaced: int | None = None
    row_number: int | None = None
    field: str | None = None
    value: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.table_role, str) or not self.table_role.strip():
            raise ValueError(f"una línea del informe dice su tabla, no {self.table_role!r}")
        if self.kind not in LOG_KINDS:
            raise ValueError(f"la clase de una línea del informe es una de "
                             f"{', '.join(LOG_KINDS)}, no {self.kind!r}")
        for name in ("n_read", "n_imported", "n_rejected", "n_replaced", "row_number"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int)
                                      or value < 0):
                raise ValueError(f"«{name}» de una línea del informe es un entero ≥ 0, no "
                                 f"{value!r}")
        for name in ("field", "value", "reason"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise TypeError(f"«{name}» de una línea del informe es un texto, no {value!r}")

    @classmethod
    def summary(cls, table_role: str, read: int, imported: int, rejected: int,
                replaced: int = 0) -> LogLine:
        """Los recuentos de una tabla de la fuente."""
        return cls(table_role, "summary", n_read=read, n_imported=imported,
                   n_rejected=rejected, n_replaced=replaced)

    @classmethod
    def rejection(cls, rejected: Rejection) -> LogLine:
        """Un registro rechazado con su motivo (``drillholes.model.Rejection``)."""
        if not isinstance(rejected, Rejection):
            raise TypeError(f"un rechazo es un drillholes.model.Rejection, no {rejected!r}")
        return cls(rejected.table, "rejected", row_number=rejected.row, field=rejected.field,
                   value=rejected.value, reason=rejected.reason)

    @classmethod
    def warning(cls, table_role: str, text: str) -> LogLine:
        """Un aviso de la importación."""
        return cls(table_role, "warning", reason=text)

    def row(self, operation_uid: str, input_uid: str | None) -> tuple[Any, ...]:
        """Su fila de ``dh_import_log`` (en el orden de sus columnas)."""
        return (operation_uid, input_uid, self.table_role, self.kind, self.n_read,
                self.n_imported, self.n_rejected, self.n_replaced, self.row_number, self.field,
                self.value, self.reason)


# --- Utilidades de escritura ---------------------------------------------------------------------


class _Pacer:
    """El presupuesto de un paso: si ya se gastó (:meth:`due`) y otro nuevo (:meth:`restart`)."""

    def __init__(self, budget_s: float, clock: Callable[[], float]) -> None:
        if isinstance(budget_s, bool) or not isinstance(budget_s, int | float) or budget_s <= 0:
            raise ValueError(f"el presupuesto de un paso es un número de segundos > 0, no "
                             f"{budget_s!r}")
        if not callable(clock):
            raise TypeError(f"el reloj de los pasos es una función, no {clock!r}")
        self.budget = float(budget_s)
        self.clock = clock
        self.start = clock()

    def due(self) -> bool:
        return self.clock() - self.start >= self.budget

    def restart(self) -> None:
        self.start = self.clock()


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? "
                        "COLLATE NOCASE", (table,)).fetchone() is not None


def _rows(value: object, layout: TableLayout, what: str) -> Sequence[Sequence[Any]]:
    """Unas filas de ``layout`` (sin copiarlas: su ancho, la primera aquí y todas al
    insertarlas, sin escribir nada si no)."""
    if isinstance(value, str | bytes | Mapping) or not isinstance(value, Sequence):
        raise TypeError(f"las filas de {what} son una lista de filas, no {value!r}")
    width = len(layout.insert_columns)
    if len(value) and len(value[0]) != width:  # todas, al insertarlas (schema.insert_rows)
        raise ValueError(f"la fila 1 de {what} tiene {len(value[0])} valores y no {width} "
                         f"({', '.join(layout.insert_columns)})")
    return value


def _content(value: object, what: str) -> ContentDigest | None:
    if value is not None and not isinstance(value, ContentDigest):
        raise TypeError(f"el hash de {what} es un ContentDigest (schema.table_digest), no "
                        f"{value!r}")
    return value


def _insert_steps(conn: sqlite3.Connection, layout: TableLayout, table: str,
                  rows: Sequence[Sequence[Any]], pacer: _Pacer) -> Iterator[int]:
    """Inserta ``rows`` por sentencias de :data:`INSERT_ROWS` filas y cede las hechas cada vez
    que el paso gasta su presupuesto."""
    for first in range(0, len(rows), INSERT_ROWS):
        insert_rows(conn, layout, table, rows[first:first + INSERT_ROWS])
        if pacer.due():
            yield min(first + INSERT_ROWS, len(rows))


def _check_handle(project: StoreProject, handle: object, allowed: Sequence[str],
                  what: str) -> OperationHandle:
    if not isinstance(handle, OperationHandle):
        raise TypeError(f"{what} es de un OperationHandle, no {handle!r}")
    if handle.project_uid != project.uid:
        raise ValueError(f"la operación {handle.uid} es de otro proyecto")
    if handle.op_type not in allowed:
        raise ValueError(f"{what} es de una operación {', '.join(allowed)}, no "
                         f"«{handle.op_type}»")
    return handle


def _status(project: StoreProject, uid: str) -> str | None:
    with project.read() as conn:
        row = conn.execute("SELECT status FROM gb_operation WHERE uid = ?", (uid,)).fetchone()
    return None if row is None else str(row[0])


def _abandon(project: StoreProject, handles: Sequence[OperationHandle],
             error: BaseException) -> None:
    """Las operaciones que siguen «en curso», «canceladas» o «fallidas» con su motivo; si no
    se puede registrar, se dice en una nota del error."""
    cancelled = isinstance(error, CANCELLATIONS)
    for handle in handles:
        try:
            if _status(project, handle.uid) != OperationStatus.RUNNING:
                continue
            if cancelled:
                handle.cancel(cancel_reason(error))
            else:
                handle.fail(failure_reason(error))
        except (GeoblenderError, OSError, sqlite3.Error) as exc:
            what = "cancelación" if cancelled else "fallo"
            error.add_note(f"La operación «{handle.op_type}» ({handle.uid}) sigue «en curso» en "
                           f"el proyecto: no se pudo registrar su {what} ({exc}).")


def _check_cancelled(cancelled: Callable[[], bool] | None, text: str) -> None:
    if cancelled is not None and cancelled():
        raise JobCancelled(text)


# --- Lo importado (SourceWriter) -----------------------------------------------------------------


@dataclass(eq=False)
class SourceInput:
    """Una entrada de una orden de importación (:meth:`SourceWriter.add`): su importación
    (``handle``), su ``InputSpec``, el nombre de lo importado (``name``: el de sus datos
    ``dh_src_<rol>_<nombre>``), sus filas por papel y el hash de cada tabla que dio el trabajo
    (``contents``), las líneas de su informe, la entrada a la que sustituye y el motivo, y cómo
    se clasificó. Tras confirmar, ``record`` (la entrada registrada) y ``datasets`` (lo
    registrado: lo importado y el informe); reutilizada, ``reused`` y nada registrado."""

    handle: OperationHandle
    spec: InputSpec
    name: str
    tables: Mapping[str, Sequence[Sequence[Any]]]
    contents: Mapping[str, ContentDigest]
    log: tuple[LogLine, ...]
    previous: InputRecord | None
    reason: str | None
    classification: Classification
    message: str | None = None
    interpreter: Mapping[str, Any] | None = None
    executor: str | None = None
    job_uid: str | None = None
    record: InputRecord | None = None
    datasets: tuple[DatasetRecord, ...] = ()

    @property
    def reused(self) -> bool:
        """Si era la misma entrada con los mismos ajustes (no se escribe nada de ella)."""
        return isinstance(self.classification, Reuse) and self.previous is None

    @property
    def rows(self) -> int:
        return sum(len(rows) for rows in self.tables.values())


def _previous(project: StoreProject, previous_uid: object,
              reason: object) -> tuple[InputRecord | None, str | None]:
    """La entrada activa a la que sustituye y el motivo, obligatorio (RF-008-11)."""
    if reason is not None and not isinstance(reason, str):
        raise TypeError(f"el motivo de una sustitución es un texto, no {reason!r}")
    if previous_uid is None:
        if reason is not None:
            raise ValueError("el motivo acompaña a una sustitución: falta la entrada sustituida "
                             "(previous_uid)")
        return None, None
    if not isinstance(previous_uid, str):
        raise TypeError(f"la entrada sustituida se indica por su uid, no {previous_uid!r}")
    with project.read() as conn:
        record = get_input(conn, previous_uid)
    if record is None:
        raise ProvenanceError("core.input_unknown", input=previous_uid, project=project.name)
    if record.status is InputStatus.SUPERSEDED:
        raise ProvenanceError("core.input_superseded", name=record.name)
    if record.status is InputStatus.DISCARDED:
        raise ProvenanceError("core.input_previous_discarded", previous=record.name)
    text = None if reason is None else reason.strip()
    if not text:
        raise ProvenanceError("core.input_supersede_reason_missing", name=record.name)
    return record, text


class SourceWriter:
    """Lo importado de una orden de importación con uno o varios ficheros (véase el módulo):
    :meth:`add` por cada entrada (clasifica antes de escribir), :meth:`steps` (todo en una
    transacción, por pasos) y, confirmada, :meth:`originals` de cada una."""

    def __init__(self, project: StoreProject) -> None:
        self.project = project
        self._items: list[SourceInput] = []
        self._started = False
        self._committed = False

    @property
    def inputs(self) -> tuple[SourceInput, ...]:
        """Las entradas de la orden, en su orden."""
        return tuple(self._items)

    @property
    def committed(self) -> bool:
        """Si la orden se confirmó."""
        return self._committed

    def add(
        self,
        handle: OperationHandle,
        spec: InputSpec,
        tables: Mapping[str, Sequence[Sequence[Any]]],
        *,
        name: str | None = None,
        contents: Mapping[str, ContentDigest] | None = None,
        log: Sequence[LogLine] = (),
        previous_uid: str | None = None,
        reason: str | None = None,
        message: str | None = None,
        interpreter: Mapping[str, Any] | None = None,
        executor: str | None = None,
        job_uid: str | None = None,
    ) -> SourceInput:
        """Añade a la orden la entrada ``spec`` (``drillholes.provenance.input_spec``) que
        importa la operación ``handle`` (``dh.import_tabular`` o ``dh.import_recmin``, «en
        curso») con sus filas por papel (``tables``: las de :func:`source_tables`), y la
        clasifica antes de escribir nada (RF-008-54):

        - la misma entrada con los mismos ajustes, sin ``previous_uid``: se reutiliza; su
          importación queda «cancelada» con el aviso (``core.inputs.reuse_input``) y no se
          escribe nada de ella;
        - los mismos datos con otros ajustes: tiene que llegar con ``previous_uid`` (esa
          entrada) y ``reason`` (RF-008-11); si no, ``ProvenanceError``
          ``core.input_substitution_required``;
        - si no, una entrada nueva (o la que sustituye a ``previous_uid``).

        ``name``: el de lo importado (por defecto, el nombre lógico de la entrada);
        ``contents``: el hash de cada tabla que dio el trabajo (``schema.table_digest``; las
        que falten, las calcula el registro al escribirlas); ``log``: su informe; ``message``,
        ``interpreter``, ``executor`` y ``job_uid``: los de ``OperationHandle.complete``.

        Rechazos, sin escribir nada: ``ProvenanceError`` (sin CRS o datum declarados,
        ``core.input_crs_missing``; un nombre lógico de otra entrada activa,
        ``core.input_name_taken``; una ``previous_uid`` que no se puede sustituir o sin
        motivo), ``ValidationError`` (``dh.dataset_name_taken``: un dato vivo o de otra entrada
        de la orden con el nombre de lo importado) y ``ValueError``/``TypeError`` (otra
        operación u otro lector, un papel que no produce, unas filas de otra forma, una
        operación repetida o la orden ya escrita)."""
        if self._started:
            raise RuntimeError("la orden ya se está escribiendo: las entradas se añaden antes")
        handle = _check_handle(self.project, handle, IMPORTS,
                               "lo importado de una entrada")
        if not isinstance(spec, InputSpec):
            raise TypeError(f"una importación declara un InputSpec, no {type(spec).__name__}")
        declared = OPERATION_TYPES_BY_NAME[handle.op_type]
        if spec.module != MODULE or spec.reader not in declared.readers:
            raise ValueError(f"«{handle.op_type}» importa con {list(declared.readers)}, no una "
                             f"entrada de «{spec.module}» con «{spec.reader}»")
        if any(item.handle.uid == handle.uid for item in self._items):
            raise ValueError(f"la importación {handle.uid} ya está en la orden: una entrada "
                             "por importación")
        chosen = name if name is not None else spec.name
        planned = self._tables(handle.op_type, tables)
        digests = self._contents(planned, contents)
        lines = tuple(log)
        for line in lines:
            if not isinstance(line, LogLine):
                raise TypeError(f"una línea del informe es un LogLine, no {line!r}")
        previous, text = _previous(self.project, previous_uid, reason)
        with self.project.read() as conn:
            found = classify_import(conn, spec)
            if isinstance(found, Substitute) and (previous is None
                                                  or found.input.uid != previous.uid):
                raise ProvenanceError("core.input_substitution_required", name=spec.name,
                                      existing=found.input.name,
                                      differences=found.describe())
            item = SourceInput(handle, spec, chosen, MappingProxyType(planned),
                               MappingProxyType(digests), lines, previous, text, found,
                               message, interpreter, executor, job_uid)
            if not item.reused:
                same_name = get_input(conn, spec.name)
                if (same_name is not None and same_name.active
                        and (previous is None or same_name.uid != previous.uid)):
                    raise ProvenanceError("core.input_name_taken", name=spec.name)
                self._check_names(conn, planned, chosen, previous)
        if item.reused:
            reuse_input(self.project, handle, found)
        self._items.append(item)
        return item

    def _tables(self, op_type: str, tables: object) -> dict[str, Sequence[Sequence[Any]]]:
        if not isinstance(tables, Mapping):
            raise TypeError(f"lo importado de una entrada es {{papel: filas}}, no {tables!r}")
        produced = [name for name in OPERATION_TYPES_BY_NAME[op_type].outputs
                    if name.startswith(SOURCE_PREFIX)]
        for role in tables:
            if f"{SOURCE_PREFIX}{role}" not in produced:
                raise ValueError(f"«{op_type}» no produce lo importado «{role}»: produce "
                                 f"{produced}")
        return {role: _rows(tables[role], source_layout(role), f"«{SOURCE_PREFIX}{role}»")
                for role in SOURCE_ROLES if role in tables}  # en el orden de los papeles

    @staticmethod
    def _contents(planned: Mapping[str, Any],
                  contents: object) -> dict[str, ContentDigest]:
        if contents is None:
            return {}
        if not isinstance(contents, Mapping):
            raise TypeError(f"los hashes de lo importado son {{papel: ContentDigest}}, no "
                            f"{contents!r}")
        found: dict[str, ContentDigest] = {}
        for role, digest in contents.items():
            if role not in planned:
                raise ValueError(f"un hash de lo importado «{role}», que no se escribe")
            found[role] = _content(digest, f"«{SOURCE_PREFIX}{role}»")
        return found

    def _check_names(self, conn: sqlite3.Connection, planned: Mapping[str, Any], name: str,
                     previous: InputRecord | None) -> None:
        """El nombre de cada dato de lo importado, libre en la orden y entre los vivos (salvo
        los de la entrada sustituida)."""
        live = ", ".join(f"'{status}'" for status in LIVE_STATUSES)
        taken = {source_name(role, item.name) for item in self._items if not item.reused
                 for role in item.tables}
        for role in planned:
            found = source_name(role, name)
            if found in taken:
                raise ValidationError("dh.dataset_name_taken", "otra entrada de la orden "
                                      "escribe un dato con ese nombre: dé otro nombre a lo "
                                      "importado", obj=_OBJ, field="dato", value=found)
            row = conn.execute(f"SELECT input_uid FROM gb_dataset WHERE name = ? AND status IN "
                               f"({live})", (found,)).fetchone()
            if row is not None and (previous is None or row[0] != previous.uid):
                raise ValidationError("dh.dataset_name_taken", "ya hay un dato vivo con ese "
                                      "nombre: dé otro nombre a lo importado", obj=_OBJ,
                                      field="dato", value=found)

    def steps(
        self,
        *,
        software: Mapping[str, str] | None = None,
        budget_s: float = STEP_BUDGET_S,
        cancelled: Callable[[], bool] | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> Generator[float, None, tuple[SourceInput, ...]]:
        """Escribe la orden en una transacción, por pasos (véase el módulo), con el avance
        (0–1) tras cada paso; devuelve (``StopIteration.value``) sus entradas, con lo
        registrado. ``software``: las versiones de las bibliotecas de las importaciones
        (``{"pyproj": …}``, RF-008-18). Las entradas reutilizadas no escriben nada; sin
        ninguna que escribir, no abre la transacción. Un error o ``cancelled()`` antes del
        ``COMMIT``: nada escrito y cada importación «fallida» o «cancelada» con su motivo (el
        error sigue). ``RuntimeError`` si ya se escribió."""
        if self._started:
            raise RuntimeError("la orden ya se escribió (o se está escribiendo)")
        self._started = True
        pacer = _Pacer(budget_s, clock)
        pending = [item for item in self._items if not item.reused]
        if not pending:
            self._committed = True
            return tuple(self._items)
        total = sum(item.rows + 1 for item in pending)
        done = 0
        try:
            with self.project.write_transaction() as conn:
                for item in pending:
                    for count in self._write(conn, item, pacer):
                        _check_cancelled(cancelled, f"Importación de «{item.spec.name}» "
                                         "cancelada")
                        yield (done + count) / total
                        pacer.restart()
                    item.datasets = self._complete(conn, item, software)
                    done += item.rows + 1
                    # Un paso por entrada completada: el COMMIT, en el suyo.
                    _check_cancelled(cancelled, f"Importación de «{item.spec.name}» cancelada")
                    yield done / total
                    pacer.restart()
        except GeneratorExit:
            self._forget(pending)
            raise
        except BaseException as error:
            self._forget(pending)
            _abandon(self.project, [item.handle for item in pending], error)
            raise
        self._committed = True
        return tuple(self._items)

    @staticmethod
    def _forget(items: Sequence[SourceInput]) -> None:
        for item in items:
            item.record = None
            item.datasets = ()

    def _write(self, conn: sqlite3.Connection, item: SourceInput,
               pacer: _Pacer) -> Iterator[int]:
        """Registra la entrada de ``item`` y escribe lo importado y su informe; cede las filas
        hechas."""
        handle = item.handle
        previous_uid = None if item.previous is None else item.previous.uid
        if previous_uid is not None:
            supersede(conn, self.project, previous_uid, operation_uid=handle.uid,
                      reason=item.reason)
        record = register_input(conn, self.project, item.spec, operation_uid=handle.uid,
                                previous_uid=previous_uid, reason=item.reason)
        item.record = record
        done = 0
        for role, rows in item.tables.items():
            layout, table = source_layout(role), source_table(role, item.name, record.uid)
            create_table(conn, layout, table, None,
                         description=f"{layout.label}: lo importado de la entrada "
                                     f"«{record.name}» por Geoblender")
            for count in _insert_steps(conn, layout, table, rows, pacer):
                yield done + count
            done += len(rows)
        log = LAYOUTS[IMPORT_LOG]
        if not _table_exists(conn, IMPORT_LOG):
            create_table(conn, log, IMPORT_LOG, None,
                         description="Informe de las importaciones de sondeos de Geoblender")
        insert_rows(conn, log, IMPORT_LOG, [line.row(handle.uid, record.uid)
                                            for line in item.log])

    def _complete(self, conn: sqlite3.Connection, item: SourceInput,
                  software: Mapping[str, str] | None) -> tuple[DatasetRecord, ...]:
        assert item.record is not None
        epsg = dict(item.spec.crs_h or {}).get("epsg")  # el CRS declarado de las bocas
        epsg = epsg if isinstance(epsg, int) and not isinstance(epsg, bool) else None
        specs: list[DatasetSpec] = [
            source_spec(role, item.name, item.record.uid, content=item.contents.get(role),
                        crs_epsg=epsg if role == "collar" else None)
            for role in item.tables]
        specs.append(dataset_spec(IMPORT_LOG))
        return item.handle.complete(conn, outputs=specs, software=software,
                                    message=item.message, interpreter=item.interpreter,
                                    executor=item.executor, job_uid=item.job_uid)

    def originals(
        self,
        item: SourceInput,
        verified_copies: Sequence[Any],
        *,
        budget_s: float = 0.02,
        same_volume: Callable[[Any, Any], bool] | None = None,
    ) -> Iterator[ProjectProgress]:
        """Los pasos que guardan el original de la entrada de ``item`` (RF-008-53;
        ``core.inputs.store_originals_steps``, como una tabla) desde ``verified_copies``, la
        copia verificada de cada fichero que hizo su trabajo (``JobDir.copy_input``), nunca la
        fuente (RF-008-14). ``RuntimeError`` si la orden no se confirmó o la entrada se
        reutilizó."""
        if item not in self._items:
            raise ValueError("esa entrada no es de esta orden")
        if not self._committed or item.record is None:
            raise RuntimeError(f"la entrada «{item.spec.name}» no se registró: el original se "
                               "guarda tras confirmar su importación")
        return store_originals_steps(self.project, item.record.uid, verified_copies,
                                     tabular=True, budget_s=budget_s, same_volume=same_volume)


# --- La base y lo calculado (BaseWriter) ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Planned:
    rows: Sequence[Sequence[Any]]
    content: ContentDigest | None
    detail: Any


def _owned(conn: sqlite3.Connection, table: str) -> bool:
    """Si la tabla ``table`` es la del dato vivo con su nombre (que se puede reescribir)."""
    live = ", ".join(f"'{status}'" for status in LIVE_STATUSES)
    return conn.execute(f"SELECT 1 FROM gb_dataset WHERE store = 'gpkg' AND locator = ? AND "
                        f"name = ? AND status IN ({live})", (table, table)).fetchone() is not None


def _drop(conn: sqlite3.Connection, table: str) -> None:
    """Quita la tabla ``table`` (SQLite quita con ella sus disparadores, sus índices y su
    contador de ``fid`` de ``sqlite_sequence``) y su registro GeoPackage (títulos, geometría y
    contenido), en la transacción de ``conn``."""
    conn.execute(f'DROP TABLE "{table}"')
    if _table_exists(conn, "gpkg_data_columns"):
        conn.execute("DELETE FROM gpkg_data_columns WHERE table_name = ?", (table,))
    conn.execute("DELETE FROM gpkg_geometry_columns WHERE table_name = ?", (table,))
    conn.execute("DELETE FROM gpkg_contents WHERE table_name = ?", (table,))


def _hashes_in(conn: sqlite3.Connection) -> dict[str, str]:
    """La huella de la desviación de cada sondeo de ``dh_collar`` (vacío sin la tabla)."""
    if not _table_exists(conn, "dh_collar"):
        return {}
    return dict(conn.execute("SELECT name, survey_sha256 FROM dh_collar").fetchall())


def _hashes_of(rows: Sequence[Sequence[Any]]) -> dict[str, str]:
    """La huella de la desviación de cada sondeo de unas filas de ``dh_collar``."""
    columns = LAYOUTS["dh_collar"].insert_columns
    name, digest = columns.index("name"), columns.index("survey_sha256")
    return {row[name]: row[digest] for row in rows}


def _project_references(conn: sqlite3.Connection) -> tuple[CrsRef, VerticalRef]:
    """El CRS horizontal y la referencia vertical de ``gb_project``, del catálogo de la 002."""
    row = conn.execute("SELECT crs_epsg, vcrs_epsg, vcrs_note FROM gb_project").fetchone()
    if row is None:
        raise ValueError("el proyecto no tiene su fila de gb_project")
    catalog = load_catalog()
    crs = catalog.horizontal(int(row[0]))
    vertical = (catalog.local_vertical(row[2]) if row[1] is None
                else catalog.vertical(int(row[1])))
    return crs, vertical


class BaseWriter:
    """Las tablas que reescribe una operación de ``dh.build_base`` (las once de la base),
    ``dh.validate`` (``dh_validation_issue``) o ``dh.desurvey`` (``dh_trace``), por pasos en
    una transacción (véase el módulo): :meth:`table` (o :meth:`base`) por cada una y
    :meth:`steps`."""

    def __init__(self, project: StoreProject, handle: OperationHandle) -> None:
        self.project = project
        self.handle = _check_handle(project, handle, _BASE_TYPES, "la base de los sondeos")
        self.outputs: tuple[str, ...] = OPERATION_TYPES_BY_NAME[handle.op_type].outputs
        self._planned: dict[str, _Planned] = {}
        self._started = False

    def table(self, name: str, rows: Sequence[Sequence[Any]], *,
              content: ContentDigest | None = None, detail: Any = None) -> None:
        """Prepara la tabla ``name`` (una de las que escribe la operación) con ``rows`` (en el
        orden de su ``fid`` y de ``TableLayout.insert_columns``); ``content``: su hash, el que
        dio el trabajo (``schema.table_digest``; sin él, lo calcula el registro); ``detail``:
        lo que cuenta su cambio (en ``dh_collar``, por defecto, los sondeos cuya huella de la
        desviación cambia, ``{"holes": [...]}``). ``ValueError`` si la operación no escribe esa
        tabla, ya está preparada o una fila no tiene sus valores."""
        if self._started:
            raise RuntimeError("las tablas se preparan antes de escribirlas")
        if name not in self.outputs:
            raise ValueError(f"«{self.handle.op_type}» escribe {list(self.outputs)}, no "
                             f"{name!r}")
        if name in self._planned:
            raise ValueError(f"la tabla «{name}» ya está preparada")
        self._planned[name] = _Planned(_rows(rows, LAYOUTS[name], f"«{name}»"),
                                       _content(content, f"«{name}»"), detail)

    def base(self, tables: BaseTables, *,
             contents: Mapping[str, ContentDigest] | None = None) -> None:
        """Prepara las once tablas de la base de ``tables`` (``build_base.build_base``) con
        su hash de ``contents`` (por tabla)."""
        if not isinstance(tables, BaseTables):
            raise TypeError(f"la base son unas BaseTables, no {tables!r}")
        chosen = dict(contents or {})
        for name in BASE_TABLES:
            self.table(name, tables.rows(name), content=chosen.get(name))

    def steps(
        self,
        *,
        software: Mapping[str, str] | None = None,
        message: str | None = None,
        interpreter: Mapping[str, Any] | None = None,
        executor: str | None = None,
        job_uid: str | None = None,
        budget_s: float = STEP_BUDGET_S,
        cancelled: Callable[[], bool] | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> Generator[float, None, tuple[DatasetRecord, ...]]:
        """Reescribe las tablas preparadas en una transacción, por pasos, con el avance (0–1)
        tras cada uno, y completa la operación con sus ``DatasetSpec`` (``software``,
        ``message``… los de ``OperationHandle.complete``); devuelve lo registrado. Cada tabla
        se quita y se crea de nuevo (sus ``fid``, desde 1). ``ValueError`` si falta alguna de
        las que escribe la operación; ``ValidationError`` ``dh.table_exists`` si una tabla con
        su nombre no es la de su dato (no se toca). Un error o ``cancelled()`` antes del
        ``COMMIT``: nada cambia y la operación queda «fallida» o «cancelada» con su motivo."""
        if self._started:
            raise RuntimeError("las tablas ya se escribieron (o se están escribiendo)")
        missing = [name for name in self.outputs if name not in self._planned]
        if missing:
            raise ValueError(f"«{self.handle.op_type}» escribe {list(self.outputs)}: faltan "
                             f"{missing}")
        self._started = True
        pacer = _Pacer(budget_s, clock)
        total = sum(len(planned.rows) + 1 for planned in self._planned.values())
        done = 0
        text = f"Escritura de «{self.handle.op_type}» cancelada"
        try:
            with self.project.write_transaction() as conn:
                crs, vertical = _project_references(conn)
                specs: list[DatasetSpec] = []
                for name in self.outputs:
                    planned = self._planned[name]
                    layout = LAYOUTS[name]
                    detail = planned.detail
                    if name == "dh_collar" and detail is None:
                        detail = {"holes": list(changed_holes(_hashes_in(conn),
                                                              _hashes_of(planned.rows)))}
                    if _table_exists(conn, name):
                        if not _owned(conn, name):
                            raise ValidationError(
                                "dh.table_exists", "ya hay en el GeoPackage del proyecto una "
                                "tabla con ese nombre que no es la de su dato: no se sustituye",
                                obj=_OBJ, field="tabla", value=name)
                        _drop(conn, name)
                    srs = crs.epsg if layout.geometry_type is not None else None
                    description = f"{layout.label} de Geoblender"
                    if layout.geometry_type is not None:
                        from ..gis.vector import z_description

                        description += f"; {z_description(vertical)}"
                    create_table(conn, layout, name, srs, description=description)
                    for count in _insert_steps(conn, layout, name, planned.rows, pacer):
                        _check_cancelled(cancelled, text)
                        yield (done + count) / total
                        pacer.restart()
                    done += len(planned.rows) + 1
                    specs.append(dataset_spec(name, content=planned.content, crs_epsg=srs,
                                              detail=detail))
                    if pacer.due():
                        _check_cancelled(cancelled, text)
                        yield done / total
                        pacer.restart()
                records = self.handle.complete(conn, outputs=specs, software=software,
                                               message=message, interpreter=interpreter,
                                               executor=executor, job_uid=job_uid)
                _check_cancelled(cancelled, text)
                yield 1.0  # el COMMIT, en su paso
        except GeneratorExit:
            raise
        except BaseException as error:
            _abandon(self.project, [self.handle], error)
            raise
        return records


# --- Lectura -------------------------------------------------------------------------------------


def existing_holes(conn: sqlite3.Connection) -> tuple[str, ...]:
    """Los sondeos de la base del proyecto (``dh_collar``), por su ``fid``: los que una
    importación pregunta si sustituir o conservar (RF-005-11). Vacío sin la tabla."""
    if not _table_exists(conn, "dh_collar"):
        return ()
    return tuple(row[0] for row in conn.execute("SELECT name FROM dh_collar ORDER BY fid"))


def stale_holes(conn: sqlite3.Connection) -> tuple[str, ...]:
    """Los sondeos con la traza obsoleta (RF-005-22): los de ``dh_trace`` cuya huella de la
    desviación (``survey_sha256``, la que usó la traza) no es la de su boca en ``dh_collar``,
    por el ``fid`` de la boca. Un sondeo sin traza no sale (no tiene una obsoleta); vacío sin
    las tablas."""
    if not (_table_exists(conn, "dh_collar") and _table_exists(conn, "dh_trace")):
        return ()
    return tuple(row[0] for row in conn.execute(
        "SELECT c.name FROM dh_collar c JOIN dh_trace t ON t.hole_id = c.fid "
        "WHERE t.survey_sha256 IS NOT c.survey_sha256 ORDER BY c.fid"))


def survey_hashes(conn: sqlite3.Connection) -> list[str]:
    """La huella de la desviación (``survey_sha256``) de cada boca de ``dh_collar``, por su
    ``fid`` (T28): la que guarda cada traza de ``dh.desurvey`` (RF-005-22). Vacía sin la
    tabla."""
    if not _table_exists(conn, "dh_collar"):
        return []
    return [row[0] for row in conn.execute("SELECT survey_sha256 FROM dh_collar ORDER BY fid")]


def kept_traces(conn: sqlite3.Connection, *, method: str,
                params: Mapping[str, str]) -> list[tuple[Any, ...]]:
    """Las trazas que conserva un cálculo de «solo las obsoletas» (T28; RF-005-22, plan
    §5.3.1): las filas de ``dh_trace`` (en el orden de ``TableLayout.insert_columns`` y de su
    sondeo) de los sondeos cuya traza no está obsoleta (:func:`stale_holes`: la huella de su
    desviación es la de su boca), si la operación que escribió ``dh_trace`` usó el método
    ``method`` y los mismos parámetros (``params``: ``{clave: value_sha256}``, los que resuelve
    la operación nueva); si no, ninguna: con otro método u otros parámetros todas están
    obsoletas. Sin las tablas, ninguna."""
    if not (_table_exists(conn, "dh_collar") and _table_exists(conn, "dh_trace")):
        return []
    live = ", ".join(f"'{status}'" for status in LIVE_STATUSES)
    found = conn.execute(
        f"SELECT o.uid, o.settings FROM gb_dataset d JOIN gb_operation o ON "
        f"o.uid = d.operation_uid WHERE d.name = 'dh_trace' AND d.store = 'gpkg' AND "
        f"d.status IN ({live})").fetchone()
    if found is None:
        return []
    settings = json.loads(found[1] or "{}")
    used = dict(conn.execute("SELECT key, value_sha256 FROM gb_operation_param WHERE "
                             "operation_uid = ?", (found[0],)).fetchall())
    if settings.get("method") != method or used != dict(params):
        return []
    columns = ", ".join(f't."{name}"' for name in LAYOUTS["dh_trace"].insert_columns)
    return [tuple(row) for row in conn.execute(
        f"SELECT {columns} FROM dh_trace t JOIN dh_collar c ON t.hole_id = c.fid "
        f"WHERE t.survey_sha256 IS c.survey_sha256 ORDER BY t.hole_id, t.fid")]


VALIDATION_TABLE = "dh_validation_issue"
"""La tabla (y el dato) del informe de la última validación (``dh.validate``)."""


@dataclass(frozen=True)
class StoredValidation:
    """El informe de la última validación de los sondeos guardado en el proyecto (T27;
    RF-005-16, RF-005-19; plan §5.6.4 y §5.6.9): el dato ``dh_validation_issue`` (su uid), sus
    filas en el orden de su ``fid`` (cada una, por el nombre de sus columnas: las de
    ``drillholes.jobs.issue_rows``) y la operación ``dh.validate`` que lo escribió por última
    vez (su uid y sus ajustes; ``None`` y vacíos si no se encuentra)."""

    dataset_uid: str
    records: tuple[Mapping[str, Any], ...]
    operation_uid: str | None = None
    settings: Mapping[str, Any] = MappingProxyType({})

    @property
    def notes(self) -> tuple[Note, ...]:
        """Lo que el informe dice que no se evaluó (``drillholes.validate.Note``), de los
        ajustes de su operación: sin MDT (``surface`` vacío, D-19), DH-W05 en ninguna boca.
        Las bocas fuera del MDT no se guardan en el proyecto (las dice el informe de la
        operación al validar)."""
        if "surface" in self.settings and self.settings["surface"] is None:
            return (no_dem_note(),)
        return ()


def stored_validation(conn: sqlite3.Connection) -> StoredValidation | None:
    """El informe de la última validación guardado en el proyecto (``conn``, de lectura):
    :class:`StoredValidation`; ``None`` si el proyecto no tiene el dato vivo
    ``dh_validation_issue`` o su tabla. Pocas filas: de una vez."""
    record = get_dataset(conn, VALIDATION_TABLE)
    if record is None or not record.live or not _table_exists(conn, record.locator):
        return None
    names = LAYOUTS[VALIDATION_TABLE].column_names
    listed = ", ".join(f'"{name}"' for name in names)
    records = tuple(MappingProxyType(dict(zip(names, row, strict=True))) for row in conn.execute(
        f'SELECT {listed} FROM "{record.locator}" ORDER BY fid'))
    found = conn.execute(
        "SELECT o.uid, o.settings FROM gb_operation_io i JOIN gb_operation o "
        "ON o.uid = i.operation_uid WHERE i.direction = 'out' AND i.item_kind = 'dataset' "
        "AND i.item_uid = ? AND o.op_type = ? AND o.status = ? "
        "ORDER BY o.finished_at DESC, o.fid DESC LIMIT 1",
        (record.uid, VALIDATE, str(OperationStatus.DONE))).fetchone()
    if found is None:
        return StoredValidation(record.uid, records)
    return StoredValidation(record.uid, records, found[0],
                            MappingProxyType(json.loads(found[1])))


def export_report(project: StoreProject, handle: OperationHandle, stored: StoredValidation,
                  target: str | os.PathLike[str], *, locator: str | None,
                  message: str) -> DatasetSpec | None:
    """Exporta el informe guardado ``stored`` a ``target`` con la operación
    ``dh.export_validation`` ``handle`` (T27; RF-005-19; plan §5.6.4 y §5.6.9): el CSV de T11
    (``report.stored_rows``) por un temporal y ``os.replace`` y, en una transacción,
    ``OperationHandle.complete`` con ``message``. Dentro de ``exports/`` (``locator``, su
    ubicación ``exports/<ruta>``) es el dato ``dh_exp_<ruta>`` con el hash de sus bytes
    (``core.document@1``), que devuelve; fuera del proyecto (``None``), ninguno (D21 de la
    006). Comprobar el destino (``check_write_target``, su extensión, que no esté en otra
    carpeta del proyecto) y confirmar la sustitución es de quien llama. Los errores de
    ``report.write_rows`` (el destino abierto por otro programa, el disco) y los de la 008, tal
    cual, con la operación «en curso» (quien llama la deja fallida); ``ValueError`` si
    ``handle`` no es una exportación."""
    _check_handle(project, handle, (EXPORT_VALIDATION,), "exportar el informe de validación")
    path = Path(target)
    rows = report.stored_rows(stored.records, stored.notes)
    if locator is not None:
        handle.claim_paths(path, path.with_name(path.name + report.TEMPORARY_SUFFIX))
        path.parent.mkdir(parents=True, exist_ok=True)
    report.write_rows(rows, path)
    spec = None
    if locator is not None:
        request = DOCUMENT.request(EXPORT_KIND, DATASET_DECLARATIONS, {MAIN_ROLE: path})
        spec = export_spec(locator, read_content(DOCUMENT, request))
    with project.write_transaction() as conn:
        handle.complete(conn, outputs=() if spec is None else (spec,), message=message)
    return spec


def read_catalogs(conn: sqlite3.Connection) -> Catalogs:
    """Los catálogos de la base de los sondeos del proyecto (``dh_lithology_code``,
    ``dh_element``, ``dh_sector``, ``dh_group`` y ``dh_zone``, por su ``fid``; los que no
    están, vacíos): con los que una importación compara los códigos de su fuente
    (RF-005-10). Pocas filas: de una vez."""
    found: dict[str, list[Any]] = {}
    for table, (attribute, record) in _BASE_CATALOGS.items():
        found[attribute] = (_catalog_records(conn, table, record)[1]
                            if _table_exists(conn, table) else [])
    return Catalogs(**found)


@dataclass(frozen=True)
class LiveSource:
    """Lo importado vigente de una entrada de los sondeos (plan §5.6.1 y §5.6.10): la entrada
    activa (``record``, su fila de ``gb_input``) y sus datos vivos de lo importado por papel
    (``datasets``: ``dh_src_<rol>_<nombre>``, en el orden de
    ``drillholes.schema.SOURCE_ROLES``)."""

    record: InputRecord
    datasets: Mapping[str, DatasetRecord]

    @property
    def declaration(self) -> SourceDeclaration:
        """Lo que declara su entrada (``provenance.input_declaration``)."""
        record = self.record
        return input_declaration(record.reader, record.crs_h, record.crs_v, record.settings)


def live_sources(conn: sqlite3.Connection) -> tuple[LiveSource, ...]:
    """Lo importado vigente del proyecto (``conn``, de lectura; plan §5.6.1 y §5.6.10): cada
    entrada activa de los sondeos con sus datos vivos de lo importado, **en el orden en que se
    registraron** (su ``registered_at`` y, si empatan, el de su fila en ``gb_input``): el que
    ``dh.build_base`` necesita para la precedencia (la más reciente manda, RF-005-11). Vacío
    sin nada importado."""
    live = ", ".join(f"'{status}'" for status in LIVE_STATUSES)
    rows = conn.execute(
        f"SELECT d.uid, d.name, d.input_uid FROM gb_dataset d JOIN gb_input i ON "
        f"i.uid = d.input_uid WHERE d.module = ? AND d.status IN ({live}) "
        f"ORDER BY i.registered_at, i.rowid", (MODULE,)).fetchall()
    grouped: dict[str, list[DatasetRecord]] = {}
    for dataset_uid, name, input_uid in rows:
        record = get_dataset(conn, dataset_uid) if name.startswith(SOURCE_PREFIX) else None
        if record is not None:
            grouped.setdefault(input_uid, []).append(record)
    found: list[LiveSource] = []
    for input_uid, datasets in grouped.items():
        record = get_input(conn, input_uid)
        if record is None or not record.active:
            continue
        by_role = {layout_of(dataset.locator).role: dataset for dataset in datasets}
        found.append(LiveSource(record, MappingProxyType(
            {role: by_role[role] for role in SOURCE_ROLES if role in by_role})))
    return tuple(found)


_HOLE_COLUMNS: Mapping[str, str] = MappingProxyType({
    role: ("name" if role == "collar" else "hole_name")
    for role in SOURCE_ROLES if role != "catalog"})
"""La columna del sondeo de lo importado de cada papel (los catálogos no tienen)."""


def source_holes(conn: sqlite3.Connection, source: LiveSource) -> tuple[str, ...]:
    """Los sondeos de lo importado vigente de la entrada de ``source`` (T28; RF-005-11): los
    nombres de sus bocas y de las filas de sus demás tablas, como se escribieron, sin repetir
    (sin distinguir mayúsculas) y por orden alfabético; los que una reimportación de esa
    entrada sustituye sin preguntar. Un catálogo, ninguno."""
    found: dict[str, str] = {}
    for role, dataset in source.datasets.items():
        column = _HOLE_COLUMNS.get(role)
        if column is None:
            continue
        for (name,) in conn.execute(f'SELECT DISTINCT "{column}" FROM "{dataset.locator}" '
                                    f'WHERE "{column}" IS NOT NULL'):
            found.setdefault(name_key(name), name)
    return tuple(found[key] for key in sorted(found))


def _join(columns: type, parts: Sequence[Any]) -> Any:
    """Unas columnas (de la clase ``columns``) una tras otra."""
    if len(parts) == 1:
        return parts[0]
    chosen = [columns.empty(), *parts]
    return columns(**{item.name: np.concatenate([getattr(part, item.name) for part in chosen])
                      for item in fields(columns)})


def source_entry_steps(
    conn: sqlite3.Connection,
    source: LiveSource,
    *,
    budget_s: float = STEP_BUDGET_S,
    clock: Callable[[], float] = time.perf_counter,
) -> Generator[float, None, SourceEntry]:
    """Lee por pasos lo importado de la entrada ``source`` (``conn``, de lectura) y lo
    devuelve (``StopIteration.value``) como el ``SourceEntry`` de ``dh.build_base``: las filas
    de cada ``dh_src_*`` en el orden de su ``fid``, por trozos de :data:`READ_ROWS` filas
    convertidos al leerlos (los de :func:`source_entry`, bit a bit), con lo que declara su
    entrada y su nombre lógico como ``label``. Cede el avance (0–1) cada vez que un paso gasta
    ``budget_s``."""
    pacer = _Pacer(budget_s, clock)
    total = max(1, sum(conn.execute(f'SELECT count(*) FROM "{dataset.locator}"').fetchone()[0]
                       for dataset in source.datasets.values()))
    done = 0
    parts: dict[str, Any] = {}
    catalogs = Catalogs()
    for role, dataset in source.datasets.items():
        layout = source_layout(role)
        quoted = ", ".join(f'"{column}"' for column in layout.insert_columns)
        sql = (f'SELECT fid, {quoted} FROM "{dataset.locator}" WHERE fid > ? ORDER BY fid '
               f"LIMIT {READ_ROWS}")
        chunks: list[Any] = []
        catalog_rows: list[tuple[Any, ...]] = []
        last = -1
        while True:
            rows = conn.execute(sql, (last,)).fetchall()
            if not rows:
                break
            last = rows[-1][0]
            stored = [tuple(row[1:]) for row in rows]
            if role == "catalog":
                catalog_rows.extend(stored)
            else:
                chunks.append(_source_columns(role, stored))
            done += len(rows)
            if pacer.due():
                yield min(done / total, 1.0)
                pacer.restart()
        if role == "catalog":
            catalogs = _catalogs_of(catalog_rows)
        else:
            attribute, columns = _SOURCE_PARTS[role]
            parts[attribute] = _join(columns, chunks) if chunks else columns.empty()
    record = source.record
    return SourceEntry(record.uid, source.declaration, catalogs=catalogs, label=record.name,
                       **parts)


def _ids(values: Sequence[Any]) -> np.ndarray:
    """Unos ids guardados (``fid`` de otra tabla) en int64, −1 sin id."""
    return np.fromiter((-1 if value is None else value for value in values), dtype=np.int64,
                       count=len(values))


class _Reading:
    """Una lectura por pasos de la base: su presupuesto y el avance que cede."""

    def __init__(self, conn: sqlite3.Connection, pacer: _Pacer, total: int) -> None:
        self.conn = conn
        self.pacer = pacer
        self.total = max(total, 1)
        self.done = 0

    def pause(self) -> Iterator[float]:
        """Cede el avance si el paso gastó su presupuesto."""
        if self.pacer.due():
            yield min(self.done / self.total, 1.0)
            self.pacer.restart()

    def table(self, table: str, convert: Mapping[str, Callable[[list[Any]], np.ndarray]]
              ) -> Generator[float, None, tuple[np.ndarray, dict[str, np.ndarray]]]:
        """El ``fid`` y las columnas ``convert`` de ``table`` (cada una con su conversión),
        por trozos de :data:`READ_ROWS` filas en el orden del ``fid``: cada trozo se convierte
        al leerlo y cede el avance si el paso gastó su presupuesto."""
        names = list(convert)
        quoted = ", ".join(f'"{column}"' for column in names)
        sql = (f'SELECT fid, {quoted} FROM "{table}" WHERE fid > ? ORDER BY fid '
               f"LIMIT {READ_ROWS}")
        fids: list[np.ndarray] = [np.zeros(0, dtype=np.int64)]
        found: dict[str, list[np.ndarray]] = {name: [] for name in names}
        last = -1
        while True:
            rows = self.conn.execute(sql, (last,)).fetchall()
            if not rows:
                break
            parts = _transpose(rows, len(names) + 1)
            fids.append(np.array(parts[0], dtype=np.int64))
            for name, values in zip(names, parts[1:], strict=True):
                found[name].append(convert[name](values))
            last = rows[-1][0]
            self.done += len(rows)
            yield from self.pause()
        yield from self.pause()
        columns = {name: (np.concatenate(parts) if parts else convert[name]([]))
                   for name, parts in found.items()}
        return np.concatenate(fids), columns


def _converters(columns: type, table: str,
                ids: Sequence[str]) -> dict[str, Callable[[list[Any]], np.ndarray]]:
    """La conversión de cada columna de ``table`` que es un campo de ``columns`` (y de los
    ids ``ids``, en int64)."""
    empty = columns.empty()
    names = set(LAYOUTS[table].column_names)
    found: dict[str, Callable[[list[Any]], np.ndarray]] = {name: _ids for name in ids}
    for item in fields(columns):
        if item.name in names:
            dtype = getattr(empty, item.name).dtype

            def convert(values: list[Any], name: str = item.name,
                        dtype: np.dtype = dtype) -> np.ndarray:
                return _column_values(columns, name, values, dtype)

            found[item.name] = convert
    return found


def _positions(fids: np.ndarray, ids: np.ndarray) -> np.ndarray:
    """La posición (por su ``fid``) de cada id de ``ids`` (int64, −1 sin id) en una tabla de
    ``fids`` ordenados; −1 sin id o si no está."""
    if not len(fids):
        return np.full(len(ids), -1, dtype=np.int64)
    found = np.minimum(np.searchsorted(fids, ids), len(fids) - 1)
    known = (ids >= 0) & (fids[found] == ids)
    return np.where(known, found, -1).astype(np.int64)


def _codes(positions: np.ndarray, codes: Sequence[str]) -> np.ndarray:
    """El código de cada posición (``None`` en −1)."""
    lookup = np.array([*codes, None], dtype=object)
    return lookup[np.where(positions >= 0, positions, len(codes))]


def _catalog_records(conn: sqlite3.Connection, table: str, record: type) -> tuple[np.ndarray,
                                                                                  list[Any]]:
    """El ``fid`` y los registros de un catálogo de la base (pocas filas: de una vez)."""
    names = LAYOUTS[table].column_names
    quoted = ", ".join(f'"{column}"' for column in names)
    rows = conn.execute(f'SELECT fid, {quoted} FROM "{table}" ORDER BY fid').fetchall()
    return (np.array([row[0] for row in rows], dtype=np.int64),
            [_record(record, dict(zip(names, row[1:], strict=True))) for row in rows])


def read_steps(
    conn: sqlite3.Connection,
    *,
    crs: CrsRef | None = None,
    vertical: VerticalRef | None = None,
    parts: Sequence[str] | None = None,
    budget_s: float = STEP_BUDGET_S,
    clock: Callable[[], float] = time.perf_counter,
) -> Generator[float, None, DrillholeSet]:
    """Lee la base de los sondeos del proyecto (``conn``, una conexión de lectura) por pasos
    a un ``DrillholeSet`` en su CRS y su datum (``crs`` y ``vertical``; por defecto, los de
    ``gb_project``) y lo devuelve (``StopIteration.value``): las bocas y cada tabla en el orden
    de su ``fid`` (``hole`` = la posición de su boca), los códigos de catálogo y el sondeo de
    cada fila por su id (con la grafía de su catálogo y de su boca) y los catálogos. Sin las
    tablas, un conjunto vacío. Cede el avance (0–1) cada vez que un paso gasta ``budget_s``.
    ``parts`` (T28): las tablas de los tramos y las estaciones que se leen además de las bocas
    y los catálogos (``("dh_survey",)``, lo que necesitan las trazas); las demás, vacías. Por
    defecto, todas. ``ValueError`` con una que no es de la base."""
    if (crs is None) != (vertical is None):
        raise ValueError("se dan los dos, el CRS y la referencia vertical, o ninguno")
    known = tuple(table for table, _, _ in _BASE_PARTS)
    chosen = known if parts is None else tuple(parts)
    unknown = sorted(set(chosen) - set(known))
    if unknown or isinstance(parts, str):
        raise ValueError(f"las tablas que se leen además de las bocas son de {list(known)}, "
                         f"no {unknown or parts!r}")
    if crs is None or vertical is None:
        crs, vertical = _project_references(conn)
    if not _table_exists(conn, "dh_collar"):
        return DrillholeSet(crs=crs, vertical=vertical)
    tables = [name for name in BASE_TABLES if _table_exists(conn, name)
              and (name not in known or name in chosen)]
    catalogs: dict[str, list[Any]] = {}
    catalog_fids: dict[str, np.ndarray] = {}
    for table, (attribute, record) in _BASE_CATALOGS.items():
        catalogs[attribute], catalog_fids[table] = [], np.zeros(0, dtype=np.int64)
        if table in tables:
            catalog_fids[table], catalogs[attribute] = _catalog_records(conn, table, record)
    codes = {table: [item.code for item in catalogs[attribute]]
             for table, (attribute, _) in _BASE_CATALOGS.items()}
    total = sum(conn.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
                for name, _, _ in (("dh_collar", "", ""), *_BASE_PARTS) if name in tables)
    reading = _Reading(conn, _Pacer(budget_s, clock), total)

    collar_fids, stored = yield from reading.table(
        "dh_collar", _converters(CollarColumns, "dh_collar", ("sector_id", "group_id")))
    yield from reading.pause()
    for name, table in (("sector", "dh_sector"), ("group", "dh_group")):
        stored[name] = _codes(_positions(catalog_fids[table], stored.pop(f"{name}_id")),
                              codes[table])
    collars = CollarColumns(**stored)
    names = collars.name.tolist()
    yield from reading.pause()

    parts: dict[str, Any] = {}
    for table, attribute, columns in _BASE_PARTS:
        if table not in tables:
            parts[attribute] = columns.empty()
            continue
        catalog = _CATALOG_ID.get(table)
        ids = ("hole_id",) if catalog is None else ("hole_id", catalog[0])
        _, stored = yield from reading.table(table, _converters(columns, table, ids))
        yield from reading.pause()
        hole = _positions(collar_fids, stored.pop("hole_id"))
        stored["hole"], stored["hole_name"] = hole, _codes(hole, names)
        if catalog is not None:
            key, field_name, source = catalog
            stored[field_name] = _codes(_positions(catalog_fids[source], stored.pop(key)),
                                        codes[source])
        yield from reading.pause()
        parts[attribute] = columns(**stored)
        yield from reading.pause()
    return DrillholeSet(crs=crs, vertical=vertical, collars=collars,
                        catalogs=Catalogs(**catalogs), **parts)
