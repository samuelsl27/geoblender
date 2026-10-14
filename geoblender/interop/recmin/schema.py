# SPDX-License-Identifier: GPL-3.0-or-later
"""Las tablas de una base de RecMin que lee el importador (spec 005, T15; RF-005-13,
RF-005-15; plan 005 §5.4 «RecMin», §5.6.2 y §5.6.12; ``docs/arquitectura/datos/sondeos.md``
§5).

- **Tablas conocidas** (:data:`KNOWN_TABLES`), por su nombre sin distinguir mayúsculas (el
  esquema 12, el de ``default.mdb``, las escribe en minúsculas; el 11, en mayúsculas), con su
  clase (:class:`TableKind`), sus columnas con campo en Geoblender (:data:`COLUMNS`), las que
  necesita para leerla (:data:`REQUIRED_COLUMNS`; sin ellas, :class:`RecminSchemaError`
  ``dh.recmin_columns_missing``) y la de su identificador (:data:`ID_COLUMNS`, el del
  ``external_id`` ``recmin:<TABLA>:<id>``). ``GRUPOS`` y ``FORMULAS`` no están en el esquema
  11.
- **Tablas adicionales** de litología y de muestras (D-7: RecMin no documenta sus nombres), por
  su forma: ``IDSONDEO``, ``DESDE``, ``HASTA`` e ``IDLITO`` (litología, con su esquema de
  logueo ``recmin_<tabla>``) o ``IDSONDEO``, ``DESDE``, ``HASTA`` y alguna ``ELEMENTO n``
  (muestras, no primarias).
- **Lo que no se importa**: las de RecMin que no son de sondeos (:data:`NOT_IMPORTED`:
  secciones, líneas, notas, permisos…; R-64) y las desconocidas.
- **La lista de tablas que lee el importador** (:func:`layout`, :attr:`SchemaLayout.names`), en
  un orden fijo que no depende del de la base ni de sus mayúsculas: la que hashea el lector de
  contenido ``io.recmin_mdb@1`` (una parte por tabla, plan §5.6.2), y las tablas de origen
  del informe de la importación.
- **La versión de esquema** (RF-005-15): ``ACTUALIZACION.ULTIMA`` (:func:`schema_version`); 11 y
  12 son las conocidas (:data:`KNOWN_SCHEMA_VERSIONS`). Otra, o ninguna, no se lee sin
  confirmarla (:func:`require_schema`, ``dh.recmin_schema_unknown``); confirmada, se lee lo
  que se reconoce y se avisa (:func:`version_warning`).

Las columnas llegan con el nombre que tienen en la base (las de ``interop.ports.RawTable`` o el
``schema.json`` del extractor) y se comparan sin distinguir mayúsculas. Dominio puro: Python
(ARQ-07).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from ...core.errors import GeoblenderError
from ...drillholes.model import LITHOLOGY_LOG_SET
from ..ports import RawTable

__all__ = [
    "COLUMNS",
    "ID_COLUMNS",
    "KNOWN_SCHEMA_VERSIONS",
    "KNOWN_TABLES",
    "LOG_SET_PREFIX",
    "NOT_IMPORTED",
    "REQUIRED_COLUMNS",
    "SOURCE_LABEL",
    "VERSION_FIELD",
    "RecminSchemaError",
    "SchemaLayout",
    "TableKind",
    "TableUse",
    "element_number",
    "index_tables",
    "layout",
    "log_set",
    "require_schema",
    "schema_version",
    "version_warning",
]

KNOWN_SCHEMA_VERSIONS: tuple[int, ...] = (11, 12)
"""Las versiones de esquema de RecMin que conoce Geoblender (``ACTUALIZACION.ULTIMA``)."""
SOURCE_LABEL = "Base de RecMin"
"""El objeto de los mensajes de una base entera."""
VERSION_FIELD = "ACTUALIZACION.ULTIMA"
LOG_SET_PREFIX = "recmin_"
"""El esquema de logueo de una tabla adicional de litología: ``recmin_<tabla>``."""


class TableKind(StrEnum):
    """La clase de una tabla de RecMin que lee el importador, en el orden de la lista."""

    VERSION = "version"  # ACTUALIZACION: la versión de esquema
    COLLARS = "collars"  # SONDEOS
    SURVEYS = "surveys"  # ANGULOS
    LITHOLOGY = "lithology"  # LITOLOGIA y las adicionales por su forma
    SAMPLES = "samples"  # MUESTRAS y las adicionales por su forma
    ZONE_INTERVALS = "zone_intervals"  # INTERSECCIONES
    CUTS = "cuts"  # CORTES
    LITHOLOGY_CODES = "lithology_codes"  # IDLITOLOGIA
    ELEMENTS = "elements"  # ELEMENTOS
    FORMULAS = "formulas"  # FORMULAS (elementos calculados)
    SECTORS = "sectors"  # SECTORES
    GROUPS = "groups"  # GRUPOS
    ZONES = "zones"  # ZONAS
    ROTATIONS = "rotations"  # GIROS: traslaciones o giros locales (solo se avisan)


KNOWN_TABLES: Mapping[str, TableKind] = MappingProxyType({
    "ACTUALIZACION": TableKind.VERSION,
    "SONDEOS": TableKind.COLLARS,
    "ANGULOS": TableKind.SURVEYS,
    "LITOLOGIA": TableKind.LITHOLOGY,
    "MUESTRAS": TableKind.SAMPLES,
    "INTERSECCIONES": TableKind.ZONE_INTERVALS,
    "CORTES": TableKind.CUTS,
    "IDLITOLOGIA": TableKind.LITHOLOGY_CODES,
    "ELEMENTOS": TableKind.ELEMENTS,
    "FORMULAS": TableKind.FORMULAS,
    "SECTORES": TableKind.SECTORS,
    "GRUPOS": TableKind.GROUPS,
    "ZONAS": TableKind.ZONES,
    "GIROS": TableKind.ROTATIONS,
})
"""Las tablas de RecMin que lee el importador, por su nombre en mayúsculas."""

NOT_IMPORTED: frozenset[str] = frozenset({
    "SECCIONES", "LINS", "LINSVERTICES", "NOTAS", "SECVIS", "PERMISOS", "BUSCAR", "UNIDADES",
})
"""Las tablas de RecMin que no son de sondeos o no se usan (R-64; las unidades de las leyes
son las de ``core.units``): no se leen."""

COLUMNS: Mapping[TableKind, frozenset[str]] = MappingProxyType({
    TableKind.VERSION: frozenset({"ULTIMA"}),
    TableKind.COLLARS: frozenset({
        "IDSONDEO", "SONDEO", "ESTE", "NORTE", "ELEVACION", "IDSECTOR", "IDGRUPO", "PLAN",
        "PRIORIDAD", "FECHA INI", "FECHA FIN", "CAT", "CONTROL"}),
    TableKind.SURVEYS: frozenset({"ID", "IDSONDEO", "DISTANCIA", "INCLINACION", "DIRECCION"}),
    TableKind.LITHOLOGY: frozenset({"ID", "IDSONDEO", "DESDE", "HASTA", "IDLITO"}),
    TableKind.SAMPLES: frozenset({"ID", "IDSONDEO", "DESDE", "HASTA"}),
    TableKind.ZONE_INTERVALS: frozenset({"ID", "IDSONDEO", "DESDE", "HASTA", "ANGULO",
                                         "IDZONA"}),
    TableKind.CUTS: frozenset({"ID", "IDZONA", "IDSONDEO", "DISTANCIA"}),
    TableKind.LITHOLOGY_CODES: frozenset({
        "IDLITO", "NOMBRE CORTO", "DESCRIPCION", "COLOR", "ESTILO", "DENSIDAD", "ORDEN",
        "VER"}),
    TableKind.ELEMENTS: frozenset({
        "ELEMENTO", "NOMBRE", "UNIDAD", "DECIMALES", "ORDEN", "TABLA", "CALCULO", "COLORES"}),
    TableKind.FORMULAS: frozenset({"NOMBRE", "CAMPO", "FACTOR"}),
    TableKind.SECTORS: frozenset({"IDSECTOR", "SECTOR", "DESCRIPCION"}),
    TableKind.GROUPS: frozenset({"IDGRUPO", "GRUPO", "DESCRIPCION"}),
    TableKind.ZONES: frozenset({"IDZONA", "ZONA", "DESCRIPCION", "DENSIDAD"}),
    TableKind.ROTATIONS: frozenset(),
})
"""Las columnas (en mayúsculas) que tienen campo en Geoblender; las demás van a ``extra``. En
las de muestras, además, cada ``ELEMENTO n`` (un valor por elemento). Los ángulos de
``CORTES`` (``AZIMUT``, ``INCLINACION``) no tienen campo: su semántica está sin verificar
(D-7) y van a ``extra``."""

REQUIRED_COLUMNS: Mapping[TableKind, tuple[str, ...]] = MappingProxyType({
    TableKind.VERSION: ("ULTIMA",),
    TableKind.COLLARS: ("IDSONDEO", "SONDEO", "ESTE", "NORTE", "ELEVACION"),
    TableKind.SURVEYS: ("IDSONDEO", "DISTANCIA", "INCLINACION", "DIRECCION"),
    TableKind.LITHOLOGY: ("IDSONDEO", "DESDE", "HASTA", "IDLITO"),
    TableKind.SAMPLES: ("IDSONDEO", "DESDE", "HASTA"),
    TableKind.ZONE_INTERVALS: ("IDSONDEO", "DESDE", "HASTA", "IDZONA"),
    TableKind.CUTS: ("IDSONDEO", "DISTANCIA"),
    TableKind.LITHOLOGY_CODES: ("IDLITO", "NOMBRE CORTO"),
    TableKind.ELEMENTS: ("ELEMENTO", "NOMBRE", "UNIDAD"),
    TableKind.FORMULAS: ("NOMBRE", "CAMPO", "FACTOR"),
    TableKind.SECTORS: ("IDSECTOR", "SECTOR"),
    TableKind.GROUPS: ("IDGRUPO", "GRUPO"),
    TableKind.ZONES: ("IDZONA", "ZONA"),
    TableKind.ROTATIONS: (),
})
"""Las columnas sin las que una tabla conocida no se puede leer."""

ID_COLUMNS: Mapping[TableKind, str] = MappingProxyType({
    TableKind.COLLARS: "IDSONDEO",
    TableKind.SURVEYS: "ID",
    TableKind.LITHOLOGY: "ID",
    TableKind.SAMPLES: "ID",
    TableKind.ZONE_INTERVALS: "ID",
    TableKind.CUTS: "ID",
    TableKind.LITHOLOGY_CODES: "IDLITO",
    TableKind.ELEMENTS: "ELEMENTO",
    TableKind.FORMULAS: "NOMBRE",
    TableKind.SECTORS: "IDSECTOR",
    TableKind.GROUPS: "IDGRUPO",
    TableKind.ZONES: "IDZONA",
})
"""La columna del identificador de RecMin de cada registro (``recmin:<TABLA>:<id>``)."""

_LITHOLOGY_SHAPE = frozenset({"IDSONDEO", "DESDE", "HASTA", "IDLITO"})
_SAMPLES_SHAPE = frozenset({"IDSONDEO", "DESDE", "HASTA"})
_ELEMENT = re.compile(r"ELEMENTO\s*(\d+)", re.IGNORECASE)
_ORDER = {kind: position for position, kind in enumerate(TableKind)}


class RecminSchemaError(GeoblenderError):
    """Una base de RecMin que no se lee como está: le falta una tabla o una columna que hace
    falta, o declara una versión de esquema que hay que confirmar (RF-005-15)."""


def element_number(column: str) -> int | None:
    """El número ``n`` de una columna ``ELEMENTO n`` de una tabla de muestras (sin distinguir
    mayúsculas ni espacios), o ``None`` si no lo es."""
    match = _ELEMENT.fullmatch(column.strip())
    return None if match is None else int(match.group(1))


def log_set(table: str) -> str:
    """El esquema de logueo de una tabla adicional de litología: ``recmin_<tabla>`` en
    minúsculas."""
    return f"{LOG_SET_PREFIX}{table.strip().lower()}"


@dataclass(frozen=True, slots=True)
class TableUse:
    """Una tabla que lee el importador: su nombre tal como está en la base, su clase, si es
    la principal de su clase (las adicionales de litología y de muestras, reconocidas por su
    forma, no lo son: sus muestras no son primarias) y, en las de litología, su esquema de
    logueo (``lithology`` la principal, ``recmin_<tabla>`` las adicionales)."""

    name: str
    kind: TableKind
    primary: bool = True
    log_set: str | None = None


@dataclass(frozen=True)
class SchemaLayout:
    """Las tablas de una base (:func:`layout`): las que lee el importador, en su orden
    (``tables``), las de RecMin que no se importan (``not_imported``) y las desconocidas
    (``unknown``), estas dos con su nombre de la base."""

    tables: tuple[TableUse, ...]
    not_imported: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()

    @property
    def names(self) -> tuple[str, ...]:
        """Los nombres (de la base) de las tablas que lee el importador, en su orden."""
        return tuple(use.name for use in self.tables)

    def table(self, kind: TableKind) -> TableUse | None:
        """La tabla principal de la clase ``kind``, o ``None`` si la base no la tiene."""
        for use in self.tables:
            if use.kind is kind and use.primary:
                return use
        return None

    def of_kind(self, kind: TableKind) -> tuple[TableUse, ...]:
        """Las tablas de la clase ``kind``: la principal y después las adicionales."""
        return tuple(use for use in self.tables if use.kind is kind)


def _check_names(names: Iterable[str], what: str) -> None:
    seen: dict[str, str] = {}
    for name in names:
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"el nombre de {what} es un texto no vacío, no {name!r}")
        key = name.casefold()
        if key in seen:
            raise ValueError(f"{what} «{name}» está dos veces («{seen[key]}»): una base de "
                             f"Access no distingue mayúsculas")
        seen[key] = name


def _use(name: str, columns: Sequence[str]) -> TableUse | str | None:
    """La tabla ``name`` que se lee, ``"not_imported"`` o ``None`` (desconocida)."""
    upper = {column.strip().upper() for column in columns}
    kind = KNOWN_TABLES.get(name.strip().upper())
    if kind is not None:
        missing = [column for column in REQUIRED_COLUMNS[kind] if column not in upper]
        if missing:
            raise RecminSchemaError(
                "dh.recmin_columns_missing",
                "le faltan columnas de RecMin (esquemas 11 y 12) que hacen falta para leerla: "
                "¿es una base de RecMin?",
                obj=name, field="columnas", value=missing, shown=", ".join(missing))
        return TableUse(name, kind,
                        log_set=LITHOLOGY_LOG_SET if kind is TableKind.LITHOLOGY else None)
    if name.strip().upper() in NOT_IMPORTED:
        return "not_imported"
    elements = any(element_number(column) is not None for column in columns)
    if _LITHOLOGY_SHAPE <= upper and not elements:
        return TableUse(name, TableKind.LITHOLOGY, primary=False, log_set=log_set(name))
    if _SAMPLES_SHAPE <= upper and elements and "IDLITO" not in upper:
        return TableUse(name, TableKind.SAMPLES, primary=False)
    return None


def layout(columns: Mapping[str, Sequence[str]]) -> SchemaLayout:
    """Las tablas de una base con las columnas ``columns`` (tabla → nombres de sus columnas,
    tal como están en la base): las que lee el importador en su orden fijo (por clase, la
    principal antes que las adicionales, y por nombre sin mayúsculas), las de RecMin que no
    se importan y las desconocidas. :class:`RecminSchemaError` si a una conocida le falta una
    columna que hace falta; ``ValueError`` si dos tablas o dos columnas de una tabla se llaman
    igual sin distinguir mayúsculas."""
    if not isinstance(columns, Mapping):
        raise TypeError(f"las columnas de la base son tabla → columnas, no {columns!r}")
    _check_names(columns, "la tabla")
    used: list[TableUse] = []
    not_imported: list[str] = []
    unknown: list[str] = []
    for name, names in columns.items():
        if isinstance(names, str) or not isinstance(names, Sequence):
            raise TypeError(f"las columnas de «{name}» son una lista de nombres, no {names!r}")
        _check_names(names, f"la columna de «{name}»")
        found = _use(name, names)
        if isinstance(found, TableUse):
            used.append(found)
        elif found == "not_imported":
            not_imported.append(name)
        else:
            unknown.append(name)
    used.sort(key=lambda u: (_ORDER[u.kind], not u.primary, u.name.casefold()))
    known = [u.kind for u in used if u.primary]
    if len(known) != len(set(known)):  # pragma: no cover - imposible con nombres únicos
        raise AssertionError("dos tablas principales de la misma clase")
    return SchemaLayout(tuple(used), tuple(sorted(not_imported, key=str.casefold)),
                        tuple(sorted(unknown, key=str.casefold)))


def index_tables(raw: Mapping[str, RawTable] | Iterable[RawTable]) -> dict[str, RawTable]:
    """Las tablas crudas de una base por su nombre sin mayúsculas (``casefold``); de un
    diccionario se toman sus valores. ``ValueError`` si dos se llaman igual."""
    tables = raw.values() if isinstance(raw, Mapping) else raw
    found: dict[str, RawTable] = {}
    for table in tables:
        if not isinstance(table, RawTable):
            raise TypeError(f"las tablas de la base son interop.ports.RawTable, no {table!r}")
        key = table.name.casefold()
        if key in found:
            raise ValueError(f"la tabla «{table.name}» está dos veces («{found[key].name}»)")
        found[key] = table
    return found


def _integer(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)  # int, float, numpy, Decimal
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else None


def schema_version(raw: Mapping[str, RawTable] | Iterable[RawTable]) -> int | None:
    """La versión de esquema que declara la base (``ACTUALIZACION.ULTIMA``; la mayor si hay
    varias filas), o ``None`` si no la declara (sin la tabla, sin la columna o sin valor
    entero)."""
    table = index_tables(raw).get("actualizacion")
    if table is None or table.position("ULTIMA") is None:
        return None
    versions = [v for v in map(_integer, table.values("ULTIMA")) if v is not None]
    return max(versions) if versions else None


def version_warning(version: int | None) -> str | None:
    """El aviso de una versión de esquema que no es 11 ni 12 (RF-005-15), o ``None`` si lo
    es."""
    if version in KNOWN_SCHEMA_VERSIONS:
        return None
    known = " y ".join(str(v) for v in KNOWN_SCHEMA_VERSIONS)
    said = ("no declara su versión de esquema" if version is None
            else f"declara la versión de esquema {version}")
    return (f"{SOURCE_LABEL}: la base {said} ({VERSION_FIELD}) y Geoblender conoce las de "
            f"RecMin {known}: solo se importa lo que se reconoce (sus tablas y columnas)")


def require_schema(version: int | None, *, accept: bool) -> str | None:
    """Comprueba la versión de esquema antes de leer (RF-005-15): 11 o 12, ``None``; otra (o
    ninguna) sin confirmar (``accept``), :class:`RecminSchemaError`
    ``dh.recmin_schema_unknown``; confirmada, su aviso (:func:`version_warning`)."""
    warning = version_warning(version)
    if warning is None or accept:
        return warning
    known = " y ".join(str(v) for v in KNOWN_SCHEMA_VERSIONS)
    raise RecminSchemaError(
        "dh.recmin_schema_unknown",
        f"Geoblender conoce los esquemas de RecMin {known}: confirme que quiere importar lo "
        f"que se reconozca de esta base",
        obj=SOURCE_LABEL, field=VERSION_FIELD, value=version,
        shown="sin versión" if version is None else str(version))
