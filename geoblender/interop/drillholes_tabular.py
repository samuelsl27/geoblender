# SPDX-License-Identifier: GPL-3.0-or-later
"""Sondeos desde tablas CSV o XLSX (spec 005, T14; RF-005-05, RF-005-07, RF-005-09,
RF-005-10; plan 005 §5.3.2, §5.4, §5.6.2 y §5.6.12).

Una tabla (``interop.csv_tables.Table``, de un CSV o de una hoja de un XLSX) tiene un
**papel** (:class:`TableRole`): bocas, desviaciones, litología, análisis en columnas (una por
elemento) o en filas (elemento, valor y unidad), catálogo de litologías o de elementos.

- **Correspondencia de columnas** (RF-005-05): :func:`suggest_mapping` propone, por los
  nombres habituales en español y en inglés (sin tildes, mayúsculas, espacios ni signos:
  «Inclinación», «INCLINACION» y «inclination» son lo mismo; :func:`aliases`), qué columna
  es cada campo (``{"x": "Este", …}``); en los análisis en columnas, cada columna que no es
  de un campo es un elemento (``"element:Au": "Au"``, :data:`ELEMENT_PREFIX`). El usuario
  la edita; una correspondencia que no vale (campo obligatorio sin columna, columna que no
  está, repetida o con dos columnas del mismo nombre, campo desconocido) se rechaza con
  :class:`MappingError` (``dh.mapping_*``) nombrando el campo. (T25) :func:`suggest_role`
  propone el papel de una tabla por el nombre de su fichero o de su hoja (o, si no lo dice,
  por sus columnas).
- **Declaraciones** (RF-005-07): :func:`needs` dice lo que hay que declarar para leer la
  tabla (``interop.base.Needs``): el CRS y el datum vertical de las bocas; la referencia del
  azimut y el convenio de la inclinación de las desviaciones y de una orientación en boca
  con datos; el formato de las fechas escritas; la unidad de cada elemento que no la trae
  en el fichero. Sin ellas no se lee (``interop.base.DeclarationError``, que las nombra).
- **Lectura por papel** (:func:`read_role`; D-15 del plan: una entrada por fichero o por
  hoja): las filas de la tabla interpretadas, en el CRS, el datum y los convenios
  declarados, sin transformar (las conversiones son de ``dh.build_base``), en las columnas
  de ``drillholes.model`` (:class:`RoleRows`; los registros hijos, sin enlazar a sus bocas:
  ``hole`` = −1). Es la lectura que usa el lector de contenido ``io.dh_csv@1``. Leer la
  vista previa (``preview_table``, 20 filas) da las filas tal como se van a interpretar.
- **Valores** (RF-005-09): los de los análisis, con ``drillholes.values.parse_column`` y
  las reglas declaradas (vacío o centinela, ausente; «<x» y «>x», x con su marca; negativo,
  tal cual o «<x» si se declara), conservando el texto original; los demás números, con el
  separador decimal declarado, sin centinelas ni marcas. Se rechaza, con su fila, su
  columna, su valor y un motivo que empieza por su sondeo y su tramo, lo que no es un número
  (también con el otro separador decimal), un error de Excel («#N/A», en cualquier
  columna), un sí/no, una fecha, un tipo de sondeo, un color, un entero o una unidad de ley
  que no lo son, una fila sin sondeo o sin código, un código repetido en un catálogo y una
  fila con otro número de campos que la cabecera. En los análisis en columnas se rechaza el
  valor, no la muestra. Un rango imposible (desde ≥ hasta, azimut 400°) no se rechaza: lo
  marca la validación.
- **Varias tablas** (:func:`read_drillholes`): el ``DrillholeSet`` de las tablas de una
  importación, en el CRS de la fuente, con su ``interop.base.ImportReport``: los registros
  hijos enlazados a su boca por el nombre; la orientación en boca, una estación a 0 m de un
  sondeo sin desviaciones (spec §8); con «todos verticales», una estación vertical (0°,
  −90°, ya en los convenios internos) en cada sondeo sin ninguna; la profundidad que falta,
  deducida (DH-W16); los nombres repetidos en la fuente (DH-E01: siguen en lo leído, la
  validación los marca y no pasan a la base) y los códigos nuevos frente a los catálogos del
  proyecto (RF-005-10).

Las tablas nunca se modifican. Dominio puro: Python y numpy (ARQ-07).
"""

from __future__ import annotations

import datetime as dt
import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

import numpy as np

from ..core.errors import GeoblenderError
from ..drillholes.model import (
    DEFAULT_COLOR,
    AssayColumns,
    Catalogs,
    CollarColumns,
    DrillholeSet,
    Element,
    HoleType,
    IntervalColumns,
    LithologyCode,
    Rejection,
    SourceDeclaration,
    StationSource,
    SurveyColumns,
    ValueRules,
    name_key,
)
from ..drillholes.validate import deduce_depths
from ..drillholes.values import FLAG_CODES, DetectionFlag, parse_column
from .base import (
    ImportReport,
    Needs,
    TableCounts,
    concat_columns,
    duplicate_names,
    grade_unit,
    link_columns,
    new_codes,
    none_array,
    object_array,
    record_columns,
    require_declarations,
    spanish_list,
)
from .csv_tables import Table
from .xlsx_tables import ERROR_VALUES

__all__ = [
    "ELEMENT_PREFIX",
    "FIELD_LABELS",
    "ROLE_LABELS",
    "ROW_FIELD",
    "SOURCE_LABEL",
    "MappingError",
    "RoleRows",
    "TableRole",
    "aliases",
    "header_key",
    "needs",
    "read_drillholes",
    "read_role",
    "required_fields",
    "suggest_mapping",
    "suggest_role",
]


class TableRole(StrEnum):
    """El papel de una tabla de una importación de sondeos (los de ``csv_basico``)."""

    COLLAR = "collar"  # bocas
    SURVEY = "survey"  # desviaciones
    LITHOLOGY = "lithology"  # litología
    ASSAY_WIDE = "assay_wide"  # análisis en columnas (una por elemento)
    ASSAY_LONG = "assay_long"  # análisis en filas (elemento, valor, unidad)
    LITHOLOGY_CATALOG = "lithology_catalog"  # catálogo de litologías
    ELEMENT_CATALOG = "element_catalog"  # catálogo de elementos


ROLE_LABELS: Mapping[TableRole, str] = MappingProxyType({
    TableRole.COLLAR: "Bocas",
    TableRole.SURVEY: "Desviaciones",
    TableRole.LITHOLOGY: "Litología",
    TableRole.ASSAY_WIDE: "Análisis en columnas",
    TableRole.ASSAY_LONG: "Análisis en filas",
    TableRole.LITHOLOGY_CATALOG: "Catálogo de litologías",
    TableRole.ELEMENT_CATALOG: "Catálogo de elementos",
})
"""El nombre de cada papel en los mensajes."""
SOURCE_LABEL = "Importación de sondeos"
"""El objeto de los mensajes de una importación con varias tablas."""
ELEMENT_PREFIX = "element:"
"""En los análisis en columnas, la clave de un elemento: ``"element:Au": "Au"``."""
ROW_FIELD = "fila"
"""El campo de un rechazo de la fila entera (otro número de campos que la cabecera)."""

FIELD_LABELS: Mapping[str, str] = MappingProxyType({
    "name": "sondeo", "hole": "sondeo", "x": "X (este)", "y": "Y (norte)", "z": "Z (cota)",
    "depth": "profundidad", "azimuth": "azimut", "inclination": "inclinación",
    "hole_type": "tipo", "planned": "planificado", "grade_control": "control de leyes",
    "category": "categoría", "priority": "prioridad", "sector": "sector", "group": "grupo",
    "campaign": "campaña", "start_date": "fecha de inicio", "end_date": "fecha de fin",
    "survey_method": "método de levantamiento", "external_id": "identificador externo",
    "comments": "comentarios", "method": "método", "from_m": "desde", "to_m": "hasta",
    "code": "código", "description": "descripción", "logged_by": "geólogo",
    "sample_id": "muestra", "lab": "laboratorio", "batch": "lote", "element": "elemento",
    "value": "valor", "unit": "unidad", "color": "color", "pattern": "trama",
    "density": "densidad", "sort_order": "orden", "decimals": "decimales",
    "detection_limit": "límite de detección",
})
"""El nombre en español de cada campo (mensajes y asistente)."""


# --- Campos de cada papel y sus nombres habituales (RF-005-05) ---------------------------------


def header_key(text: str) -> str:
    """La forma con que se comparan los nombres de las columnas: sin tildes, sin mayúsculas
    y solo con letras y cifras ASCII («Fecha  de inicio» → ``fechadeinicio``)."""
    if not isinstance(text, str):
        raise TypeError(f"el nombre de una columna es un texto, no {text!r}")
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if char.isascii() and char.isalnum())


@dataclass(frozen=True, slots=True)
class _Spec:
    """Un campo de un papel: su nombre (el del modelo), si es obligatorio y sus nombres
    habituales (ya con :func:`header_key`)."""

    name: str
    required: bool
    aliases: frozenset[str]


def _spec(name: str, aliases: str, required: bool = False) -> _Spec:
    return _Spec(name, required, frozenset(aliases.split()))


_HOLE = ("sondeo nombre nombresondeo idsondeo hole holeid holename bhid dhid borehole "
         "boreholeid drillhole drillholeid id pozo")
_AZIMUTH = "azimut azimuth az azi direccion bearing brg"
_INCLINATION = "inclinacion inclination inc incl dip buzamiento"
_FROM = "desde de from depthfrom fromm"
_TO = "hasta a to depthto tom"
_SAMPLE = ("muestra nmuestra numeromuestra idmuestra codigomuestra sample sampleid "
           "samplenumber sampleno")
_EXTERNAL = "idexterno identificadorexterno externalid"
_UNIT = "unidad unidades unit units"
_ORDER = "orden order sortorder"
_ASSAY_COMMON = (
    _spec("hole", _HOLE, True),
    _spec("from_m", _FROM, True),
    _spec("to_m", _TO, True),
    _spec("sample_id", _SAMPLE),
    _spec("lab", "laboratorio lab laboratory"),
    _spec("method", "metodo metodoanalitico method analyticalmethod"),
    _spec("batch", "lote batch"),
    _spec("external_id", _EXTERNAL),
)

_FIELDS: Mapping[TableRole, tuple[_Spec, ...]] = MappingProxyType({
    TableRole.COLLAR: (
        _spec("name", _HOLE, True),
        _spec("x", "x este east easting e coordx xutm utmx utme", True),
        _spec("y", "y norte north northing n coordy yutm utmy utmn", True),
        _spec("z", "z cota elevacion elevation elev rl altitud altitude altura cotaboca",
              True),
        _spec("depth", "profundidad prof profundidadtotal proftotal depth totaldepth "
                       "maxdepth eoh finaldepth length longitud"),
        _spec("azimuth", _AZIMUTH),
        _spec("inclination", _INCLINATION),
        _spec("hole_type", "tipo tiposondeo type holetype"),
        _spec("planned", "planificado previsto planned"),
        _spec("grade_control", "controldeleyes controlleyes gradecontrol"),
        _spec("category", "categoria category"),
        _spec("priority", "prioridad priority"),
        _spec("sector", "sector"),
        _spec("group", "grupo group"),
        _spec("campaign", "campana campaign programa program"),
        _spec("start_date", "fechainicio fechadeinicio inicio startdate start datestarted"),
        _spec("end_date", "fechafin fechadefin fechafinal fin enddate end datecompleted"),
        _spec("survey_method", "metododedesviacion metododesviacion metododelevantamiento "
                               "surveymethod"),
        _spec("external_id", _EXTERNAL),
        _spec("comments", "comentarios observaciones notas comments comment notes remarks"),
    ),
    TableRole.SURVEY: (
        _spec("hole", _HOLE, True),
        _spec("depth", "profundidad prof depth distancia distance md at surveydepth", True),
        _spec("azimuth", _AZIMUTH, True),
        _spec("inclination", _INCLINATION, True),
        _spec("method", "metodo instrumento method instrument tool"),
        _spec("external_id", _EXTERNAL),
    ),
    TableRole.LITHOLOGY: (
        _spec("hole", _HOLE, True),
        _spec("from_m", _FROM, True),
        _spec("to_m", _TO, True),
        _spec("code", "litologia codigolitologia lito lit codigo lith litho lithology "
                      "lithcode code rock rocktype roca", True),
        _spec("description", "descripcion description desc"),
        _spec("logged_by", "geologo loggedby logger geologist"),
        _spec("external_id", _EXTERNAL),
    ),
    TableRole.ASSAY_WIDE: _ASSAY_COMMON,
    TableRole.ASSAY_LONG: _ASSAY_COMMON[:4] + (
        _spec("element", "elemento analito element analyte", True),
        _spec("value", "valor ley resultado value grade result", True),
        _spec("unit", _UNIT),
    ) + _ASSAY_COMMON[4:],
    TableRole.LITHOLOGY_CATALOG: (
        _spec("code", "codigo litologia lito code lith lithology litho lithcode", True),
        _spec("description", "descripcion nombre description name"),
        _spec("color", "color colour rgb"),
        _spec("pattern", "trama patron pattern"),
        _spec("density", "densidad density sg pesoespecifico"),
        _spec("sort_order", _ORDER),
        _spec("external_id", _EXTERNAL),
    ),
    TableRole.ELEMENT_CATALOG: (
        _spec("code", "codigo elemento code element", True),
        _spec("name", "nombre descripcion name description"),
        _spec("unit", _UNIT),
        _spec("decimals", "decimales decimals"),
        _spec("detection_limit", "limitededeteccion limitedeteccion ld detectionlimit dl lod"),
        _spec("sort_order", _ORDER),
        _spec("external_id", _EXTERNAL),
    ),
})


def _role(role: object) -> TableRole:
    """El papel ``role`` (su texto vale); ``ValueError`` si no es uno de :class:`TableRole`."""
    try:
        return TableRole(role)
    except ValueError:
        raise ValueError(f"un papel es uno de {[str(r) for r in TableRole]}, no "
                         f"{role!r}") from None


def aliases(role: TableRole | str) -> Mapping[str, frozenset[str]]:
    """Los nombres habituales (con :func:`header_key`) de cada campo del papel ``role``."""
    return MappingProxyType({spec.name: spec.aliases for spec in _FIELDS[_role(role)]})


def required_fields(role: TableRole | str) -> tuple[str, ...]:
    """Los campos que necesitan columna en el papel ``role`` (y, en los análisis en
    columnas, al menos un elemento)."""
    return tuple(spec.name for spec in _FIELDS[_role(role)] if spec.required)


def suggest_mapping(role: TableRole | str, columns: Sequence[str]) -> dict[str, str]:
    """La correspondencia propuesta para una tabla del papel ``role`` con las columnas
    ``columns`` (RF-005-05): cada campo, con la primera columna libre cuyo nombre es uno de
    sus nombres habituales (:func:`aliases`); en los análisis en columnas, además, cada
    columna libre como un elemento con su nombre (``"element:Au": "Au"``)."""
    role = _role(role)
    if isinstance(columns, str) or not isinstance(columns, Sequence):
        raise TypeError(f"las columnas son una lista de nombres, no {columns!r}")
    keys = [header_key(column) for column in columns]
    used: set[int] = set()
    mapping: dict[str, str] = {}
    for spec in _FIELDS[role]:
        for position, key in enumerate(keys):
            if position not in used and key and key in spec.aliases:
                mapping[spec.name] = columns[position]
                used.add(position)
                break
    if role is TableRole.ASSAY_WIDE:
        seen: set[str] = set()
        for position, column in enumerate(columns):
            code = column.strip()
            if position in used or not code or name_key(code) in seen:
                continue
            seen.add(name_key(code))
            mapping[ELEMENT_PREFIX + code] = column
    return mapping


_ROLE_NAMES: tuple[tuple[TableRole, tuple[str, ...]], ...] = (
    # Los catálogos, antes que la litología y los análisis («litologias» empieza por
    # «litologia»).
    (TableRole.LITHOLOGY_CATALOG, ("litologias", "lithologies", "lithologycodes", "lithcodes",
                                   "codigoslitologia", "codigosdelitologia",
                                   "catalogolitologias", "catalogodelitologias")),
    (TableRole.ELEMENT_CATALOG, ("elementos", "elements", "analitos", "analytes",
                                 "catalogoelementos", "catalogodeelementos")),
    (TableRole.COLLAR, ("bocas", "boca", "collar", "sondeos", "holes", "drillholes")),
    (TableRole.SURVEY, ("desviacion", "survey", "levantamiento", "downhole")),
    (TableRole.LITHOLOGY, ("litologia", "lithology", "geologia", "geology", "logueo")),
    (TableRole.ASSAY_WIDE, ("analisis", "assay", "leyes", "muestras", "samples", "quimica")),
)
"""Cómo empieza el nombre (con :func:`header_key`) de un fichero o de una hoja de cada papel;
los análisis, en columnas o en filas según sus columnas."""
_ROLES_BY_COLUMNS: tuple[TableRole, ...] = (
    TableRole.COLLAR, TableRole.SURVEY, TableRole.ASSAY_LONG, TableRole.LITHOLOGY)
"""Sin nombre reconocible, los papeles que se proponen por sus columnas (todas las
obligatorias), en este orden."""


def _assays(columns: Sequence[str]) -> TableRole:
    """Unos análisis en filas si tienen columnas de elemento y de valor; si no, en
    columnas."""
    found = suggest_mapping(TableRole.ASSAY_LONG, columns)
    if "element" in found and "value" in found:
        return TableRole.ASSAY_LONG
    return TableRole.ASSAY_WIDE


def suggest_role(name: str, columns: Sequence[str]) -> TableRole | None:
    """El papel propuesto para la tabla de un fichero o de una hoja llamado ``name`` (sin la
    carpeta; la extensión no cuenta) con las columnas ``columns`` (RF-005-05): por cómo
    empieza su nombre, en español o en inglés («bocas», «collars_2026», «desviaciones»,
    «litologia», «analisis_filas», «litologias», «elements»…; los análisis, en filas si tienen
    columnas de elemento y valor y si no, en columnas); si el nombre no lo dice, el primero de
    bocas, desviaciones, análisis en filas y litología cuyos campos obligatorios están todos
    entre sus columnas. ``None`` si nada encaja: lo elige quien importa."""
    if not isinstance(name, str):
        raise TypeError(f"el nombre de una tabla es un texto, no {name!r}")
    if isinstance(columns, str) or not isinstance(columns, Sequence):
        raise TypeError(f"las columnas son una lista de nombres, no {columns!r}")
    stem = name.rsplit(".", 1)[0] if "." in name else name
    key = header_key(stem)
    for role, starts in _ROLE_NAMES:
        if key and any(key.startswith(start) for start in starts):
            return _assays(columns) if role is TableRole.ASSAY_WIDE else role
    for role in _ROLES_BY_COLUMNS:
        found = suggest_mapping(role, columns)
        if all(field in found for field in required_fields(role)):
            return role
    return None


class MappingError(GeoblenderError):
    """Una correspondencia de columnas que no vale (``dh.mapping_*``): el objeto es la
    tabla (su papel), el campo es la clave de la correspondencia y el valor, la columna."""


@dataclass(frozen=True)
class _Layout:
    """Una correspondencia comprobada: la posición de la columna de cada campo y los
    elementos de los análisis en columnas (código, posición)."""

    index: Mapping[str, int]
    elements: tuple[tuple[str, int], ...]


def _layout(role: TableRole, columns: Sequence[str], mapping: object) -> _Layout:
    """La correspondencia ``mapping`` comprobada contra ``columns`` (véase el módulo)."""
    if not isinstance(mapping, Mapping):
        raise TypeError(f"la correspondencia es campo → columna, no {mapping!r}")
    label = ROLE_LABELS[role]
    specs = {spec.name: spec for spec in _FIELDS[role]}
    positions: dict[str, list[int]] = {}
    for position, column in enumerate(columns):
        positions.setdefault(column, []).append(position)
    index: dict[str, int] = {}
    elements: list[tuple[str, int]] = []
    owners: dict[int, str] = {}
    codes: dict[str, str] = {}
    for key, column in mapping.items():
        if not isinstance(key, str) or not isinstance(column, str):
            raise TypeError(f"la correspondencia es de textos (campo → columna), no "
                            f"{key!r} → {column!r}")
        code = None
        if role is TableRole.ASSAY_WIDE and key.startswith(ELEMENT_PREFIX):
            code = key[len(ELEMENT_PREFIX):].strip()
        if (code is None and key not in specs) or code == "":
            raise MappingError(
                "dh.mapping_unknown_field",
                f"no es un campo de esta tabla: los campos son "
                f"{spanish_list(list(specs))}"
                + (f" y, para cada elemento, «{ELEMENT_PREFIX}<código>»"
                   if role is TableRole.ASSAY_WIDE else ""),
                obj=label, field=key, value=column)
        found = positions.get(column, [])
        if not found:
            raise MappingError("dh.mapping_missing_column",
                               "la tabla no tiene esa columna: elija una de las suyas",
                               obj=label, field=key, value=column)
        if len(found) > 1:
            raise MappingError("dh.mapping_ambiguous_column",
                               f"la tabla tiene {len(found)} columnas con ese nombre: "
                               f"cámbielo en el fichero para elegir una",
                               obj=label, field=key, value=column)
        position = found[0]
        if position in owners:
            raise MappingError("dh.mapping_repeated_column",
                               f"esa columna ya es «{owners[position]}»: una columna es un "
                               f"solo campo",
                               obj=label, field=key, value=column)
        owners[position] = key
        if code is None:
            index[key] = position
            continue
        if name_key(code) in codes:
            raise MappingError("dh.mapping_repeated_element",
                               f"el elemento «{code}» ya es la columna «{codes[name_key(code)]}»",
                               obj=label, field=key, value=column)
        codes[name_key(code)] = column
        elements.append((code, position))
    missing = [name for name, spec in specs.items() if spec.required and name not in index]
    if missing:
        shown = spanish_list([f"«{FIELD_LABELS[name]}» ({name})" for name in missing])
        raise MappingError("dh.mapping_required",
                           f"falta la columna de {shown}: es obligatoria", obj=label,
                           field=missing[0], shown="sin columna")
    if role is TableRole.ASSAY_WIDE and not elements:
        raise MappingError("dh.mapping_required",
                           "los análisis en columnas necesitan al menos una columna de un "
                           "elemento", obj=label, field="elementos", shown="ninguno")
    return _Layout(MappingProxyType(index), tuple(elements))


def _column_texts(table: Table, position: int) -> list[str]:
    """Los textos de la columna ``position`` (una fila más corta, «»)."""
    return [row[position] if position < len(row) else "" for row in table.rows]


def _any_text(table: Table, layout: _Layout, *names: str) -> bool:
    for name in names:
        position = layout.index.get(name)
        if position is not None and any(t.strip() for t in _column_texts(table, position)):
            return True
    return False


def _without_unit(table: Table, layout: _Layout, code_field: str) -> tuple[str, ...]:
    """Los códigos (en su orden) de las filas sin unidad en el fichero."""
    codes = _column_texts(table, layout.index[code_field])
    position = layout.index.get("unit")
    units = [""] * len(codes) if position is None else _column_texts(table, position)
    return tuple(code for code, unit in zip(codes, units, strict=True)
                 if code.strip() and not unit.strip())


def _needs(role: TableRole, table: Table, layout: _Layout) -> Needs:
    if role is TableRole.COLLAR:
        oriented = _any_text(table, layout, "azimuth", "inclination")
        return Needs(crs=True, vertical=True, azimuth=oriented, inclination=oriented,
                     dates=_any_text(table, layout, "start_date", "end_date"))
    if role is TableRole.SURVEY:
        return Needs(azimuth=True, inclination=True)
    if role is TableRole.ASSAY_WIDE:
        return Needs(elements=tuple(code for code, _ in layout.elements))
    if role is TableRole.ASSAY_LONG:
        return Needs(elements=_without_unit(table, layout, "element"))
    if role is TableRole.ELEMENT_CATALOG:
        return Needs(elements=_without_unit(table, layout, "code"))
    return Needs()


def _check_table(table: object) -> Table:
    if not isinstance(table, Table):
        raise TypeError(f"una tabla es un interop.csv_tables.Table, no {table!r}")
    return table


def needs(role: TableRole | str, table: Table, mapping: Mapping[str, str]) -> Needs:
    """Lo que hay que declarar para leer ``table`` como ``role`` con ``mapping``
    (RF-005-07; véase el módulo). ``MappingError`` si la correspondencia no vale."""
    role = _role(role)
    table = _check_table(table)
    return _needs(role, table, _layout(role, table.columns, mapping))


# --- La lectura de una tabla -------------------------------------------------------------------

_TRUE = frozenset({"si", "s", "yes", "y", "true", "verdadero", "1"})
_FALSE = frozenset({"no", "n", "false", "falso", "0"})
_HOLE_TYPES: Mapping[str, HoleType] = MappingProxyType({
    alias: kind
    for kind, names in (
        (HoleType.DD, "dd diamantina diamante diamond testigo sondeoatestigo core"),
        (HoleType.RC, "rc circulacioninversa reversecirculation"),
        (HoleType.RP, "rp rotopercusion percusion percussion"),
        (HoleType.AC, "ac aircore"),
        (HoleType.TR, "tr zanja trinchera trench"),
        (HoleType.CA, "ca calicata pit testpit"),
        (HoleType.OT, "ot otro otros other"),
    )
    for alias in names.split()
})
_COLOR = re.compile(r"#?([0-9A-Fa-f]{6})")
_OK = FLAG_CODES[DetectionFlag.OK]
_EXACT_INT = 2.0**53
_SPECIAL_REASON = "«<» y «>» solo valen en los valores de los análisis"
_EXCEL_REASON = "es un error de Excel, no un dato: corrija la celda en el libro"


def _shown(value: float) -> str:
    """Un número como en los mensajes: el decimal más corto, con coma."""
    return np.format_float_positional(value, unique=True, trim="-").replace(".", ",")


@dataclass(frozen=True, eq=False)
class RoleRows:
    """Las filas de una tabla interpretadas (:func:`read_role`), en el CRS, el datum y los
    convenios declarados: las bocas (``collars``) y su orientación en boca (``surveys``,
    estaciones ``collar`` a 0 m), las desviaciones (``surveys``), la litología, los análisis
    o los catálogos, según el papel; los registros hijos, sin enlazar (``hole`` = −1).
    ``lines`` da la fila de la fuente de cada registro (por tabla: ``collars``,
    ``surveys``, ``lithology``, ``assays``); ``rejected``, los rechazos (RF-005-09);
    ``duplicate_holes``, las bocas con el mismo nombre (DH-E01)."""

    role: TableRole
    read: int
    imported: int
    rejected_records: int
    collars: CollarColumns
    surveys: SurveyColumns
    lithology: IntervalColumns
    assays: AssayColumns
    catalogs: Catalogs
    lines: Mapping[str, np.ndarray]
    rejected: tuple[Rejection, ...]
    duplicate_holes: tuple[tuple[str, ...], ...] = ()

    @property
    def counts(self) -> TableCounts:
        """Los recuentos de la tabla (RF-005-12)."""
        return TableCounts(read=self.read, imported=self.imported,
                           rejected=self.rejected_records,
                           duplicated=sum(len(group) for group in self.duplicate_holes))


class _Reader:
    """Una tabla de un papel mientras se lee: los textos de cada campo, lo interpretado y
    los rechazos de cada fila (con la posición de su columna, para ordenarlos)."""

    def __init__(self, role: TableRole, table: Table, layout: _Layout,
                 decl: SourceDeclaration) -> None:
        self.role = role
        self.table = table
        self.layout = layout
        self.decl = decl
        self.count = len(table.rows)
        self.lines = np.array(table.lines, dtype=np.int64)
        self.rules = ValueRules(decimal_mark=decl.value_rules.decimal_mark)
        width = len(table.columns)
        self.broken = np.array([len(row) != width for row in table.rows], dtype=bool)
        self.ok = ~self.broken
        self.problems: list[tuple[int, int, str, str | None, str]] = [
            (row, -1, ROW_FIELD, None, f"la fila tiene {len(table.rows[row])} campos y la "
                                       f"cabecera {width}")
            for row in np.flatnonzero(self.broken).tolist()
        ]
        self.label: list[str | None] = [None] * self.count  # sondeo o código, para el motivo
        self.span: tuple[np.ndarray, np.ndarray] | None = None

    # Rechazos

    def fail(self, row: int, position: int, value: str | None, reason: str, *,
             record: bool = True) -> None:
        """Rechaza la fila ``row`` (``record``: la fila entera) por la columna ``position``."""
        if self.broken[row]:
            return
        if record:
            self.ok[row] = False
        shown = value if value is not None and value.strip() else None
        self.problems.append((row, position, self.table.columns[position], shown, reason))

    def rejections(self) -> tuple[Rejection, ...]:
        """Los rechazos, por fila y columna, con el sondeo y el tramo (o el código) delante
        del motivo."""
        found = []
        for row, position, column, value, reason in sorted(self.problems,
                                                           key=lambda p: (p[0], p[1])):
            found.append(Rejection(str(self.role), int(self.lines[row]), column, value,
                                   self._where(row, reason)))
        return tuple(found)

    def _where(self, row: int, reason: str) -> str:
        label = self.label[row]
        if label is None:
            return reason
        if self.role in (TableRole.LITHOLOGY_CATALOG, TableRole.ELEMENT_CATALOG):
            return f"código «{label}»: {reason}"
        place = f"sondeo «{label}»"
        if self.span is not None:
            start, end = float(self.span[0][row]), float(self.span[1][row])
            if self.role is TableRole.SURVEY and math.isfinite(start):
                place += f", a {_shown(start)} m"
            elif math.isfinite(start) and math.isfinite(end):
                place += f", de {_shown(start)} a {_shown(end)} m"
        return f"{place}: {reason}"

    # Textos

    def position(self, name: str) -> int | None:
        return self.layout.index.get(name)

    def texts(self, name: str) -> list[str] | None:
        """Los textos del campo ``name`` (``None`` sin columna); un error de Excel rechaza
        su fila y queda «»."""
        position = self.position(name)
        if position is None:
            return None
        texts = _column_texts(self.table, position)
        for row in self._excel(texts):
            self.fail(row, position, texts[row], _EXCEL_REASON)
            texts[row] = ""
        return texts

    @staticmethod
    def _excel(texts: Sequence[str]) -> list[int]:
        return [row for row, text in enumerate(texts) if "#" in text and text.strip() in
                ERROR_VALUES]

    def keys(self, name: str, missing: str) -> np.ndarray:
        """Un campo obligatorio de texto (sondeo, código): tal como venía; vacío, la fila
        rechazada con ``missing``."""
        texts = self.texts(name)
        position = self.position(name)
        found = []
        for row, text in enumerate(texts):
            if text.strip():
                found.append(text)
            else:
                found.append(None)
                self.fail(row, position, None, missing)
        return object_array(found)

    def optional(self, name: str) -> np.ndarray:
        """Un campo de texto opcional: tal como venía; vacío, ``None``."""
        texts = self.texts(name)
        if texts is None:
            return none_array(self.count)
        return object_array([text if text.strip() else None for text in texts])

    def numbers(self, name: str) -> np.ndarray:
        """Un número que no es una ley (float64; vacío o rechazado, NaN): con el separador
        decimal declarado, sin centinelas ni «<x»/«>x»."""
        return self._numbers(name)[0]

    def _numbers(self, name: str) -> tuple[np.ndarray, list[str] | None]:
        texts = self.texts(name)
        if texts is None:
            return np.full(self.count, math.nan), None
        position = self.position(name)
        parsed = parse_column(texts, self.rules)
        values = parsed.values.copy()
        for row, reason in zip(parsed.rejected_rows.tolist(), parsed.rejected_reasons,
                               strict=True):
            self.fail(row, position, texts[row], reason)
        for row in np.flatnonzero(parsed.flags != _OK).tolist():
            self.fail(row, position, texts[row], _SPECIAL_REASON)
            values[row] = math.nan
        return values, texts

    def integers(self, name: str, default: int | None) -> list[int | None]:
        """Un entero (vacío, ``default``)."""
        values, texts = self._numbers(name)
        found: list[int | None] = []
        for row, value in enumerate(values.tolist()):
            if math.isnan(value):
                found.append(default)
            elif value.is_integer() and abs(value) < _EXACT_INT:
                found.append(int(value))
            else:
                self.fail(row, self.position(name), texts[row], "no es un número entero")
                found.append(default)
        return found

    def bools(self, name: str) -> np.ndarray:
        """Sí o no («sí», «no», «yes», «TRUE», «1»…; vacío, no)."""
        texts = self.texts(name)
        found = np.zeros(self.count, dtype=bool)
        if texts is None:
            return found
        for row, text in enumerate(texts):
            key = header_key(text)
            if key in _TRUE:
                found[row] = True
            elif key and key not in _FALSE:
                self.fail(row, self.position(name), text, "no es sí ni no (sí, no, yes, "
                                                         "TRUE, FALSE, 1 o 0)")
        return found

    def dates(self, name: str) -> np.ndarray:
        """Una fecha con el formato declarado (vacía, ``None``)."""
        texts = self.texts(name)
        if texts is None:
            return none_array(self.count)
        fmt = self.decl.date_format
        found: list[dt.date | None] = []
        for row, text in enumerate(texts):
            value = None
            if text.strip():
                try:
                    value = dt.datetime.strptime(text.strip(), fmt).date()
                except (TypeError, ValueError):
                    self.fail(row, self.position(name), text,
                              f"no es una fecha con el formato declarado «{fmt}»")
            found.append(value)
        return object_array(found)

    def hole_types(self, name: str) -> np.ndarray:
        """El tipo de sondeo (código int8; vacío, −1) por su código o su nombre en español
        o en inglés («Calicata», «trench»)."""
        texts = self.texts(name)
        found = np.full(self.count, -1, dtype=np.int8)
        if texts is None:
            return found
        kinds = CollarColumns.code_values("hole_type")
        for row, text in enumerate(texts):
            key = header_key(text)
            if not key:
                continue
            kind = _HOLE_TYPES.get(key)
            if kind is None:
                self.fail(row, self.position(name), text, "no es un tipo de sondeo (DD, RC, "
                                                         "RP, AC, TR, CA u OT)")
            else:
                found[row] = kinds.index(kind)
        return found

    def colors(self, name: str) -> list[str]:
        """Un color «#RRGGBB» (también en minúsculas o sin «#»; vacío, el gris por
        defecto)."""
        texts = self.texts(name)
        if texts is None:
            return [DEFAULT_COLOR] * self.count
        found = []
        for row, text in enumerate(texts):
            match = _COLOR.fullmatch(text.strip())
            if not text.strip():
                found.append(DEFAULT_COLOR)
            elif match is None:
                self.fail(row, self.position(name), text, "no es un color «#RRGGBB» (seis "
                                                         "cifras hexadecimales)")
                found.append(DEFAULT_COLOR)
            else:
                found.append(f"#{match.group(1).upper()}")
        return found

    def units(self, codes: np.ndarray) -> tuple[list[str | None], list[str | None]]:
        """La unidad de ley de cada fila (la del fichero o, si no la trae, la declarada
        para su código) y la unidad tal como venía; una que no es de ley, rechazada."""
        texts = self.texts("unit")
        if texts is None:
            texts = [""] * self.count
        position = self.position("unit")
        units: list[str | None] = []
        reported: list[str | None] = []
        for row, text in enumerate(texts):
            if text.strip():
                unit, shown = grade_unit(text), text
                if unit is None:
                    self.fail(row, position, text, "no es una unidad de ley (g/t, ppm, ppb "
                                                   "o %)")
            elif codes[row] is not None:
                shown = self.decl.unit_of(codes[row])
                unit = grade_unit(shown)
            else:
                unit = shown = None
            units.append(unit)
            reported.append(shown)
        return units, reported

    def repeated(self, codes: np.ndarray, name: str) -> None:
        """Rechaza la fila que repite un código de otra anterior (sin distinguir mayúsculas
        ni espacios exteriores)."""
        first: dict[str, int] = {}
        for row in np.flatnonzero(self.ok).tolist():
            key = name_key(codes[row])
            if key in first:
                earlier = first[key]
                self.fail(row, self.position(name), codes[row],
                          f"repite el código «{codes[earlier]}» de la fila "
                          f"{int(self.lines[earlier])}")
            else:
                first[key] = row

    def result(self, imported: int, rejected_records: int, **parts: Any) -> RoleRows:
        lines = parts.pop("lines", {})
        return RoleRows(
            role=self.role,
            read=self.count,
            imported=imported,
            rejected_records=rejected_records,
            collars=parts.pop("collars", CollarColumns.empty()),
            surveys=parts.pop("surveys", SurveyColumns.empty()),
            lithology=parts.pop("lithology", IntervalColumns.empty()),
            assays=parts.pop("assays", AssayColumns.empty()),
            catalogs=parts.pop("catalogs", Catalogs()),
            lines=MappingProxyType(dict(lines)),
            rejected=self.rejections(),
            duplicate_holes=parts.pop("duplicate_holes", ()),
        )


def _holes(reader: _Reader, name: str) -> np.ndarray:
    holes = reader.keys(name, "falta el nombre del sondeo")
    reader.label = holes.tolist()
    return holes


def _read_collars(r: _Reader) -> RoleRows:
    names = _holes(r, "name")
    x, y, z = r.numbers("x"), r.numbers("y"), r.numbers("z")
    depth = r.numbers("depth")
    azimuth, inclination = r.numbers("azimuth"), r.numbers("inclination")
    hole_type = r.hole_types("hole_type")
    planned, grade_control = r.bools("planned"), r.bools("grade_control")
    category = r.integers("category", None)
    priority = r.integers("priority", None)
    texts = {name: r.optional(name) for name in ("sector", "group", "campaign",
                                                 "survey_method", "external_id", "comments")}
    start, end = r.dates("start_date"), r.dates("end_date")
    keep = np.flatnonzero(r.ok)
    collars = record_columns(
        CollarColumns, keep.size, name=names[keep], x=x[keep], y=y[keep], z=z[keep],
        depth=depth[keep], hole_type=hole_type[keep], planned=planned[keep],
        grade_control=grade_control[keep], category=object_array(category)[keep],
        priority=object_array(priority)[keep], start_date=start[keep], end_date=end[keep],
        **{name: values[keep] for name, values in texts.items()})
    oriented = keep[~(np.isnan(azimuth[keep]) & np.isnan(inclination[keep]))]
    surveys = record_columns(
        SurveyColumns, oriented.size, hole_name=names[oriented],
        depth=np.zeros(oriented.size), azimuth=azimuth[oriented],
        inclination=inclination[oriented],
        source=np.full(oriented.size, SurveyColumns.code_values("source").index(
            StationSource.COLLAR), dtype=np.int8))
    return r.result(keep.size, r.count - keep.size, collars=collars, surveys=surveys,
                    lines={"collars": r.lines[keep], "surveys": r.lines[oriented]},
                    duplicate_holes=duplicate_names(names[keep].tolist()))


def _read_surveys(r: _Reader) -> RoleRows:
    holes = _holes(r, "hole")
    depth = r.numbers("depth")
    r.span = (depth, depth)
    azimuth, inclination = r.numbers("azimuth"), r.numbers("inclination")
    method, external = r.optional("method"), r.optional("external_id")
    keep = np.flatnonzero(r.ok)
    surveys = record_columns(SurveyColumns, keep.size, hole_name=holes[keep], depth=depth[keep],
                       azimuth=azimuth[keep], inclination=inclination[keep],
                       method=method[keep], external_id=external[keep])
    return r.result(keep.size, r.count - keep.size, surveys=surveys,
                    lines={"surveys": r.lines[keep]})


def _span(r: _Reader) -> tuple[np.ndarray, np.ndarray]:
    start, end = r.numbers("from_m"), r.numbers("to_m")
    r.span = (start, end)
    return start, end


def _read_lithology(r: _Reader) -> RoleRows:
    holes = _holes(r, "hole")
    start, end = _span(r)
    codes = r.keys("code", "falta el código de litología")
    texts = {name: r.optional(name) for name in ("description", "logged_by", "external_id")}
    keep = np.flatnonzero(r.ok)
    lithology = record_columns(IntervalColumns, keep.size, hole_name=holes[keep],
                         from_m=start[keep], to_m=end[keep], code=codes[keep],
                         **{name: values[keep] for name, values in texts.items()})
    return r.result(keep.size, r.count - keep.size, lithology=lithology,
                    lines={"lithology": r.lines[keep]})


_ASSAY_TEXTS = ("sample_id", "lab", "method", "batch", "external_id")


def _read_assays_long(r: _Reader) -> RoleRows:
    holes = _holes(r, "hole")
    start, end = _span(r)
    elements = r.keys("element", "falta el elemento")
    texts = r.texts("value")
    position = r.position("value")
    parsed = parse_column(texts, r.decl.value_rules)
    for row, reason in zip(parsed.rejected_rows.tolist(), parsed.rejected_reasons,
                           strict=True):
        r.fail(row, position, texts[row], reason)
    units, reported_units = r.units(elements)
    others = {name: r.optional(name) for name in _ASSAY_TEXTS}
    keep = np.flatnonzero(r.ok)
    assays = record_columns(
        AssayColumns, keep.size, hole_name=holes[keep], from_m=start[keep], to_m=end[keep],
        element=elements[keep], value=parsed.values[keep], unit=object_array(units)[keep],
        detection_flag=parsed.flags[keep], reported_value=parsed.reported[keep],
        reported_unit=object_array(reported_units)[keep],
        **{name: values[keep] for name, values in others.items()})
    return r.result(keep.size, r.count - keep.size, assays=assays,
                    lines={"assays": r.lines[keep]})


def _read_assays_wide(r: _Reader) -> RoleRows:
    holes = _holes(r, "hole")
    start, end = _span(r)
    others = {name: r.optional(name) for name in _ASSAY_TEXTS}
    elements = r.layout.elements
    count, width = r.count, len(elements)
    values = np.full((count, width), math.nan)
    flags = np.full((count, width), _OK, dtype=np.int8)
    reported = np.empty((count, width), dtype=object)
    valid = np.ones((count, width), dtype=bool)
    units, declared = [], []
    for column, (code, position) in enumerate(elements):
        texts = _column_texts(r.table, position)
        for row in r._excel(texts):
            r.fail(row, position, texts[row], _EXCEL_REASON, record=False)
            valid[row, column] = False
            texts[row] = ""
        parsed = parse_column(texts, r.decl.value_rules)
        for row, reason in zip(parsed.rejected_rows.tolist(), parsed.rejected_reasons,
                               strict=True):
            r.fail(row, position, texts[row], reason, record=False)
            valid[row, column] = False
        values[:, column] = parsed.values
        flags[:, column] = parsed.flags
        reported[:, column] = parsed.reported
        declared.append(r.decl.unit_of(code))
        units.append(grade_unit(declared[-1]))
    chosen = valid & r.ok[:, None]
    rows, columns = np.nonzero(chosen)
    codes = object_array([code for code, _ in elements])
    assays = record_columns(
        AssayColumns, rows.size, hole_name=holes[rows], from_m=start[rows], to_m=end[rows],
        element=codes[columns], value=values[rows, columns], unit=object_array(units)[columns],
        detection_flag=flags[rows, columns], reported_value=reported[rows, columns],
        reported_unit=object_array(declared)[columns],
        **{name: column_values[rows] for name, column_values in others.items()})
    return r.result(rows.size, count * width - rows.size, assays=assays,
                    lines={"assays": r.lines[rows]})


def _codes(r: _Reader) -> np.ndarray:
    codes = r.keys("code", "falta el código")
    r.label = codes.tolist()
    return codes


def _read_lithology_catalog(r: _Reader) -> RoleRows:
    codes = _codes(r)
    description, pattern = r.optional("description"), r.optional("pattern")
    external = r.optional("external_id")
    colors = r.colors("color")
    density = r.numbers("density")
    order = r.integers("sort_order", 0)
    r.repeated(codes, "code")
    keep = np.flatnonzero(r.ok).tolist()
    kind = r.decl.density_kind
    entries = tuple(
        LithologyCode(codes[k], description=description[k], color=colors[k],
                      pattern=pattern[k],
                      density=None if math.isnan(density[k]) else float(density[k]),
                      density_kind=None if math.isnan(density[k]) else kind,
                      sort_order=order[k], external_id=external[k])
        for k in keep)
    return r.result(len(keep), r.count - len(keep), catalogs=Catalogs(lithology=entries))


def _read_element_catalog(r: _Reader) -> RoleRows:
    codes = _codes(r)
    names, external = r.optional("name"), r.optional("external_id")
    units, _ = r.units(codes)
    decimals = r.integers("decimals", 2)
    limit = r.numbers("detection_limit")
    order = r.integers("sort_order", 0)
    r.repeated(codes, "code")
    keep = np.flatnonzero(r.ok).tolist()
    entries = tuple(
        Element(codes[k], units[k], name=names[k], decimals=decimals[k],
                detection_limit=None if math.isnan(limit[k]) else float(limit[k]),
                sort_order=order[k], external_id=external[k])
        for k in keep)
    return r.result(len(keep), r.count - len(keep), catalogs=Catalogs(elements=entries))


_READERS = MappingProxyType({
    TableRole.COLLAR: _read_collars,
    TableRole.SURVEY: _read_surveys,
    TableRole.LITHOLOGY: _read_lithology,
    TableRole.ASSAY_WIDE: _read_assays_wide,
    TableRole.ASSAY_LONG: _read_assays_long,
    TableRole.LITHOLOGY_CATALOG: _read_lithology_catalog,
    TableRole.ELEMENT_CATALOG: _read_element_catalog,
})


def _check_decl(decl: object) -> SourceDeclaration:
    if not isinstance(decl, SourceDeclaration):
        raise TypeError(f"la declaración es un SourceDeclaration, no {decl!r}")
    return decl


def read_role(role: TableRole | str, table: Table, mapping: Mapping[str, str],
              decl: SourceDeclaration) -> RoleRows:
    """Las filas de ``table`` interpretadas como ``role`` con la correspondencia
    ``mapping`` y la declaración ``decl`` (véase el módulo; RF-005-05, RF-005-09). Sin las
    declaraciones que necesita, ``interop.base.DeclarationError`` (RF-005-07); con una
    correspondencia que no vale, :class:`MappingError`. ``table`` no cambia."""
    role = _role(role)
    table = _check_table(table)
    decl = _check_decl(decl)
    layout = _layout(role, table.columns, mapping)
    require_declarations(decl, _needs(role, table, layout), obj=ROLE_LABELS[role])
    return _READERS[role](_Reader(role, table, layout, decl))


# --- Una importación con varias tablas ----------------------------------------------------------


def _stations(collar: RoleRows | None, survey: RoleRows | None, collars: CollarColumns,
              all_vertical: bool) -> SurveyColumns:
    """Las estaciones: la orientación en boca de los sondeos sin desviaciones (spec §8),
    las desviaciones y, con «todos verticales», una vertical a 0 m en cada boca sin
    ninguna."""
    measured = SurveyColumns.empty() if survey is None else survey.surveys
    oriented = SurveyColumns.empty() if collar is None else collar.surveys
    surveyed = {name_key(name) for name in measured.hole_name.tolist()}
    kept = [row for row, name in enumerate(oriented.hole_name.tolist())
            if name_key(name) not in surveyed]
    stations = concat_columns(SurveyColumns, [oriented.take(np.array(kept, dtype=np.int64)),
                                       measured])
    if not all_vertical:
        return stations
    with_station = {name_key(name) for name in stations.hole_name.tolist()}
    names = [name for name in collars.name.tolist() if name_key(name) not in with_station]
    count = len(names)
    vertical = record_columns(
        SurveyColumns, count, hole_name=object_array(names), depth=np.zeros(count),
        azimuth=np.zeros(count), inclination=np.full(count, -90.0),
        source=np.full(count, SurveyColumns.code_values("source").index(
            StationSource.DECLARED_VERTICAL), dtype=np.int8))
    return concat_columns(SurveyColumns, [stations, vertical])


def _warnings(results: Mapping[TableRole, RoleRows]) -> tuple[str, ...]:
    found = [f"{ROLE_LABELS[role]}: la tabla no tiene filas y no se importa"
             for role, rows in results.items() if rows.read == 0]
    collar = results.get(TableRole.COLLAR)
    if collar is not None and collar.duplicate_holes:
        groups = "; ".join(spanish_list([f"«{name}»" for name in group])
                           for group in collar.duplicate_holes)
        found.append(f"{ROLE_LABELS[TableRole.COLLAR]}: sondeos con el nombre repetido "
                     f"(DH-E01), que no pasan a la base: {groups}")
    return tuple(found)


def read_drillholes(
    tables: Mapping[TableRole | str, Table],
    mappings: Mapping[TableRole | str, Mapping[str, str]] | None,
    decl: SourceDeclaration,
    catalogs: Catalogs | None = None,
) -> tuple[DrillholeSet, ImportReport]:
    """El ``DrillholeSet`` de las tablas de una importación (una por papel) y su informe
    (véase el módulo): en el CRS, el datum y los convenios de ``decl`` (sin transformar),
    con ``mappings`` (por papel; ``None``, las de :func:`suggest_mapping`) y los códigos
    nuevos frente a ``catalogs`` (los del proyecto). Sin las declaraciones que necesitan
    las tablas (y siempre el CRS y el datum vertical: un conjunto de sondeos está en uno),
    ``interop.base.DeclarationError`` con todas a la vez. Las tablas no cambian."""
    decl = _check_decl(decl)
    chosen: dict[TableRole, Table] = {}
    for role, table in tables.items():
        role = _role(role)
        if role in chosen:
            raise ValueError(f"dos tablas con el papel «{role}»")
        chosen[role] = _check_table(table)
    given = {} if mappings is None else {_role(role): m for role, m in mappings.items()}
    layouts: dict[TableRole, _Layout] = {}
    total = Needs(crs=True, vertical=True)
    for role in TableRole:
        if role not in chosen:
            continue
        table = chosen[role]
        if mappings is None:
            mapping = suggest_mapping(role, table.columns)
        elif role in given:
            mapping = given[role]
        else:
            raise ValueError(f"falta la correspondencia de columnas de «{role}»")
        layouts[role] = _layout(role, table.columns, mapping)
        total = total | _needs(role, table, layouts[role])
    require_declarations(decl, total, obj=SOURCE_LABEL)
    results = {role: _READERS[role](_Reader(role, chosen[role], layout, decl))
               for role, layout in layouts.items()}

    collar = results.get(TableRole.COLLAR)
    collars = CollarColumns.empty() if collar is None else collar.collars
    stations = _stations(collar, results.get(TableRole.SURVEY), collars, decl.all_vertical)
    lithology = concat_columns(IntervalColumns, [rows.lithology for rows in results.values()])
    assays = concat_columns(AssayColumns, [rows.assays for rows in results.values()])
    found = Catalogs(
        lithology=tuple(e for rows in results.values() for e in rows.catalogs.lithology),
        elements=tuple(e for rows in results.values() for e in rows.catalogs.elements))
    dset = deduce_depths(DrillholeSet(
        crs=decl.crs, vertical=decl.vertical, collars=collars,
        surveys=link_columns(stations, collars), lithology=link_columns(lithology, collars),
        assays=link_columns(assays, collars), catalogs=found))
    report = ImportReport(
        per_table={str(role): rows.counts for role, rows in results.items()},
        rejected=tuple(r for rows in results.values() for r in rows.rejected),
        warnings=_warnings(results),
        unknown_codes=new_codes(dset, catalogs),
        duplicate_holes=() if collar is None else collar.duplicate_holes,
    )
    return dset, report
