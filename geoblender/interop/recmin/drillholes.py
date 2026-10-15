# SPDX-License-Identifier: GPL-3.0-or-later
"""De las tablas de una base de RecMin a sondeos (spec 005, T15; RF-005-02, RF-005-07,
RF-005-09, RF-005-10, RF-005-12, RF-005-13, RF-005-15; plan 005 §5.4 «RecMin», §5.6.2 y
§5.6.12; ``docs/arquitectura/datos/sondeos.md`` §5).

:func:`read_drillholes` lee las tablas crudas de una base (``interop.ports.RawTable``, las que
extrae el motor; :mod:`.schema` dice cuáles) y da un ``drillholes.model.DrillholeSet`` en el
CRS, el datum y los convenios declarados, sin transformar (las conversiones son de
``dh.build_base``), con su ``interop.base.ImportReport``. **Una tabla de salida por papel**
(:data:`OUTPUT_ROLES`): las bocas, las desviaciones, la litología (la principal y las
adicionales, cada una con su esquema de logueo), los análisis (los de todas las tablas de
muestras), las intersecciones, los cortes y los catálogos; los registros hijos, **enlazados
por el nombre** del sondeo (``hole_name``), no por el ``IDSONDEO`` de RecMin.

- **Identificador y campos sin equivalente** (RF-005-13): cada registro lleva su
  ``external_id`` = ``recmin:<TABLA>:<id>`` (la tabla en mayúsculas; el id, el de
  ``schema.ID_COLUMNS``) y en ``extra`` todas las columnas de su tabla sin campo en
  Geoblender (``CL NORTE``, ``COLORPRINT``, ``CONTADOR``, los ángulos de ``CORTES``…; las
  desconocidas también), con su valor: los Single, por su decimal más corto; las fechas, en
  ISO; los decimales exactos, como texto.
- **Precisión simple** (RF-005-02): un Single (``numpy.float32``, o su ``float`` exacto en una
  columna ``DBTYPE_R4``) se guarda por su decimal más corto (``drillholes.values``): 0,1 y no
  0,10000000149011612. Un Double, idéntico.
- **Bocas** (``SONDEOS``): nombre, X, Y, Z, sector y grupo (su código, por ``IDSECTOR`` e
  ``IDGRUPO``), planificado, control de leyes, prioridad, categoría y fechas (una hora que no
  es las 00:00, también en ``extra``). RecMin no guarda la profundidad total: se deduce de la
  más honda de sus estaciones y tramos, CALCULADO (``drillholes.validate.deduce_depths``;
  la avisa DH-W16). Sin tipo de sondeo.
- **Desviaciones** (``ANGULOS``): ``DIRECCION`` = 360 pasa a 0; la inclinación es la de
  RecMin (negativa hacia abajo, :data:`INCLINATION_CONVENTION`), y la referencia del azimut,
  la declarada.
- **Litología** (``LITOLOGIA`` y las adicionales por su forma, D-7): el código, por ``IDLITO``
  en ``IDLITOLOGIA``; esquema de logueo ``lithology`` o ``recmin_<tabla>``. El catálogo de
  litologías (uno en RecMin) se da en cada esquema de logueo leído.
- **Análisis** (``MUESTRAS`` y las adicionales): de ancho a largo, un registro por
  ``ELEMENTO n`` no nulo, con el nombre (``ELEMENTOS.NOMBRE``) y la unidad de su catálogo
  (:func:`element_unit`: g/t, ppm, ppb o %, o «txt», que es ``text``: sin valor y con su texto
  en ``reported_value``); ``reported_unit``, la de RecMin; muestra ``recmin:<TABLA>:<ID>``. Las
  de las tablas adicionales no son primarias (no chocan con las de ``MUESTRAS``: DH-E10,
  DH-E12). Un negativo, tal cual (DH-W08), o «<x» si se declara (RF-005-09); un texto en una
  columna de un elemento numérico, con las reglas de la declaración (``drillholes.values``).
- **Catálogos**: litologías con color (``COLOR`` en BGR de Windows → «#RRGGBB»; sin él, el
  gris; uno que no es un color, el gris y su valor en ``extra``), trama (``ESTILO``),
  densidad (con el tipo declarado), orden y leyenda (``VER``); elementos con decimales, orden,
  si se muestran (``TABLA``) y se usan (``CALCULO``) y su leyenda (``COLORES``); los
  elementos calculados de ``FORMULAS`` (su expresión literal Σ factor·campo, en la unidad de
  su primer término de ``ELEMENTOS``; sin usarse en los cálculos hasta verificar su
  semántica); sectores, grupos y zonas (con densidad).
- **Intersecciones y cortes** (D-7, literales): ``INTERSECCIONES.ANGULO`` en ``angle_deg``;
  ``CORTES`` como planos de zona (``zone_plane``, ``recmin_cortes``) con sus ángulos solo en
  ``extra``.

**Lo que no se puede leer** se rechaza con su tabla, su fila (desde 1), su columna, su valor y
un motivo que empieza por el sondeo y el tramo (o el código) (RF-005-09, RF-005-12): una fila
sin sondeo (``IDSONDEO`` vacío), un código de litología o una zona de una intersección que no
están en su catálogo, un valor que no es un número (o de una columna ``ELEMENTO n`` sin
elemento: solo ese valor), un nombre o un código vacío, o repetido en su catálogo. Lo que sí
entra y marca la validación: un sondeo que no está en ``SONDEOS`` (con el nombre
``recmin:SONDEOS:<id>``, DH-E04), dos con el mismo nombre (DH-E01), los rangos imposibles. Un
sector, un grupo o una zona de un corte que no están en su catálogo: sin él, con el
identificador en ``extra`` y un aviso.

**Antes de leer** (RF-005-07, RF-005-15): la versión de esquema (otra que 11 y 12, o ninguna,
solo con ``accept_schema``; ``schema.require_schema``) y las declaraciones (:func:`needs`: el
CRS y el datum vertical; la referencia del azimut si hay desviaciones; la unidad de un elemento
cuya ``UNIDAD`` no es de ley). La inclinación no se declara (es la de RecMin), ni «todos
verticales»; los centinelas y el separador decimal solo valen para los textos.

Las tablas crudas nunca se modifican. Dominio puro: Python y numpy (ARQ-07).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import math
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from types import MappingProxyType
from typing import Any

import numpy as np

from ...drillholes.model import (
    DEFAULT_COLOR,
    LITHOLOGY_LOG_SET,
    AssayColumns,
    CatalogEntry,
    Catalogs,
    CollarColumns,
    DrillholeSet,
    Element,
    InclinationConvention,
    IntervalColumns,
    LithologyCode,
    OrientationSource,
    Rejection,
    SourceDeclaration,
    StructureColumns,
    StructureType,
    SurveyColumns,
    ZoneColumns,
    name_key,
)
from ...drillholes.validate import deduce_depths
from ...drillholes.values import FLAG_CODES, DetectionFlag, from_single_column, parse_column
from ..base import (
    ImportReport,
    Needs,
    TableCounts,
    concat_columns,
    duplicate_names,
    grade_unit,
    link_columns,
    new_codes,
    object_array,
    record_columns,
    require_declarations,
    spanish_list,
)
from ..ports import DBTYPE_R4, RawColumn, RawTable
from .schema import (
    COLUMNS,
    ID_COLUMNS,
    KNOWN_SCHEMA_VERSIONS,
    SOURCE_LABEL,
    SchemaLayout,
    TableKind,
    TableUse,
    element_number,
    index_tables,
    layout,
    require_collars,
    require_schema,
    schema_version,
)

__all__ = [
    "EMPTY_FIELDS_WARNING",
    "EXTERNAL_PREFIX",
    "INCLINATION_CONVENTION",
    "KNOWN_SCHEMA_VERSIONS",
    "OUTPUT_ROLES",
    "TEXT_UNIT",
    "element_unit",
    "external_table",
    "hole_rows",
    "needs",
    "read_drillholes",
]

EXTERNAL_PREFIX = "recmin:"
"""El principio del ``external_id`` de un registro de RecMin: ``recmin:<TABLA>:<id>``."""

INCLINATION_CONVENTION = InclinationConvention.NEGATIVE_DOWN
"""El convenio de la inclinación de RecMin (desde la horizontal, negativa hacia abajo, el de
Geoblender: ADR-0005). No se declara: la validación avisa si parece invertido (DH-W14)."""
TEXT_UNIT = "text"
"""La unidad de un elemento de texto de RecMin («txt»): sin valor, con su texto."""
OUTPUT_ROLES: Mapping[str, tuple[TableKind, ...]] = MappingProxyType({
    "collar": (TableKind.COLLARS,),
    "survey": (TableKind.SURVEYS,),
    "lithology": (TableKind.LITHOLOGY,),
    "assay": (TableKind.SAMPLES,),
    "zone_interval": (TableKind.ZONE_INTERVALS,),
    "structure": (TableKind.CUTS,),
    "catalog": (TableKind.LITHOLOGY_CODES, TableKind.ELEMENTS, TableKind.FORMULAS,
                TableKind.SECTORS, TableKind.GROUPS, TableKind.ZONES),
})
"""Las tablas de salida, una por papel (las de lo importado, ``dh_src_<papel>``; plan
§5.6.1), y las clases de tablas de RecMin que las dan. En el ``DrillholeSet``: ``collars``,
``surveys``, ``lithology``, ``assays``, ``zones``, ``structures`` y ``catalogs``."""
EMPTY_FIELDS_WARNING = (
    f"{SOURCE_LABEL}: RecMin no guarda la profundidad total de los sondeos, que se deduce de "
    f"su medida más honda (CALCULADO, avisada con DH-W16), ni el tipo de sondeo, el "
    f"laboratorio, el método, el lote o el tipo de control de calidad de las muestras, que "
    f"quedan vacíos o con su valor por defecto"
)
"""El aviso de lo que RecMin no tiene y Geoblender sí (``sondeos.md`` §5)."""

_TEXT_UNITS = frozenset({"txt", "text"})
_SINGLE_KINDS = (float, np.float32)
_NUMBERS = (int, float, Decimal, np.integer, np.floating)
_OK = FLAG_CODES[DetectionFlag.OK]
_BELOW = FLAG_CODES[DetectionFlag.BELOW_DL]
_CATALOG_KINDS = frozenset(OUTPUT_ROLES["catalog"])
_AT_DEPTH = frozenset({TableKind.SURVEYS, TableKind.CUTS})
_MAX_COLOR = 0xFFFFFF
_EXACT_INT = 2.0**53
_NOT_NUMBER = "no es un número"


def element_unit(text: object) -> str | None:
    """La unidad de Geoblender de una ``UNIDAD`` de ``ELEMENTOS``: una de ley (g/t, ppm, ppb,
    %; sin distinguir mayúsculas ni espacios exteriores), :data:`TEXT_UNIT` para «txt», o
    ``None`` si no es ninguna (hay que declararla, RF-005-07)."""
    if not isinstance(text, str):
        return None
    if text.strip().casefold() in _TEXT_UNITS:
        return TEXT_UNIT
    return grade_unit(text)


def external_table(external_id: object) -> str | None:
    """La tabla de RecMin de un registro por su ``external_id`` (``recmin:<TABLA>:<id>``, la
    tabla en mayúsculas); ``None`` si no es el de un registro de RecMin."""
    if not isinstance(external_id, str) or not external_id.startswith(EXTERNAL_PREFIX):
        return None
    table, sep, _ident = external_id.removeprefix(EXTERNAL_PREFIX).partition(":")
    return table if sep and table else None


_HOLE_TABLES = ("collars", "surveys", "lithology", "assays", "zones", "structures")


def hole_rows(dset: DrillholeSet, holes: Iterable[str],
              tables: Iterable[str] = ()) -> dict[str, dict[str, int]]:
    """Los registros de cada sondeo de ``holes`` (sin distinguir mayúsculas ni espacios) en lo
    leído de una base de RecMin (``dset``), por la tabla de RecMin de la que vienen (su
    ``external_id``; :func:`external_table`): ``{tabla: {sondeo: registros}}``, con el sondeo
    como lo escribe la base y la tabla como la nombra ``tables`` (las de
    ``ImportReport.per_table``) si está, sin distinguir mayúsculas. Son los que quita conservar
    un sondeo que ya está en el proyecto, o los que sustituye (RF-005-11, RF-005-12): un valor
    de un análisis es un registro, como en los recuentos del informe."""
    wanted = {name_key(hole) for hole in holes}
    named = {table.casefold(): table for table in tables}
    found: dict[str, dict[str, int]] = {}
    if not wanted:
        return found
    for attribute in _HOLE_TABLES:
        columns = getattr(dset, attribute)
        field = "name" if attribute == "collars" else "hole_name"
        for hole, external in zip(getattr(columns, field).tolist(),
                                  columns.external_id.tolist(), strict=True):
            table = external_table(external)
            if hole is None or table is None or name_key(hole) not in wanted:
                continue
            per = found.setdefault(named.get(table.casefold(), table), {})
            per[hole] = per.get(hole, 0) + 1
    return found


# --- Valores crudos ------------------------------------------------------------------------------


def _decimal_text(value: float) -> str:
    return np.format_float_positional(value, unique=True, trim="-")


def _text_of(value: object, single: bool = False) -> str | None:
    """Un valor crudo como texto (rechazos, identificadores, textos): un número, por su decimal
    más corto (el de su Single si lo es); una fecha, en ISO."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bool | np.bool_):
        return "sí" if value else "no"
    if isinstance(value, np.float32) or (single and isinstance(value, float)):
        return _decimal_text(np.float32(value))
    if isinstance(value, float | np.floating):
        return _decimal_text(float(value))
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    return str(value)


def _shown(value: float) -> str:
    """Un número como en los mensajes: el decimal más corto, con coma."""
    return _decimal_text(value).replace(".", ",")


def _floats(values: Sequence[object], single_column: bool) -> tuple[np.ndarray, list[int]]:
    """Los números de una columna en float64 (``None``, NaN) y las filas que no lo son; un
    Single, por su decimal más corto (RF-005-02)."""
    count = len(values)
    found = np.full(count, math.nan)
    single = np.zeros(count, dtype=bool)
    bad: list[int] = []
    for row, value in enumerate(values):
        if value is None:
            continue
        if isinstance(value, bool | np.bool_) or not isinstance(value, _NUMBERS):
            bad.append(row)
            continue
        if isinstance(value, np.float32) or (single_column and isinstance(value, float)):
            single[row] = True
        found[row] = float(value)
    if single.any():
        found[single] = from_single_column(found[single])
    return found, bad


def _integer(value: object) -> int | None | str:
    """Un entero de un valor crudo (``None``, ``None``); ``"bad"`` si no lo es."""
    if value is None:
        return None
    if isinstance(value, bool | np.bool_) or not isinstance(value, _NUMBERS):
        return "bad"
    if isinstance(value, int | np.integer):
        return int(value)
    number = float(value)
    if number.is_integer() and abs(number) < _EXACT_INT:
        return int(number)
    return "bad"


def _extra_value(value: object, single: bool) -> object:
    """Un valor crudo en ``extra`` (que se guarda en JSON): Single por su decimal más corto,
    fechas en ISO, decimales exactos como texto, binarios vacíos."""
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool | np.bool_):
        return bool(value)
    if isinstance(value, int | np.integer):
        return int(value)
    if isinstance(value, np.float32) or (single and isinstance(value, float)):
        return float(from_single_column(np.array([value], dtype=np.float64))[0])
    if isinstance(value, float | np.floating):
        return float(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    if isinstance(value, bytes | bytearray | memoryview):
        return None
    return str(value)


def _color(value: object) -> tuple[str, bool]:
    """El «#RRGGBB» de un ``COLOR`` de Windows (BGR: R = c & 0xFF, G = (c >> 8) & 0xFF,
    B = (c >> 16) & 0xFF) y si era un color; sin él o si no lo es, el gris por defecto."""
    if value is None:
        return DEFAULT_COLOR, True
    number = _integer(value)
    if not isinstance(number, int) or not 0 <= number <= _MAX_COLOR:
        return DEFAULT_COLOR, False
    red, green, blue = number & 0xFF, (number >> 8) & 0xFF, (number >> 16) & 0xFF
    return f"#{red:02X}{green:02X}{blue:02X}", True


# --- Una tabla mientras se lee ------------------------------------------------------------------


class _Source:
    """Una tabla cruda que lee el importador: sus valores por columna, lo que se rechaza de
    cada fila y lo que se cuenta."""

    def __init__(self, table: RawTable, use: TableUse) -> None:
        self.table = table
        self.use = use
        self.kind = use.kind
        self.name = table.name
        self.count = len(table.rows)
        self.ok = np.ones(self.count, dtype=bool)
        self.problems: list[tuple[int, int, str, str | None, str]] = []
        self.label: list[str | None] = [None] * self.count
        self.span: tuple[np.ndarray, np.ndarray] | None = None
        self.imported = 0
        self.rejected = 0
        mapped = COLUMNS[self.kind]
        self.extra_columns = [
            (position, column) for position, column in enumerate(table.columns)
            if column.name.strip().upper() not in mapped
            and not (self.kind is TableKind.SAMPLES and element_number(column.name) is not None)
        ]
        ident = ID_COLUMNS.get(self.kind)
        self.ids = self.values(ident) if ident is not None else [None] * self.count
        self.ident_single = ident is not None and self._single(ident)

    # Columnas

    def column(self, name: str) -> RawColumn | None:
        position = self.table.position(name)
        return None if position is None else self.table.columns[position]

    def _single(self, name: str) -> bool:
        column = self.column(name)
        return column is not None and column.type == DBTYPE_R4

    def values(self, name: str) -> list[object]:
        """Los valores de la columna ``name`` (sin ella, todos ``None``)."""
        if self.table.position(name) is None:
            return [None] * self.count
        return self.table.values(name)

    # Rechazos

    def fail(self, row: int, name: str, value: object, reason: str, *,
             record: bool = True) -> None:
        """Rechaza el registro de la fila ``row`` (o, sin ``record``, solo ese valor) por la
        columna ``name``."""
        if record:
            self.ok[row] = False
        column = self.column(name)
        position = self.table.position(name)
        shown = _text_of(value, column is not None and column.type == DBTYPE_R4)
        if shown is not None and not shown.strip():
            shown = None
        self.problems.append((row, -1 if position is None else position,
                              name if column is None else column.name, shown, reason))

    def rejections(self) -> list[Rejection]:
        """Los rechazos por fila y columna, con el sondeo y el tramo (o el código) delante del
        motivo."""
        return [Rejection(self.name, row + 1, column, value, self._where(row, reason))
                for row, _, column, value, reason in sorted(self.problems,
                                                            key=lambda p: (p[0], p[1]))]

    def _where(self, row: int, reason: str) -> str:
        label = self.label[row]
        if label is None:
            return reason
        if self.kind in _CATALOG_KINDS:
            return f"código «{label}»: {reason}"
        place = f"sondeo «{label}»"
        if self.span is not None:
            start, end = float(self.span[0][row]), float(self.span[1][row])
            if self.kind in _AT_DEPTH and math.isfinite(start):
                place += f", a {_shown(start)} m"
            elif self.kind not in _AT_DEPTH and math.isfinite(start) and math.isfinite(end):
                place += f", de {_shown(start)} a {_shown(end)} m"
        return f"{place}: {reason}"

    # Valores

    def floats(self, name: str) -> np.ndarray:
        """Un número (float64; vacío o que no lo es, NaN y su fila rechazada)."""
        values = self.values(name)
        found, bad = _floats(values, self._single(name))
        for row in bad:
            self.fail(row, name, values[row], _NOT_NUMBER)
        return found

    def ints(self, name: str, default: int | None) -> list[int | None]:
        """Un entero (vacío, ``default``)."""
        found: list[int | None] = []
        for row, value in enumerate(self.values(name)):
            number = _integer(value)
            if number == "bad":
                self.fail(row, name, value, "no es un número entero")
                number = default
            found.append(default if number is None else number)
        return found

    def bools(self, name: str, default: bool) -> np.ndarray:
        """Sí o no (vacío, ``default``)."""
        found = np.full(self.count, default, dtype=bool)
        for row, value in enumerate(self.values(name)):
            if value is None:
                continue
            if isinstance(value, bool | np.bool_ | int | np.integer):
                found[row] = bool(value)
            else:
                self.fail(row, name, value, "no es sí ni no")
        return found

    def texts(self, name: str) -> list[str | None]:
        """Un texto tal como está (un número, por su decimal más corto)."""
        single = self._single(name)
        return [_text_of(value, single) for value in self.values(name)]

    def keys(self, name: str, missing: str) -> list[str | None]:
        """Un nombre o un código obligatorio: tal como está; vacío, la fila rechazada."""
        found = self.texts(name)
        for row, text in enumerate(found):
            if text is None or not text.strip():
                found[row] = None
                self.fail(row, name, None, missing)
        return found

    def dates(self, name: str) -> tuple[list[dt.date | None], list[str | None]]:
        """Un día (vacío, ``None``) y, si tenía una hora que no es las 00:00, la fecha entera en
        ISO (para ``extra``)."""
        days: list[dt.date | None] = []
        moments: list[str | None] = []
        for row, value in enumerate(self.values(name)):
            day, moment = None, None
            if isinstance(value, dt.datetime):
                day = value.date()
                if value.time() != dt.time():
                    moment = value.isoformat()
            elif isinstance(value, dt.date):
                day = value
            elif value is not None:
                self.fail(row, name, value, "no es una fecha")
            days.append(day)
            moments.append(moment)
        return days, moments

    def repeated(self, codes: Sequence[str | None], name: str) -> None:
        """Rechaza la fila que repite el código de otra anterior (sin distinguir mayúsculas ni
        espacios exteriores)."""
        first: dict[str, int] = {}
        for row in np.flatnonzero(self.ok).tolist():
            key = name_key(codes[row])
            if key in first:
                self.fail(row, name, codes[row], f"repite el código «{codes[first[key]]}» de la "
                                                 f"fila {first[key] + 1}")
            else:
                first[key] = row

    # Identificador y extra

    def external_id(self, row: int) -> str | None:
        """``recmin:<TABLA>:<id>`` del registro de la fila ``row`` (sin id, ``None``)."""
        ident = _text_of(self.ids[row], self.ident_single)
        if ident is None or not ident.strip():
            return None
        return f"{EXTERNAL_PREFIX}{self.name.upper()}:{ident}"

    def extra(self, row: int, **more: object) -> Mapping[str, Any]:
        """Las columnas sin campo de la fila ``row`` (y ``more``), para ``extra``."""
        values = self.table.rows[row]
        found = {column.name: _extra_value(values[position], column.type == DBTYPE_R4)
                 for position, column in self.extra_columns}
        found.update(more)
        return MappingProxyType(found)

    def counts(self, duplicated: int = 0) -> TableCounts:
        return TableCounts(read=self.count, imported=self.imported, rejected=self.rejected,
                           duplicated=duplicated)


# --- La base entera ----------------------------------------------------------------------------


def _check_decl(decl: object) -> SourceDeclaration:
    if not isinstance(decl, SourceDeclaration):
        raise TypeError(f"la declaración es un SourceDeclaration, no {decl!r}")
    if decl.inclination_convention not in (None, INCLINATION_CONVENTION):
        raise ValueError(f"la inclinación de RecMin es negativa hacia abajo "
                         f"({INCLINATION_CONVENTION}): no se declara otra "
                         f"({decl.inclination_convention})")
    if decl.all_vertical:
        raise ValueError("«todos verticales» no se declara para una base de RecMin: sus "
                         "desviaciones son las de ANGULOS")
    return decl


def _layout(tables: Mapping[str, RawTable]) -> SchemaLayout:
    return layout({table.name: [column.name for column in table.columns]
                   for table in tables.values()})


def _needs(tables: Mapping[str, RawTable], found: SchemaLayout) -> Needs:
    surveys = found.table(TableKind.SURVEYS)
    azimuth = surveys is not None and bool(tables[surveys.name.casefold()].rows)
    unknown: list[str] = []
    elements = found.table(TableKind.ELEMENTS)
    if elements is not None:
        table = tables[elements.name.casefold()]
        units = table.values("UNIDAD")
        for name, unit in zip(table.values("NOMBRE"), units, strict=True):
            code = _text_of(name)
            if code is not None and code.strip() and element_unit(unit) is None:
                unknown.append(code)
    return Needs(crs=True, vertical=True, azimuth=azimuth, elements=tuple(unknown))


def needs(raw: Mapping[str, RawTable] | Iterable[RawTable]) -> Needs:
    """Lo que hay que declarar para leer la base ``raw`` (RF-005-07): siempre el CRS y el datum
    vertical; la referencia del azimut (y, si es magnético, la declinación) si ``ANGULOS``
    tiene filas; la unidad de cada elemento cuya ``UNIDAD`` no es de ley ni «txt»."""
    tables = index_tables(raw)
    return _needs(tables, _layout(tables))


class _Reader:
    """Una base mientras se lee: sus tablas (en el orden de la lista), los catálogos ya
    leídos, los sondeos por su ``IDSONDEO`` y los avisos."""

    def __init__(self, tables: Mapping[str, RawTable], found: SchemaLayout,
                 decl: SourceDeclaration) -> None:
        self.layout = found
        self.decl = decl
        self.sources = [_Source(tables[use.name.casefold()], use) for use in found.tables]
        self.warnings: list[str] = []
        self.unresolved: dict[tuple[str, str, str, str], list[str]] = {}
        self.hole_names: dict[object, str] = {}
        self.collar_table = "SONDEOS"
        self.lithology_codes: dict[object, str] = {}
        self.elements: dict[int, tuple[str, str, str | None]] = {}
        self.ids: dict[TableKind, dict[object, str]] = {}

    def of_kind(self, kind: TableKind) -> list[_Source]:
        return [source for source in self.sources if source.kind is kind]

    def main(self, kind: TableKind) -> _Source | None:
        for source in self.sources:
            if source.kind is kind and source.use.primary:
                return source
        return None

    def catalog_name(self, kind: TableKind, default: str) -> str:
        source = self.main(kind)
        return default if source is None else source.name

    def note_unresolved(self, source: _Source, column: str, ident: object, catalog: str,
                        what: str, label: str | None) -> None:
        key = (source.name, column, _text_of(ident) or "", f"{catalog}\x00{what}")
        self.unresolved.setdefault(key, []).append(label or "?")

    # Catálogos

    def read_elements(self) -> list[Element]:
        source = self.main(TableKind.ELEMENTS)
        if source is None:
            return []
        names = source.keys("NOMBRE", "falta el nombre del elemento (NOMBRE)")
        source.label = names
        numbers = source.ints("ELEMENTO", None)
        units = source.texts("UNIDAD")
        decimals = source.ints("DECIMALES", 2)
        order = source.ints("ORDEN", 0)
        shown, used = source.bools("TABLA", True), source.bools("CALCULO", True)
        legends = source.texts("COLORES")
        source.repeated(names, "NOMBRE")
        found = []
        for row in np.flatnonzero(source.ok).tolist():
            code = names[row]
            unit = element_unit(units[row])
            reported = units[row]
            if unit is None:  # declarada (require_declarations)
                reported = reported if reported is not None and reported.strip() else (
                    self.decl.unit_of(code))
                unit = grade_unit(self.decl.unit_of(code))
            found.append(Element(code, unit, decimals=decimals[row], sort_order=order[row],
                                 show_in_tables=bool(shown[row]), use_in_calc=bool(used[row]),
                                 color_legend=legends[row],
                                 external_id=source.external_id(row),
                                 extra=source.extra(row)))
            number = numbers[row]
            if number is not None and number not in self.elements:
                self.elements[number] = (code, unit, reported)
        source.imported = len(found)
        source.rejected = source.count - len(found)
        return found

    def read_formulas(self, elements: list[Element]) -> list[Element]:
        """Los elementos calculados (FORMULAS): Σ FACTOR·CAMPO por NOMBRE, literal; uno que
        se llama como un elemento de ELEMENTOS le da su expresión."""
        source = self.main(TableKind.FORMULAS)
        if source is None:
            return elements
        names = source.keys("NOMBRE", "falta el nombre del elemento calculado (NOMBRE)")
        source.label = names
        fields = source.keys("CAMPO", "falta el elemento (CAMPO)")
        factors = source.floats("FACTOR")
        groups: dict[str, list[int]] = {}
        for row in np.flatnonzero(source.ok).tolist():
            if math.isnan(factors[row]):
                source.fail(row, "FACTOR", None, "falta el factor (FACTOR)")
                continue
            groups.setdefault(name_key(names[row]), []).append(row)
        known = {name_key(element.code): element for element in elements}
        found = list(elements)
        produced = 0
        for rows in groups.values():
            units = [known[name_key(fields[k])].unit for k in rows
                     if name_key(fields[k]) in known]
            if not units:
                for k in rows:
                    source.fail(k, "CAMPO", fields[k], "ninguno de sus CAMPO es un elemento "
                                                       "de ELEMENTOS")
                continue
            expression = " + ".join(f"{_decimal_text(factors[k])}*{fields[k]}" for k in rows)
            terms = [dict(source.extra(k), CAMPO=fields[k], FACTOR=float(factors[k]))
                     for k in rows]
            code = names[rows[0]]
            existing = known.get(name_key(code))
            if existing is not None:
                position = found.index(existing)
                found[position] = dataclasses.replace(
                    existing, expression=expression, extra={**existing.extra, "FORMULAS": terms})
            else:
                found.append(Element(code, units[0], expression=expression, use_in_calc=False,
                                     external_id=source.external_id(rows[0]),
                                     extra={"FORMULAS": terms}))
            produced += 1
        source.imported = produced
        source.rejected = int(np.count_nonzero(~source.ok))
        return found

    def read_lithology_codes(self) -> list[LithologyCode]:
        source = self.main(TableKind.LITHOLOGY_CODES)
        if source is None:
            return []
        codes = source.keys("NOMBRE CORTO", "falta el código (NOMBRE CORTO)")
        source.label = codes
        descriptions, patterns = source.texts("DESCRIPCION"), source.texts("ESTILO")
        colors = source.values("COLOR")
        density = source.floats("DENSIDAD")
        order = source.ints("ORDEN", 0)
        legend = source.bools("VER", True)
        source.repeated(codes, "NOMBRE CORTO")
        kind = self.decl.density_kind
        found = []
        for row in np.flatnonzero(source.ok).tolist():
            color, valid = _color(colors[row])
            more = {} if valid else {source.column("COLOR").name: _extra_value(colors[row],
                                                                               False)}
            found.append(LithologyCode(
                codes[row], log_set=LITHOLOGY_LOG_SET, description=descriptions[row],
                color=color, pattern=patterns[row],
                density=None if math.isnan(density[row]) else float(density[row]),
                density_kind=None if math.isnan(density[row]) else kind,
                sort_order=order[row], show_in_legend=bool(legend[row]),
                external_id=source.external_id(row), extra=source.extra(row, **more)))
            self.lithology_codes.setdefault(source.ids[row], codes[row])
        source.imported = len(found)
        source.rejected = source.count - len(found)
        return found

    def read_entries(self, kind: TableKind, code_column: str) -> list[CatalogEntry]:
        """Sectores, grupos o zonas (estas, con su densidad)."""
        source = self.main(kind)
        self.ids[kind] = {}
        if source is None:
            return []
        codes = source.keys(code_column, f"falta el código ({code_column})")
        source.label = codes
        descriptions = source.texts("DESCRIPCION")
        density = (source.floats("DENSIDAD") if kind is TableKind.ZONES
                   else np.full(source.count, math.nan))
        source.repeated(codes, code_column)
        found = []
        for row in np.flatnonzero(source.ok).tolist():
            measured = not math.isnan(density[row])
            found.append(CatalogEntry(
                codes[row], description=descriptions[row],
                density=float(density[row]) if measured else None,
                density_kind=self.decl.density_kind if measured else None,
                external_id=source.external_id(row), extra=source.extra(row)))
            self.ids[kind].setdefault(source.ids[row], codes[row])
        source.imported = len(found)
        source.rejected = source.count - len(found)
        return found

    # Bocas

    def read_collars(self) -> CollarColumns:
        source = self.main(TableKind.COLLARS)
        assert source is not None  # lo comprueba read_drillholes
        self.collar_table = source.name.upper()
        names = source.keys("SONDEO", "falta el nombre del sondeo (SONDEO)")
        source.label = names
        x, y, z = source.floats("ESTE"), source.floats("NORTE"), source.floats("ELEVACION")
        planned, control = source.bools("PLAN", False), source.bools("CONTROL", False)
        priority, category = source.ints("PRIORIDAD", None), source.ints("CAT", None)
        start, start_at = source.dates("FECHA INI")
        end, end_at = source.dates("FECHA FIN")
        references = {}
        for kind, column, what in ((TableKind.SECTORS, "IDSECTOR", "sector"),
                                   (TableKind.GROUPS, "IDGRUPO", "grupo")):
            references[kind] = (column, what, source.values(column))
        keep = np.flatnonzero(source.ok).tolist()
        codes: dict[TableKind, list[str | None]] = {kind: [] for kind in references}
        extras = []
        for row in keep:
            more: dict[str, object] = {}
            for kind, (column, what, values) in references.items():
                code = None
                if values[row] is not None:
                    code = self.ids[kind].get(values[row])
                    if code is None:
                        name = source.column(column).name
                        more[name] = _extra_value(values[row], False)
                        self.note_unresolved(source, name, values[row], self.catalog_name(
                            kind, "SECTORES" if kind is TableKind.SECTORS else "GRUPOS"),
                            what, names[row])
                codes[kind].append(code)
            for column, moment in (("FECHA INI", start_at[row]), ("FECHA FIN", end_at[row])):
                if moment is not None:
                    more[source.column(column).name] = moment
            extras.append(source.extra(row, **more))
            self.hole_names.setdefault(source.ids[row], names[row])
        index = np.array(keep, dtype=np.int64)
        source.imported = len(keep)
        source.rejected = source.count - len(keep)
        return record_columns(
            CollarColumns, len(keep), name=object_array([names[k] for k in keep]),
            x=x[index], y=y[index], z=z[index], depth=np.full(len(keep), math.nan),
            planned=planned[index], grade_control=control[index],
            category=object_array([category[k] for k in keep]),
            priority=object_array([priority[k] for k in keep]),
            sector=object_array(codes[TableKind.SECTORS]),
            group=object_array(codes[TableKind.GROUPS]),
            start_date=object_array([start[k] for k in keep]),
            end_date=object_array([end[k] for k in keep]),
            external_id=object_array([source.external_id(k) for k in keep]),
            extra=object_array(extras))

    # Tablas hijas

    def holes(self, source: _Source) -> list[str | None]:
        """El nombre del sondeo de cada fila, por su ``IDSONDEO``; uno que no está en SONDEOS,
        ``recmin:SONDEOS:<id>`` (DH-E04); sin ``IDSONDEO``, la fila rechazada."""
        found: list[str | None] = []
        for row, ident in enumerate(source.values("IDSONDEO")):
            if ident is None:
                source.fail(row, "IDSONDEO", None, "falta el sondeo (IDSONDEO vacío)")
                found.append(None)
                continue
            name = self.hole_names.get(ident)
            found.append(name if name is not None
                         else f"recmin:{self.collar_table}:{_text_of(ident)}")
        source.label = found
        return found

    def span(self, source: _Source, start: str, end: str | None = None
             ) -> tuple[np.ndarray, np.ndarray]:
        first = source.floats(start)
        second = first if end is None else source.floats(end)
        source.span = (first, second)
        return first, second

    def code_of(self, source: _Source, column: str, ids: Mapping[object, str],
                catalog: str, row: int, value: object) -> str | None:
        """El código de catálogo de ``value`` (``column`` de la fila ``row``); sin él, la fila
        rechazada."""
        if value is None:
            source.fail(row, column, None, f"falta el código ({column} vacío)")
            return None
        code = ids.get(value)
        if code is None:
            source.fail(row, column, value, f"{column} {_text_of(value)} no está en {catalog}")
        return code

    def finish(self, source: _Source, keep: list[int]) -> tuple[np.ndarray, np.ndarray]:
        """Los ``external_id`` y ``extra`` de las filas ``keep`` (y sus recuentos)."""
        source.imported = len(keep)
        source.rejected = source.count - len(keep)
        return (object_array([source.external_id(k) for k in keep]),
                object_array([source.extra(k) for k in keep]))

    def read_surveys(self) -> SurveyColumns:
        parts = []
        for source in self.of_kind(TableKind.SURVEYS):
            holes = self.holes(source)
            depth, _ = self.span(source, "DISTANCIA")
            inclination = source.floats("INCLINACION")
            azimuth = source.floats("DIRECCION")
            azimuth[azimuth == 360.0] = 0.0  # el mismo norte (plan §5.4)
            keep = np.flatnonzero(source.ok).tolist()
            external, extra = self.finish(source, keep)
            parts.append(record_columns(
                SurveyColumns, len(keep), hole_name=object_array([holes[k] for k in keep]),
                depth=depth[keep], azimuth=azimuth[keep], inclination=inclination[keep],
                external_id=external, extra=extra))
        return concat_columns(SurveyColumns, parts)

    def read_lithology(self) -> IntervalColumns:
        catalog = self.catalog_name(TableKind.LITHOLOGY_CODES, "IDLITOLOGIA")
        parts = []
        for source in self.of_kind(TableKind.LITHOLOGY):
            holes = self.holes(source)
            start, end = self.span(source, "DESDE", "HASTA")
            codes = [self.code_of(source, "IDLITO", self.lithology_codes, catalog, row, value)
                     for row, value in enumerate(source.values("IDLITO"))]
            keep = np.flatnonzero(source.ok).tolist()
            external, extra = self.finish(source, keep)
            parts.append(record_columns(
                IntervalColumns, len(keep), hole_name=object_array([holes[k] for k in keep]),
                from_m=start[keep], to_m=end[keep], code=object_array([codes[k] for k in keep]),
                log_set=object_array([source.use.log_set] * len(keep)),
                external_id=external, extra=extra))
        return concat_columns(IntervalColumns, parts)

    def read_assays(self) -> AssayColumns:
        parts = [self._samples(source) for source in self.of_kind(TableKind.SAMPLES)]
        return concat_columns(AssayColumns, parts)

    def _samples(self, source: _Source) -> AssayColumns:
        """Una tabla de muestras de ancho a largo: un registro por ``ELEMENTO n`` no nulo."""
        holes = self.holes(source)
        start, end = self.span(source, "DESDE", "HASTA")
        columns = [(column, number) for column in source.table.columns
                   if (number := element_number(column.name)) is not None]
        count, width = source.count, len(columns)
        values = np.full((count, width), math.nan)
        flags = np.full((count, width), _OK, dtype=np.int8)
        reported = np.full((count, width), None, dtype=object)
        present = np.zeros((count, width), dtype=bool)
        valid = np.zeros((count, width), dtype=bool)
        codes, units, reported_units = [], [], []
        catalog = self.catalog_name(TableKind.ELEMENTS, "ELEMENTOS")
        for k, (column, number) in enumerate(columns):
            raw = source.values(column.name)
            present[:, k] = [v is not None and not (isinstance(v, str) and not v.strip())
                             for v in raw]
            element = self.elements.get(number)
            code, unit, unit_text = element if element is not None else (None, None, None)
            codes.append(code)
            units.append(unit)
            reported_units.append(unit_text)
            rows = np.flatnonzero(present[:, k]).tolist()
            if element is None:
                for row in rows:
                    source.fail(row, column.name, raw[row], f"la columna «{column.name}» no "
                                f"tiene elemento en {catalog}: su valor no se importa",
                                record=False)
                continue
            single = column.type == DBTYPE_R4
            if unit == TEXT_UNIT:
                for row in rows:
                    reported[row, k] = _text_of(raw[row], single)
                    valid[row, k] = True
                continue
            self._numbers(source, column, raw, rows, k, values, flags, reported, valid)
        chosen = valid & source.ok[:, None]
        rows, picked = np.nonzero(chosen)
        source.imported = int(rows.size)
        source.rejected = int(np.count_nonzero(present)) - int(rows.size)
        external = object_array([source.external_id(k) for k in range(count)])
        extra = object_array([source.extra(k) for k in range(count)])
        return record_columns(
            AssayColumns, int(rows.size), hole_name=object_array(holes)[rows],
            from_m=start[rows], to_m=end[rows], element=object_array(codes)[picked],
            value=values[rows, picked], unit=object_array(units)[picked],
            detection_flag=flags[rows, picked], reported_value=reported[rows, picked],
            reported_unit=object_array(reported_units)[picked], sample_id=external[rows],
            is_primary=np.full(rows.size, source.use.primary), external_id=external[rows],
            extra=extra[rows])

    def _numbers(self, source: _Source, column: RawColumn, raw: list[object], rows: list[int],
                 k: int, values: np.ndarray, flags: np.ndarray, reported: np.ndarray,
                 valid: np.ndarray) -> None:
        """Los valores de un elemento numérico: los números (un Single, por su decimal más
        corto; un negativo, «<x» si se declara) y los textos con las reglas declaradas."""
        rules = self.decl.value_rules
        texts = [row for row in rows if isinstance(raw[row], str)]
        numbers = [row for row in rows if not isinstance(raw[row], str)]
        found, bad = _floats([raw[row] for row in numbers], column.type == DBTYPE_R4)
        bad_rows = {numbers[i] for i in bad}
        for row in sorted(bad_rows):
            source.fail(row, column.name, raw[row], _NOT_NUMBER, record=False)
        for i, row in enumerate(numbers):
            if row in bad_rows:
                continue
            value = float(found[i])
            reported[row, k] = _decimal_text(value)
            if rules.negative_is_below_dl and value < 0:
                values[row, k], flags[row, k] = -value, _BELOW
            else:
                values[row, k] = value
            valid[row, k] = True
        if texts:
            parsed = parse_column([raw[row] for row in texts], rules)
            rejected = dict(zip(parsed.rejected_rows.tolist(), parsed.rejected_reasons,
                                strict=True))
            for i, row in enumerate(texts):
                if i in rejected:
                    source.fail(row, column.name, raw[row], rejected[i], record=False)
                    continue
                values[row, k] = parsed.values[i]
                flags[row, k] = parsed.flags[i]
                reported[row, k] = parsed.reported[i]
                valid[row, k] = True

    def read_zone_intervals(self) -> ZoneColumns:
        catalog = self.catalog_name(TableKind.ZONES, "ZONAS")
        parts = []
        for source in self.of_kind(TableKind.ZONE_INTERVALS):
            holes = self.holes(source)
            start, end = self.span(source, "DESDE", "HASTA")
            angle = source.floats("ANGULO")
            zones = [self.code_of(source, "IDZONA", self.ids[TableKind.ZONES], catalog, row,
                                  value)
                     for row, value in enumerate(source.values("IDZONA"))]
            keep = np.flatnonzero(source.ok).tolist()
            external, extra = self.finish(source, keep)
            parts.append(record_columns(
                ZoneColumns, len(keep), hole_name=object_array([holes[k] for k in keep]),
                from_m=start[keep], to_m=end[keep], zone=object_array([zones[k] for k in keep]),
                angle_deg=angle[keep], external_id=external, extra=extra))
        return concat_columns(ZoneColumns, parts)

    def read_structures(self) -> StructureColumns:
        catalog = self.catalog_name(TableKind.ZONES, "ZONAS")
        plane = StructureColumns.code_values("structure_type").index(StructureType.ZONE_PLANE)
        origin = StructureColumns.code_values("orientation_source").index(
            OrientationSource.RECMIN_CORTES)
        parts = []
        for source in self.of_kind(TableKind.CUTS):
            holes = self.holes(source)
            depth, _ = self.span(source, "DISTANCIA")
            ids = source.values("IDZONA")
            keep = np.flatnonzero(source.ok).tolist()
            zones, extras = [], []
            for row in keep:
                more: dict[str, object] = {}
                zone = None
                if ids[row] is not None:
                    zone = self.ids[TableKind.ZONES].get(ids[row])
                    if zone is None:
                        name = source.column("IDZONA").name
                        more[name] = _extra_value(ids[row], False)
                        self.note_unresolved(source, name, ids[row], catalog, "zona",
                                             holes[row])
                zones.append(zone)
                extras.append(source.extra(row, **more))
            source.imported = len(keep)
            source.rejected = source.count - len(keep)
            count = len(keep)
            parts.append(record_columns(
                StructureColumns, count, hole_name=object_array([holes[k] for k in keep]),
                depth=depth[keep], structure_type=np.full(count, plane, dtype=np.int8),
                orientation_source=np.full(count, origin, dtype=np.int8),
                zone=object_array(zones),
                external_id=object_array([source.external_id(k) for k in keep]),
                extra=object_array(extras)))
        return concat_columns(StructureColumns, parts)

    # Avisos

    def unresolved_warnings(self) -> list[str]:
        found = []
        for (table, column, ident, where), labels in self.unresolved.items():
            catalog, what = where.split("\x00")
            plural = "registros" if len(labels) != 1 else "registro"
            shown = spanish_list([f"«{label}»" for label in labels])
            found.append(f"{table}: {column} {ident} no está en {catalog} ({len(labels)} "
                         f"{plural}, de {shown}): se importan sin {what}, con el "
                         f"identificador en «extra»")
        return found


def read_drillholes(
    raw: Mapping[str, RawTable] | Iterable[RawTable],
    decl: SourceDeclaration,
    catalogs: Catalogs | None = None,
    *,
    accept_schema: bool = False,
) -> tuple[DrillholeSet, ImportReport]:
    """El ``DrillholeSet`` de una base de RecMin (sus tablas crudas, ``raw``) y su informe
    (véase el módulo; RF-005-13): en el CRS, el datum y los convenios de ``decl`` (sin
    transformar), con los códigos nuevos frente a ``catalogs`` (los del proyecto; RF-005-10).

    Antes de leer: sin la tabla de sondeos o con una tabla conocida a la que le falta una
    columna, ``schema.RecminSchemaError``; con una versión de esquema que no es 11 ni 12 (o
    sin ella), ``dh.recmin_schema_unknown`` salvo con ``accept_schema`` (RF-005-15: entonces
    se lee lo que se reconoce y se avisa); sin las declaraciones que necesita (:func:`needs`),
    ``interop.base.DeclarationError`` con todas a la vez (RF-005-07). Las tablas no
    cambian."""
    decl = _check_decl(decl)
    tables = index_tables(raw)
    found = _layout(tables)
    require_collars(found)
    warning = require_schema(schema_version(tables), accept=accept_schema)
    require_declarations(decl, _needs(tables, found), obj=SOURCE_LABEL)

    reader = _Reader(tables, found, decl)
    elements = reader.read_formulas(reader.read_elements())
    lithology_codes = reader.read_lithology_codes()
    sectors = reader.read_entries(TableKind.SECTORS, "SECTOR")
    groups = reader.read_entries(TableKind.GROUPS, "GRUPO")
    zones = reader.read_entries(TableKind.ZONES, "ZONA")
    collars = reader.read_collars()
    additional = [source.use.log_set for source in reader.of_kind(TableKind.LITHOLOGY)
                  if not source.use.primary]
    lithology_catalog = tuple(lithology_codes) + tuple(
        dataclasses.replace(code, log_set=log_set)
        for log_set in additional for code in lithology_codes)
    dset = deduce_depths(DrillholeSet(
        crs=decl.crs, vertical=decl.vertical, collars=collars,
        surveys=link_columns(reader.read_surveys(), collars),
        lithology=link_columns(reader.read_lithology(), collars),
        assays=link_columns(reader.read_assays(), collars),
        zones=link_columns(reader.read_zone_intervals(), collars),
        structures=link_columns(reader.read_structures(), collars),
        catalogs=Catalogs(lithology=lithology_catalog, elements=tuple(elements),
                          sectors=tuple(sectors), groups=tuple(groups), zones=tuple(zones)),
    ))

    duplicates = duplicate_names(collars.name.tolist())
    warnings = [] if warning is None else [warning]
    for source in reader.of_kind(TableKind.ROTATIONS):
        if source.count:
            warnings.append(
                f"{source.name}: la base tiene {source.count} traslaciones o giros locales: sus "
                f"coordenadas pueden ser locales y no las del CRS declarado; si lo son, no la "
                f"importe (R-64)")
    skipped = found.not_imported + found.unknown
    if skipped:
        warnings.append(f"{SOURCE_LABEL}: tablas que no se importan (de RecMin que no son de "
                        f"sondeos, o desconocidas): {spanish_list(list(skipped))}")
    if duplicates:
        groups_text = "; ".join(spanish_list([f"«{name}»" for name in group])
                                for group in duplicates)
        warnings.append(f"{reader.main(TableKind.COLLARS).name}: sondeos con el nombre "
                        f"repetido (DH-E01), que no pasan a la base: {groups_text}")
    warnings += reader.unresolved_warnings()
    warnings.append(EMPTY_FIELDS_WARNING)

    counted = [source for source in reader.sources
               if source.kind not in (TableKind.VERSION, TableKind.ROTATIONS)]
    per_table = {
        source.name: source.counts(
            sum(len(group) for group in duplicates) if source.kind is TableKind.COLLARS else 0)
        for source in counted
    }
    report = ImportReport(
        per_table=per_table,
        rejected=tuple(r for source in reader.sources for r in source.rejections()),
        warnings=tuple(warnings),
        unknown_codes=new_codes(dset, catalogs),
        duplicate_holes=duplicates,
    )
    return dset, report
