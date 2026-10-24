# SPDX-License-Identifier: GPL-3.0-or-later
"""Exportar una cubicación (spec 011, T17; RF-011-24, RF-011-05; RNF-011-06; RF-008-15; plan
011 §2.1, D-29).

Exportar **no es una operación** (D-29): el CSV y la rejilla entregable se escriben desde lo
registrado, también con el proyecto en solo lectura (fuera de él) y desde una versión que ya no
es editable; nada se registra.

**El CSV** (:func:`cubication_export`, :func:`csv_bytes`, :func:`write_csv`), para Excel en
español (RF-011-24): UTF-8 con su BOM (sin ella Excel no muestra bien las tildes), «;» de
separador, filas acabadas en CRLF y los números con **coma decimal**, sin separador de miles ni
exponente: el decimal más corto que vuelve al mismo float64 (el valor exacto, ``repr``; −0 es
«0»). La primera celda es «Cubicación», no «ID» (Excel tomaría el fichero por SYLK).

- La **cabecera**, una fila por dato (la primera celda dice qué es): la cubicación, el proyecto,
  la versión (con su estado) y la revisión (con el suyo), cada operación de la cubicación
  (``res.volume`` y, si reparte por unidades, ``res.tonnage``: su nombre, su revisión, la fecha
  en que terminó y la versión de Geoblender que la calculó), cada entrada que consumieron con su
  papel («Superficie de partida», «Base de Capa útil», «Columna de materiales»…), el nombre del
  dato y el hash de contenido que se consumió (una cota constante, sin hash), cada parámetro que
  leyeron (su nombre, su clave, el valor leído, su unidad, su tipo, «sin confirmar» y su ámbito:
  «proyecto» o la versión), la fecha de la exportación y la versión de Geoblender que exporta.
- Una fila vacía y la **tabla**: sus títulos (:data:`TABLE_HEADER`) y **una fila por valor** de
  las tablas registradas, la de volúmenes (``res_vol_``) y la de toneladas (``res_ton_``), en su
  orden: la tabla, el ámbito (el dominio —«Todos los dominios», «Fuera de los dominios» o su
  valor—, la rodaja, la unidad y el componente con sus códigos y su nombre en la columna de
  materiales del proyecto), la clave del dato y su nombre en español
  (``reserves.table.QUANTITIES``), el valor (vacío si no se puede dar), su unidad, su tipo
  (CALCULADO) y las marcas de su operación de hoy (RF-008-31: «depende de una hipótesis»,
  «depende de un valor sin confirmar», «obsoleta»), y sus notas («sin densidad»…).
- **Una cubicación por momentos** (T38; RF-011-19, F-3 de la verificación): su tabla
  (``res_stg_``) con una columna más tras «Tabla», «Momento» (:data:`STAGE_TABLE_HEADER`: el
  momento de cada fila; vacío en las que comparan su suma con la directa), y en la cabecera su
  ``res.stages``, cada momento y la directa («Momento 1 «Explotación»», «Cubicación directa
  «Directa»»: su tabla de volúmenes y el hash consumido) y la tolerancia que leyó.

**El panel de la cubicación** (T25; RF-011-23) lee lo mismo (:func:`cubication_export` con el
idioma de Geoblender) y enseña sus filas sin las de las toneladas que repiten los m³ in situ de
la tabla de volúmenes (:func:`shown_rows`).

**La rejilla de diferencias** (:func:`export_difference_steps`, :func:`export_difference`;
RF-011-05, RF-006-24): la registrada (``rasters/res_dif_…``, Float64 con NaN) como GeoTIFF del
perfil ``deliverable`` de la 006 (Float32, −9999), con ``gis.geotiff.writer.write_steps`` (un
paso por tesela).

**El destino** (:func:`check_target`, antes de escribir nada): con su extensión
(``gis.export_extension_invalid``); dentro del proyecto, solo en ``exports/``
(``gis.export_inside_project``) y nunca con el proyecto en solo lectura
(``res.export_read_only_project``); la guarda de las escrituras de la 008
(``core.inputs.check_write_target``: ni sobre una entrada, ni en la carpeta de su fuente, ni en
una carpeta de solo lectura; RF-008-15); y sobre un fichero que ya existe, solo con
``overwrite`` (``gis.export_target_exists``: quien exporta pregunta). Se escribe en un temporal
(``<destino>.tmp``, en la misma carpeta) con ``fsync`` y ``os.replace``: si otro programa tiene
abierto el destino (Excel, QGIS), ``gis.raster_target_locked`` y el anterior intacto; un fallo
del disco, ``gis.raster_write_failed``; en los dos, sin temporal. Python puro (nivel 9).
"""

from __future__ import annotations

import csv
import io
import math
import os
import sqlite3
import sys
from collections.abc import Generator, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from ..core.datasets import registry as dataset_registry
from ..core.datasets.model import DatasetRecord
from ..core.i18n import translate
from ..core.inputs.guard import GuardProject, check_write_target
from ..core.params.model import ParamKind, parameter_label
from ..core.paths import ReadOnlyDirs, check_path_length
from ..core.provenance.lineage import OperationLink, lineage
from ..core.timeutil import format_utc, parse_utc
from ..core.units import UNITS, symbol
from ..core.versions import read as versions_read
from ..core.versions.model import Version, VersionError
from ..gis.geotiff.reader import read_geotiff
from ..gis.geotiff.writer import target_locked, temporary_path, write_failed, write_steps
from ..gis.messages import GisError
from ..gis.provenance import dataset_slug, export_locator, inside_project
from ..gis.raster import Raster
from ..gis.store import project_references
from . import provenance as declared
from .materials import read_column
from .messages import MESSAGES, ResError, render
from .table import ALL_DOMAINS, OUTSIDE_DOMAINS, QUANTITIES, Row, read_rows, read_stage_rows
from .volumes import FINAL, OUTSIDE_SCOPE, START

__all__ = [
    "CALCULATED",
    "CSV_SUFFIXES",
    "DIFFERENCE_SUFFIXES",
    "ENCODING",
    "SEPARATOR",
    "STAGE_TABLE_HEADER",
    "TABLE_HEADER",
    "CubicationExport",
    "ExportHeader",
    "ExportRow",
    "UsedInput",
    "UsedOperation",
    "UsedParameter",
    "check_target",
    "csv_bytes",
    "csv_rows",
    "cubication_export",
    "export_difference",
    "export_difference_steps",
    "shown_rows",
    "write_csv",
]

LANGUAGE = "es"
"""El idioma del CSV (RF-011-24: Excel en español)."""
ENCODING = "utf-8-sig"
"""UTF-8 con su marca de orden de bytes."""
SEPARATOR = ";"
LINE_END = "\r\n"
DECIMAL_MARK = ","
JOIN = " · "
"""Separa las marcas y las notas de una fila."""
CALCULATED = str(ParamKind.CALCULADO)
"""El tipo de cada valor de las tablas: lo produce su operación."""
CSV_SUFFIXES: tuple[str, ...] = (".csv",)
DIFFERENCE_SUFFIXES: tuple[str, ...] = (".tif", ".tiff")
"""Las extensiones de cada entregable."""

TABLE_HEADER: tuple[str, ...] = (
    "Tabla", "Dominio", "Cota inferior de la rodaja (m)", "Cota superior de la rodaja (m)",
    "Unidad", "Componente", "Nombre", "Clave del dato", "Dato", "Valor", "Unidad de medida",
    "Tipo", "Marcas", "Nota",
)
"""Los títulos de la tabla del CSV, en su orden."""
STAGE_TABLE_HEADER: tuple[str, ...] = (TABLE_HEADER[0], "Momento", *TABLE_HEADER[1:])
"""Los de la tabla de una cubicación por momentos: «Momento» tras «Tabla» (T38)."""

_TARGET = "destino"
_EXTENSION = "extensión"
_DOMAINS = {ALL_DOMAINS: "Todos los dominios", OUTSIDE_DOMAINS: OUTSIDE_SCOPE}
_REVISION_STATES = {"open": "abierta", "frozen": "congelada", "closed": "cerrada"}
_UNCONFIRMED = "sin confirmar"
_PROJECT_SCOPES = {"es": "proyecto", "en": "project"}
"""El ámbito «proyecto» de un parámetro, en cada idioma de Geoblender."""
REPEATED_TOLERANCE = 1e-12
"""Cuánto (relativo) puede diferir de la de volúmenes la fila de toneladas que la repite: el
redondeo de sumar los m³ de los componentes de una compuesta (``reserves.tonnage``)."""
_YES_NO = ("no", "sí")
_LOCAL = "%d/%m/%Y %H:%M"
_ROLES = {
    START: "Superficie de partida",
    FINAL: "Superficie final",
    declared.MATERIALS_ROLE: "Columna de materiales",
    declared.VOLUMES_ROLE: "Tabla de volúmenes",
    declared.SCOPE_ROLE: "Ámbito",
    declared.DOMAINS_ROLE: "Capa de dominios",
    declared.DIRECT_ROLE: "Cubicación directa",
}
_UNIT_ROLES = (("base_", "Base de"), ("thickness_", "Espesor de"))
_STAGE_ROLE = "stage_"
"""El comienzo del papel de la tabla de un momento (``reserves.provenance.stage_role``)."""


class ExportProject(GuardProject, Protocol):
    """Lo que la exportación usa del proyecto (``core.project.Project``): lo de la guarda de las
    escrituras, su nombre, su reloj y su sesión (quién exporta, con qué Geoblender), si se puede
    escribir y su fila de ``gb_project`` (el CRS horizontal y la referencia vertical)."""

    @property
    def name(self) -> str: ...

    @property
    def clock(self) -> Any: ...

    @property
    def session(self) -> Any: ...

    @property
    def writable(self) -> bool: ...

    @property
    def record(self) -> Any: ...


# --- Lo que se exporta ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UsedOperation:
    """Una operación de la cubicación: su uid y su tipo, su nombre en español, su revisión
    («V01.r1»), cuándo terminó (UTC), con qué Geoblender y sus marcas de hoy (en español)."""

    uid: str
    op_type: str
    label: str
    revision: str
    finished_at: str | None
    geoblender_version: str
    marks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UsedInput:
    """Lo que consumió la cubicación: su papel, cómo se nombra en español, el dato (o la cota
    constante, en texto) y el hash de contenido consumido (``""`` en una cota constante)."""

    role: str
    label: str
    dataset: str
    content_sha256: str


@dataclass(frozen=True, slots=True)
class UsedParameter:
    """Un parámetro que leyó la cubicación: su clave, su nombre en español, el valor leído con
    su unidad, su tipo, si estaba «sin confirmar» y su ámbito («proyecto» o la versión)."""

    key: str
    label: str
    value: Any
    unit: str
    kind: ParamKind
    unconfirmed: bool
    scope: str


@dataclass(frozen=True, slots=True)
class ExportHeader:
    """La cabecera del CSV (véase el módulo): la cubicación, el proyecto, la versión y su
    estado, la revisión y el suyo, las operaciones, lo que consumieron y los parámetros que
    leyeron, cuándo se exporta (UTC) y con qué Geoblender."""

    cubication: str
    project: str
    version: str
    version_status: str
    revision: str
    revision_state: str
    operations: tuple[UsedOperation, ...]
    inputs: tuple[UsedInput, ...]
    parameters: tuple[UsedParameter, ...]
    exported_at: str
    geoblender_version: str


@dataclass(frozen=True, slots=True)
class ExportRow:
    """Una fila de la tabla del CSV: la tabla de la que sale (su nombre en español), la fila
    registrada, el nombre de su unidad o componente, las marcas de su operación y, en una
    cubicación por momentos, su momento (``None``: las que comparan la suma con la directa, o
    no es de momentos)."""

    table: str
    row: Row
    name: str
    marks: tuple[str, ...]
    stage: str | None = None


@dataclass(frozen=True, slots=True)
class CubicationExport:
    """Lo que escribe el CSV de una cubicación: su cabecera, sus filas y si es una cubicación
    por momentos (su tabla lleva la columna «Momento», T38)."""

    header: ExportHeader
    rows: tuple[ExportRow, ...]
    stages: bool = False

    @property
    def default_name(self) -> str:
        """El fichero que se propone (D-29): ``<cubicación>_<revisión>.csv``, con el nombre de
        la cubicación en ASCII (``mensual_octubre_V03.r1.csv``), para ``exports/``."""
        return f"{dataset_slug(self.header.cubication)}_{self.header.revision}{CSV_SUFFIXES[0]}"


# --- Leer lo registrado --------------------------------------------------------------------


def _version(conn: sqlite3.Connection, version: object) -> Version:
    if not isinstance(version, str) or not version:
        raise TypeError(f"la versión se indica por su uid o su código, no {version!r}")
    found = versions_read.version(conn, version)
    if found is None:
        raise VersionError("core.version_unknown", field="versión", value=version,
                           version=version)
    return found


def _record(conn: sqlite3.Connection, family: str, name: str,
            version: Version) -> DatasetRecord | None:
    """El dato vivo de la familia ``family`` de la cubicación ``name`` en ``version``."""
    dataset = declared.dataset_name(family, name)
    record = dataset_registry.get(conn, dataset, version_uid=version.uid)
    return record if record is not None and record.name == dataset else None


def _revision_of(conn: sqlite3.Connection, operation_uid: str) -> Any:
    row = conn.execute("SELECT revision_uid FROM gb_operation WHERE uid = ?",
                       (operation_uid,)).fetchone()
    return None if row is None or not row[0] else versions_read.revision(conn, str(row[0]))


def _role_label(role: str | None, names: Mapping[str, str]) -> str:
    if role is None:
        return ""
    if role in _ROLES:
        return _ROLES[role]
    if role.startswith(_STAGE_ROLE) and role.removeprefix(_STAGE_ROLE).isdigit():
        return f"Momento {role.removeprefix(_STAGE_ROLE)}"
    for prefix, label in _UNIT_ROLES:
        if role.startswith(prefix):
            code = role.removeprefix(prefix)
            return f"{label} {names.get(code, code)}"
    return role


def _constant(settings: Mapping[str, Any], role: str) -> UsedInput | None:
    """La cota constante del papel ``role`` en los ajustes de la cubicación (o ninguna)."""
    value = settings.get(role)
    if not isinstance(value, Mapping) or value.get("elevation_m") is None:
        return None
    text = f"Cota constante: {_number(float(value['elevation_m']))} m"
    return UsedInput(role, _ROLES[role], text, "")


def _operation_label(op_type: str, language: str = LANGUAGE) -> str:
    found = declared.OPERATION_TYPES_BY_NAME.get(op_type)
    return op_type if found is None else translate(language, found.label_msgid)


def cubication_export(project: ExportProject, name: str, *, version: str,
                      language: str = LANGUAGE) -> CubicationExport:
    """Lo que escribe el CSV de la cubicación ``name`` de la versión ``version`` (uid o
    código): lo registrado (véase el módulo), leído en una instantánea sin escribir nada. Con
    unidades (los ajustes de su ``res.volume``), también su tabla de toneladas, si la hay. Si
    ``name`` no es una cubicación de la versión pero sí una cubicación por momentos, su tabla
    ``res_stg_`` (T38; la de volúmenes manda si se llaman igual).
    ``ResError`` ``res.cubication_unknown`` si esa versión no tiene la cubicación;
    ``VersionError`` ``core.version_unknown`` si la versión no existe. Las marcas, el nombre de
    cada operación y de cada parámetro y el ámbito «proyecto», en ``language`` (el del CSV, el
    español; el panel de la cubicación lo lee en el de Geoblender, T25)."""
    if not isinstance(name, str) or not name.strip():
        raise TypeError(f"una cubicación se indica por su nombre, no {name!r}")
    if language not in _PROJECT_SCOPES:
        raise ValueError(f"el idioma «{language}» no es de Geoblender: "
                         f"{', '.join(_PROJECT_SCOPES)}")
    with project.read() as conn:
        found = _version(conn, version)
        volume = _record(conn, declared.VOLUMES, name, found)
        staged = None if volume is not None else _record(conn, declared.STAGE_TABLE, name,
                                                         found)
        first = volume if volume is not None else staged
        if first is None:
            raise ResError("res.cubication_unknown", obj=name, field="cubicación", value=name,
                           version=found.code)
        column = read_column(conn)
        units = {} if column is None else {unit.code: unit.name for unit in column.units}
        parts = {} if column is None else {(unit.code, item.code): item.name
                                           for unit in column.units for item in unit.components}
        tables: list[tuple[str, DatasetRecord, OperationLink, tuple[str, ...]]] = []
        root, marks = _producer(project, conn, first, language)
        family = declared.VOLUMES if staged is None else declared.STAGE_TABLE
        tables.append((declared.FAMILIES_BY_CODE[family].label, first, root, marks))
        if staged is None and root.settings.get("units"):
            tonnage = _record(conn, declared.TONNES, name, found)
            if tonnage is not None:
                tables.append((declared.FAMILIES_BY_CODE[declared.TONNES].label, tonnage,
                               *_producer(project, conn, tonnage, language)))
        operations: list[UsedOperation] = []
        rows: list[ExportRow] = []
        for label, record, link, marks in tables:
            revision = _revision_of(conn, link.uid)
            shown = "" if revision is None else revision.label(found.code)
            operations.append(UsedOperation(
                link.uid, link.op_type, _operation_label(link.op_type, language), shown,
                link.finished_at, link.geoblender_version, marks))
            found_rows = ([(None, item) for item in read_rows(conn, record.locator)]
                          if staged is None else
                          [(item.stage, item.row)
                           for item in read_stage_rows(conn, record.locator)])
            for stage, item in found_rows:
                if item.component is not None:
                    named = parts.get((item.unit or "", item.component), "")
                else:
                    named = units.get(item.unit or "", "")
                rows.append(ExportRow(label, item, named, marks, stage))
        own = _revision_of(conn, root.uid)
    header = ExportHeader(
        cubication=name,
        project=project.name,
        version=found.label,
        version_status=str(found.status),
        revision="" if own is None else own.label(found.code),
        revision_state="" if own is None else _REVISION_STATES.get(str(own.state),
                                                                   str(own.state)),
        operations=tuple(operations),
        inputs=_inputs([item[2] for item in tables], units),
        parameters=_parameters([item[2] for item in tables], found.code, language),
        exported_at=format_utc(project.clock.now()),
        geoblender_version=str(project.session.geoblender_version),
    )
    return CubicationExport(header, tuple(rows), stages=staged is not None)


def shown_rows(export: CubicationExport) -> tuple[ExportRow, ...]:
    """Las filas de ``export`` que enseña el panel de la cubicación (T25; RF-011-23, D-16): todas
    menos las de la tabla de toneladas que repiten los m³ in situ de una unidad entera de la de
    volúmenes (su ``volume_m3`` y, de lo in situ, su ``in_situ_m3``: el mismo valor, salvo el
    redondeo de sumar los componentes de una compuesta, :data:`REPEATED_TOLERANCE`, en el mismo
    dominio y la misma rodaja). Los m³ in situ son los de ``res.volume``, con sus marcas: un K
    HIPÓTESIS marca las toneladas, no esos m³. En su orden."""
    tonnes = declared.FAMILIES_BY_CODE[declared.TONNES].label
    volumes = {(row.domain, row.bench_z0, row.bench_z1, row.unit): row.value
               for row in (item.row for item in export.rows if item.table != tonnes)
               if row.quantity == "volume_m3" and row.unit is not None and row.component is None}

    def repeated(item: ExportRow) -> bool:
        row = item.row
        if item.table != tonnes or row.unit is None or row.component is not None:
            return False
        if row.quantity not in ("volume_m3", "in_situ_m3"):
            return False
        key = (row.domain, row.bench_z0, row.bench_z1, row.unit)
        volume = volumes.get(key)
        return volume is not None and row.value is not None and math.isclose(
            row.value, volume, rel_tol=REPEATED_TOLERANCE, abs_tol=0.0)

    return tuple(item for item in export.rows if not repeated(item))


def _producer(project: ExportProject, conn: sqlite3.Connection, record: DatasetRecord,
              language: str = LANGUAGE) -> tuple[OperationLink, tuple[str, ...]]:
    """La operación que escribió el contenido actual de ``record``, con su procedencia, y sus
    marcas de hoy (RF-008-31), en ``language``."""
    tree = lineage(project, record.operation_uid, conn=conn, language=language)
    return tree.operations[tree.root], tree.marks.texts(language=language)


def _inputs(links: Sequence[OperationLink], units: Mapping[str, str]) -> tuple[UsedInput, ...]:
    """Lo que consumieron las operaciones ``links``, en su orden y sin repetir: las cotas
    constantes de sus superficies y cada dato con el hash consumido."""
    found: dict[tuple[str, str, str], UsedInput] = {}
    for link in links:
        for role in (START, FINAL):
            constant = _constant(link.settings, role)
            if constant is not None:
                found.setdefault((role, constant.dataset, ""), constant)
        compared = _compared(link)
        for item in link.consumed:
            role = item.role or ""
            label = _role_label(item.role, units)
            if role in compared:
                label = f"{label} «{compared[role]}»"
            found.setdefault((role, item.name, item.content_sha256), UsedInput(
                role, label, item.name, item.content_sha256))
    return tuple(found.values())


def _compared(link: OperationLink) -> dict[str, str]:
    """Las cubicaciones que compara una ``res.stages`` por papel (``stage_1``…, ``direct``),
    de sus ajustes; de otra operación, ninguna."""
    if link.op_type != declared.STAGES:
        return {}
    moments, direct = link.settings.get("moments"), link.settings.get("direct")
    found = {declared.stage_role(position): str(moment)
             for position, moment in enumerate(moments if isinstance(moments, list) else (),
                                               start=1)}
    if isinstance(direct, str):
        found[declared.DIRECT_ROLE] = direct
    return found


def _parameters(links: Sequence[OperationLink], version_code: str,
                language: str = LANGUAGE) -> tuple[UsedParameter, ...]:
    """Los parámetros que leyeron las operaciones ``links``, en su orden y una vez cada uno."""
    found: dict[str, UsedParameter] = {}
    for link in links:
        for used in link.params:
            if used.key in found:
                continue
            found[used.key] = UsedParameter(
                used.key, parameter_label(used.key, language) or used.key, used.value,
                used.unit, used.kind, used.unconfirmed,
                _PROJECT_SCOPES[language] if used.scope == "project" else version_code)
    return tuple(found.values())


# --- El CSV --------------------------------------------------------------------------------


def _number(value: float) -> str:
    """Un número con coma decimal: el decimal más corto que vuelve al mismo float64, sin
    exponente ni separador de miles; −0, «0»; un valor que no es finito, vacío (no lo hay en
    las tablas: RF-011-22)."""
    if not math.isfinite(value):
        return ""
    text = np.format_float_positional(value, unique=True, trim="-")
    if text == "-0":
        text = "0"
    return text.replace(".", DECIMAL_MARK)


def _optional(value: float | None) -> str:
    return "" if value is None else _number(float(value))


def _value(value: Any) -> str:
    """El valor de un parámetro como celda: un número con coma, «sí» o «no», el texto o, de
    una lista, sus elementos separados por «; »."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return _YES_NO[value]
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _number(value)
    if isinstance(value, tuple | list):
        return "; ".join(_value(item) for item in value)
    return str(value)


def _symbol(unit: str) -> str:
    return symbol(unit) if unit in UNITS else unit


def _local(moment: str | None) -> str:
    """Una hora UTC guardada, en hora local («23/10/2026 14:05»)."""
    if not moment:
        return ""
    try:
        return parse_utc(moment).astimezone().strftime(_LOCAL)
    except ValueError:
        return moment


def _note(code: str) -> str:
    return render(code, language=LANGUAGE) if code in MESSAGES else code


def csv_rows(export: CubicationExport) -> list[tuple[str, ...]]:
    """Las filas del CSV de ``export`` como textos (véase el módulo): la cabecera, una fila
    vacía, los títulos de la tabla y una fila por valor."""
    header = export.header
    found: list[tuple[str, ...]] = [
        ("Cubicación", header.cubication),
        ("Proyecto", header.project),
        ("Versión", header.version, header.version_status),
        ("Revisión", header.revision, header.revision_state),
    ]
    found += [("Operación", item.label, item.revision, _local(item.finished_at),
               item.geoblender_version) for item in header.operations]
    found += [("Entrada", item.label, item.dataset, item.content_sha256)
              for item in header.inputs]
    found += [("Parámetro", item.label, item.key, _value(item.value), _symbol(item.unit),
               str(item.kind), _UNCONFIRMED if item.unconfirmed else "", item.scope)
              for item in header.parameters]
    found += [("Fecha de la exportación", _local(header.exported_at)),
              ("Versión de Geoblender", header.geoblender_version), (),
              STAGE_TABLE_HEADER if export.stages else TABLE_HEADER]
    labels = {key: translate(LANGUAGE, quantity.label) if quantity.label else key
              for key, quantity in QUANTITIES.items()}
    symbols: dict[str, str] = {}
    notes: dict[str | None, str] = {None: ""}
    for item in export.rows:
        row = item.row
        unit = symbols.get(row.unit_code)
        if unit is None:
            unit = symbols[row.unit_code] = _symbol(row.unit_code)
        note = notes.get(row.note)
        if note is None:
            note = notes[row.note] = JOIN.join(_note(code) for code in row.notes)
        cells = (
            _DOMAINS.get(row.domain, row.domain), _optional(row.bench_z0),
            _optional(row.bench_z1), row.unit or "", row.component or "", item.name,
            row.quantity, labels.get(row.quantity, row.quantity), _optional(row.value), unit,
            CALCULATED, JOIN.join(item.marks), note,
        )
        found.append((item.table, item.stage or "", *cells) if export.stages
                     else (item.table, *cells))
    return found


def csv_bytes(export: CubicationExport) -> bytes:
    """El CSV de ``export`` tal como lo escribe :func:`write_csv`: BOM de UTF-8, «;» y CRLF."""
    stream = io.StringIO(newline="")
    csv.writer(stream, delimiter=SEPARATOR, lineterminator=LINE_END).writerows(
        csv_rows(export))
    return stream.getvalue().encode(ENCODING)


# --- El destino y la escritura -------------------------------------------------------------


def check_target(path: str | os.PathLike[str], *, project: ExportProject,
                 read_only: ReadOnlyDirs, overwrite: bool, suffixes: Sequence[str],
                 label: str) -> Path:
    """El destino ``path`` de un entregable ``label`` («CSV», «GeoTIFF») con una de
    ``suffixes``, comprobado sin escribir nada (véase el módulo): ``GisError``
    ``gis.export_extension_invalid``, ``gis.export_inside_project`` o
    ``gis.export_target_exists``; ``ResError`` ``res.export_read_only_project``;
    ``ProvenanceError`` ``core.write_target_*`` (RF-008-15); ``core.path_too_long``."""
    if not isinstance(overwrite, bool):
        raise TypeError(f"«overwrite» es verdadero o falso, no {overwrite!r}")
    target = Path(path)
    name = target.name
    if target.suffix.lower() not in suffixes:
        raise GisError("gis.export_extension_invalid", obj=name, field=_EXTENSION,
                       value=target.suffix or "—", file=name, format=label,
                       expected="/".join(suffixes))
    root = Path(project.root)
    if inside_project(root, target):
        if not project.writable:
            raise ResError("res.export_read_only_project", obj=name, field=_TARGET, value=name,
                           project=project.name)
        if export_locator(root, target) is None:
            raise GisError("gis.export_inside_project", obj=name, field=_TARGET, value=name,
                           file=name, project=project.name)
    check_write_target(target, project=project, read_only=read_only)
    check_path_length(temporary_path(target), obj=name)
    if not overwrite and target.exists():
        raise GisError("gis.export_target_exists", obj=name, field=_TARGET, value=name,
                       file=name)
    return target


def _discard(temporary: Path) -> None:
    try:
        temporary.unlink(missing_ok=True)
    except OSError:
        pass


def _write_bytes(data: bytes, target: Path) -> None:
    """``data`` en ``target`` por su temporal, ``fsync`` y ``os.replace`` (véase el módulo)."""
    name = target.name
    temporary = temporary_path(target)
    try:
        with temporary.open("wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException as error:
        _discard(temporary)
        if isinstance(error, OSError):
            raise write_failed(name, error) from None
        raise
    try:
        os.replace(temporary, target)
    except OSError as error:
        _discard(temporary)
        if isinstance(error, PermissionError):  # Windows: otro programa lo tiene abierto
            raise target_locked(name) from None
        raise write_failed(name, error) from None


def write_csv(export: CubicationExport, path: str | os.PathLike[str], *,
              project: ExportProject, read_only: ReadOnlyDirs,
              overwrite: bool = False) -> Path:
    """Escribe el CSV de ``export`` (de ``project``) en ``path`` y lo devuelve: el destino,
    comprobado (:func:`check_target`, con ``read_only``, las carpetas de solo lectura), por un
    temporal; sobre uno que existe, solo con ``overwrite`` (véase el módulo)."""
    if not isinstance(export, CubicationExport):
        raise TypeError(f"se exporta una CubicationExport, no {type(export).__name__}")
    target = check_target(path, project=project, read_only=read_only, overwrite=overwrite,
                          suffixes=CSV_SUFFIXES, label="CSV")
    _write_bytes(csv_bytes(export), target)
    return target


# --- La rejilla de diferencias -------------------------------------------------------------


def _difference_file(project: ExportProject, name: str, version: str) -> Path:
    """El fichero registrado de la rejilla de diferencias ``name`` de ``version``."""
    if not isinstance(name, str) or not name.strip():
        raise TypeError(f"una rejilla de diferencias se indica por su nombre, no {name!r}")
    with project.read() as conn:
        found = _version(conn, version)
        record = _record(conn, declared.DIFFERENCE_GRID, name, found)
    if record is None:
        raise ResError("res.difference_unknown", obj=name, field="rejilla", value=name,
                       version=found.code)
    path = Path(project.root).joinpath(*record.locator.split("/"))
    if not path.is_file():
        raise GisError("gis.dataset_file_missing", obj=record.name, field="fichero",
                       value=path.name, file=path.name, name=record.name)
    return path


def export_difference_steps(project: ExportProject, name: str, path: str | os.PathLike[str],
                            *, version: str, read_only: ReadOnlyDirs,
                            overwrite: bool = False) -> Generator[float, None, Path]:
    """La rejilla de diferencias ``name`` de la versión ``version`` (uid o código) a GeoTIFF
    entregable en ``path``, por pasos (RF-011-05, RF-006-24): al llamar, sin escribir nada, la
    rejilla registrada (``res.difference_unknown``) y el destino (:func:`check_target`); el
    primer paso la lee y cada uno de los siguientes escribe una tesela
    (``gis.geotiff.writer.write_steps``: su avance, de 0 a 1); el último la pone en su sitio y
    devuelve ``path`` (``StopIteration.value``). Cerrar los pasos antes no deja nada."""
    source = _difference_file(project, name, version)
    target = check_target(path, project=project, read_only=read_only, overwrite=overwrite,
                          suffixes=DIFFERENCE_SUFFIXES, label="GeoTIFF")
    return _difference_steps(project, source, target)


def _difference_steps(project: ExportProject, source: Path,
                      target: Path) -> Generator[float, None, Path]:
    found = read_geotiff(source, max_cells=sys.maxsize)
    crs, vertical = project_references(project)
    raster = Raster(found.grid, found.values, found.declared_crs or crs,
                    found.declared_vertical or vertical)
    yield 0.0
    return (yield from write_steps(raster, target, profile="deliverable"))


def export_difference(project: ExportProject, name: str, path: str | os.PathLike[str], *,
                      version: str, read_only: ReadOnlyDirs, overwrite: bool = False) -> Path:
    """:func:`export_difference_steps` de una vez: devuelve ``path``."""
    steps = export_difference_steps(project, name, path, version=version,
                                    read_only=read_only, overwrite=overwrite)
    with closing(steps):
        while True:
            try:
                next(steps)
            except StopIteration as stop:
                return stop.value  # type: ignore[no-any-return]
