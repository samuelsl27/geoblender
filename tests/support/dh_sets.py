# SPDX-License-Identifier: GPL-3.0-or-later
"""Conjuntos de sondeos de ``tests/data/dh`` para las pruebas de la validación (spec 005, T08
y T09; plan 005 §7).

No es el lector de la importación (T14): monta el ``DrillholeSet`` de los ficheros de
``csv_basico`` y de cada caso de ``csv_errores`` **tal como están** (sin convertir unidades
ni ángulos: la declaración de ``csv_basico`` es la de los convenios internos), como lo dejaría
el lector con la declaración de ``esperado.json``:

- la orientación en boca de la tabla de bocas, una estación ``collar`` a 0 m;
- con ``all_vertical``, una estación ``declared_vertical`` (0°, −90°) a 0 m en cada boca sin
  estaciones ni orientación en boca (ya en los convenios internos: contrato de T04);
- los análisis en columnas (``assay_wide``, con la unidad de la declaración) o en filas
  (``assay_long``), con ``drillholes.values.parse_column`` («<x», «>x», vacíos);
- los catálogos de litologías (densidad ADOPTADO) y de elementos;
- la profundidad que falta, deducida con ``drillholes.validate.deduce_depths`` (DH-W16).

:func:`error_case` da además los umbrales, la ventana de trabajo y, en DH-W15, la posición de
las bocas en la capa; :func:`expected_value` interpreta el «value» (texto de la fuente) de una
incidencia esperada como lo da ``Issue.value``.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np

from tests.support.package import import_geoblender
from tests.support.repo import ROOT

model = import_geoblender("drillholes.model")
values = import_geoblender("drillholes.values")
validate = import_geoblender("drillholes.validate")
georef = import_geoblender("core.georef")
csv_tables = import_geoblender("interop.csv_tables")

DATA = ROOT / "tests" / "data" / "dh"
BASICO = DATA / "csv_basico"
ERRORES = DATA / "csv_errores"

CATALOG = georef.load_catalog()
H25830 = CATALOG.horizontal(25830)
V5782 = CATALOG.vertical(5782)

SEPARATOR = ";"
DECIMAL = ","
DATE_FORMAT = "%d/%m/%Y"
YES = "sí"

NUMERIC_FIELDS = frozenset({"x", "y", "z", "depth", "azimuth", "inclination", "from_m",
                            "to_m", "value", "density"})
"""Los campos numéricos de las incidencias: su «value» es un número (vacío, «»)."""
BOOL_FIELDS = frozenset({"planned", "grade_control"})


def _read(path: Path) -> Any:
    return csv_tables.read_table(path, encoding="utf-8", separator=SEPARATOR)


@cache
def basico_expected() -> Mapping[str, Any]:
    return json.loads((BASICO / "esperado.json").read_text(encoding="utf-8"))


@cache
def errores_expected() -> Mapping[str, Any]:
    return json.loads((ERRORES / "esperado.json").read_text(encoding="utf-8"))


@cache
def basico_tables() -> Mapping[str, Any]:
    """Las tablas de ``csv_basico`` por papel (``collar``, ``survey``…)."""
    return {role: _read(BASICO / name) for role, name in basico_expected()["files"].items()}


def _number(text: str) -> float:
    """Un número de los CSV de prueba (coma decimal); vacío, NaN."""
    text = text.strip()
    return float(text.replace(",", ".")) if text else float("nan")


def _optional(text: str) -> float | None:
    found = _number(text)
    return None if found != found else found


def _date(text: str) -> dt.date | None:
    return dt.datetime.strptime(text, DATE_FORMAT).date() if text else None


def _columns(table: Any) -> dict[str, int]:
    return {name: index for index, name in enumerate(table.columns)}


def _collars(table: Any) -> tuple[list[Any], list[Any]]:
    """Las bocas y las estaciones de su orientación en boca."""
    col = _columns(table)
    collars, stations = [], []
    for row in table.rows:
        name = row[col["Sondeo"]]
        collars.append(model.Collar(
            name, _optional(row[col["X"]]), _optional(row[col["Y"]]),
            _optional(row[col["Z"]]), _optional(row[col["Profundidad"]]),
            hole_type=row[col["Tipo"]] or None, planned=row[col["Planificado"]] == YES,
            campaign=row[col["Campaña"]] or None,
            start_date=_date(row[col["Fecha inicio"]]),
            end_date=_date(row[col["Fecha fin"]])))
        if row[col["Azimut"]]:
            stations.append(model.SurveyStation(
                name, 0.0, _number(row[col["Azimut"]]), _number(row[col["Inclinación"]]),
                source="collar"))
    return collars, stations


def _surveys(table: Any) -> list[Any]:
    return [model.SurveyStation(name, _number(depth), _number(azimuth), _number(inclination))
            for name, depth, azimuth, inclination in table.rows]


def _lithology(table: Any) -> list[Any]:
    return [model.LithologyInterval(name, _number(start), _number(end), code)
            for name, start, end, code in table.rows]


def _assay_rows(holes, starts, ends, samples, elements, texts, units) -> list[Any]:
    parsed = values.parse_column(texts, model.ValueRules(decimal_mark=DECIMAL))
    assert not parsed.rejected_rows.size, parsed.rejected_reasons
    rows = []
    for k, hole in enumerate(holes):
        value = float(parsed.values[k])
        rows.append(model.AssayValue(
            hole, _number(starts[k]), _number(ends[k]), elements[k],
            None if value != value else value, units[k],
            detection_flag=values.FLAGS[int(parsed.flags[k])],
            reported_value=parsed.reported[k], reported_unit=units[k],
            sample_id=samples[k]))
    return rows


def _assays_long(table: Any) -> list[Any]:
    columns = list(zip(*table.rows, strict=True)) if table.rows else [()] * 7
    return _assay_rows(*columns)


def _assays_wide(table: Any, units: Mapping[str, str]) -> list[Any]:
    holes, starts, ends, samples, elements, texts, found_units = ([] for _ in range(7))
    codes = table.columns[4:]
    for row in table.rows:
        for offset, code in enumerate(codes):
            holes.append(row[0])
            starts.append(row[1])
            ends.append(row[2])
            samples.append(row[3])
            elements.append(code)
            texts.append(row[4 + offset])
            found_units.append(units[code])
    return _assay_rows(holes, starts, ends, samples, elements, texts, found_units)


def _catalogs(lithology: Any, elements: Any, density_kind: str) -> Any:
    codes = []
    for code, description, color, density, order in lithology.rows:
        value = _optional(density)
        codes.append(model.LithologyCode(
            code, description=description or None, color=color, density=value,
            density_kind=None if value is None else density_kind, sort_order=int(order)))
    found = []
    for code, name, unit, decimals, limit in elements.rows:
        found.append(model.Element(code, unit, name=name or None, decimals=int(decimals),
                                   detection_limit=_optional(limit)))
    return model.Catalogs(lithology=tuple(codes), elements=tuple(found))


def drillhole_set(tables: Mapping[str, Any], *, all_vertical: bool = True,
                  assays: str = "assay_wide") -> Any:
    """El ``DrillholeSet`` de unas tablas por papel (véase el módulo); ``assays`` dice qué
    tabla de análisis se usa (``assay_wide`` o ``assay_long``)."""
    declaration = basico_expected()["declaration"]
    collars, stations = _collars(tables["collar"])
    stations += _surveys(tables["survey"])
    if all_vertical:
        surveyed = {model.name_key(station.hole) for station in stations}
        stations += [model.SurveyStation(c.name, 0.0, 0.0, -90.0, source="declared_vertical")
                     for c in collars if model.name_key(c.name) not in surveyed]
    if assays == "assay_long":
        assay_rows = _assays_long(tables["assay_long"])
    else:
        assay_rows = _assays_wide(tables["assay_wide"], declaration["units"])
    catalogs = _catalogs(tables["lithology_catalog"], tables["element_catalog"],
                         declaration["density_kind"])
    dset = model.DrillholeSet.from_records(
        crs=H25830, vertical=V5782, collars=collars, surveys=stations,
        lithology=_lithology(tables["lithology"]), assays=assay_rows, catalogs=catalogs)
    return validate.deduce_depths(dset)


def basico_set(assays: str = "assay_wide") -> Any:
    """El ``DrillholeSet`` de ``csv_basico`` (el juego limpio)."""
    return drillhole_set(basico_tables(), assays=assays)


def params() -> Any:
    """Los umbrales de ``csv_errores/esperado.json`` (los de la spec 005 §11)."""
    return validate.ValidationParams(**errores_expected()["params"])


def work_window() -> Any:
    return georef.Window(*errores_expected()["work_window"])


@dataclass(frozen=True, eq=False)
class ErrorCase:
    """Un caso de ``csv_errores``: su código, su papel, su conjunto de sondeos, la posición
    de las bocas en la capa (solo DH-W15) y sus incidencias esperadas."""

    code: str
    role: str
    about: str
    dset: Any
    stored_geom_xyz: np.ndarray | None
    issues: tuple[Mapping[str, Any], ...]


def _stored_geom(table: Any, collars: Any) -> np.ndarray:
    """La posición de cada boca de ``collars`` en la capa (``dh_w15_geom.csv``)."""
    found = {model.name_key(row[0]): [_number(text) for text in row[1:4]] for row in table.rows}
    return np.array([found[model.name_key(name)] for name in collars.name.tolist()],
                    dtype=np.float64)


def error_case(case: Mapping[str, Any]) -> ErrorCase:
    """El caso ``case`` de ``csv_errores/esperado.json``."""
    tables = dict(basico_tables())
    table = _read(ERRORES / case["file"])
    role = case["role"]
    geom = None
    if role != "collar_geom":
        tables[role] = table
    dset = drillhole_set(
        tables, all_vertical=case["declaration"].get("all_vertical", True),
        assays="assay_long" if role == "assay_long" else "assay_wide")
    if role == "collar_geom":
        geom = _stored_geom(table, dset.collars)
    return ErrorCase(case["code"], role, case["about"], dset, geom, tuple(case["issues"]))


def error_cases() -> list[ErrorCase]:
    """Todos los casos de ``csv_errores``, en el orden de ``esperado.json``."""
    return [error_case(case) for case in errores_expected()["cases"]]


def expected_value(field: str | None, text: str | None) -> Any:
    """El ``Issue.value`` del «value» ``text`` (texto de la fuente) de una incidencia
    esperada: ``None`` sin valor; «» si el campo estaba vacío; un número en los campos
    numéricos (coma decimal), sí/no en los lógicos y el texto en los demás."""
    if text is None or text == "":
        return text
    if field in NUMERIC_FIELDS:
        return _number(text)
    if field in BOOL_FIELDS:
        return text == YES
    return text


def issue_key(issue: Any) -> tuple:
    """Una incidencia de ``validate`` comparable con una esperada (:func:`expected_key`)."""
    return (issue.code, str(issue.level), None if issue.scope is None else str(issue.scope),
            issue.hole_name, issue.table, issue.catalog_code, issue.depth_from,
            issue.depth_to, issue.field, issue.value)


def expected_key(item: Mapping[str, Any]) -> tuple:
    """La incidencia esperada ``item`` de ``esperado.json`` como :func:`issue_key`."""
    return (item["code"], item["level"], item["scope"], item["hole"], item["table"],
            item["catalog_code"], item["depth_from"], item["depth_to"], item["field"],
            expected_value(item["field"], item["value"]))


__all__ = [
    "BASICO",
    "ERRORES",
    "H25830",
    "V5782",
    "ErrorCase",
    "basico_expected",
    "basico_set",
    "basico_tables",
    "drillhole_set",
    "error_case",
    "error_cases",
    "errores_expected",
    "expected_key",
    "expected_value",
    "issue_key",
    "params",
    "work_window",
]
