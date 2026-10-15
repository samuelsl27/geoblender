# SPDX-License-Identifier: GPL-3.0-or-later
"""Sondeos desde tablas CSV o XLSX (spec 005, T14; HU-005-1; plan 005 §5.3.2, §5.6.2 y
§5.6.12; ``interop.base`` e ``interop.drillholes_tabular``).

- **RF-005-05** (correspondencia propuesta por los nombres habituales en español y en inglés,
  editable, y las 20 primeras filas tal como se van a interpretar): las cabeceras de
  ``csv_basico`` (español) y de ``csv_convenios`` (inglés) dan su correspondencia completa,
  también en mayúsculas, sin tildes o con otros espacios y guiones; una correspondencia
  editada que no vale (campo obligatorio sin columna, columna que no está o repetida,
  campo desconocido) se rechaza nombrándolo; leer la vista previa (``preview_table``) da
  los primeros registros de la lectura entera.
- **RF-005-07** (nada se supone): cada declaración que falta (CRS, datum vertical,
  referencia del azimut, declinación de un azimut magnético, convenio de la inclinación,
  unidad de cada elemento, formato de las fechas) impide leer y se nombra; un papel que no
  la necesita se lee sin ella.
- **RF-005-09** (valores): vacío o centinela, ausente; «<x» y «>x», x con su marca;
  negativo, tal cual o «<x» si se declara; lo que no es un número, un error de Excel, un
  separador decimal que no es el declarado, una fecha, un sí/no, un tipo o un color que no
  valen, o una fila con otro número de campos, rechazados con su fila, su campo, su valor y,
  en el motivo, su sondeo y su tramo; el texto original se conserva.
- **RF-005-10** (códigos nuevos): los códigos de litología, elemento, sector y grupo de la
  fuente que no están en los catálogos del proyecto (sin distinguir mayúsculas ni espacios
  exteriores), en el informe y en el ``ImportDto``.
- DH-E01 sobre la fuente (plan §5.4): los nombres repetidos se listan en el informe (no
  pasarán a la base) y la validación los marca.
- **HU-005-1**: ``csv_basico`` (análisis en columnas o en filas) y cada variante de
  ``csv_convenios`` dan el mismo ``DrillholeSet`` tras convertir sus convenios
  (``drillholes.conventions``); el de ``csv_basico`` y el de cada caso de ``csv_errores``
  son exactamente los que montan las pruebas de la validación (``tests.support.dh_sets``,
  T08–T10), y el libro ``csv_basico.xlsx`` da el mismo que sus CSV (RF-005-06).

Las tablas nunca cambian al leerlas (lo comprueba cada lectura de los juegos de datos).
"""

from __future__ import annotations

import copy
import dataclasses
import datetime as dt
import json
import math
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

from tests.data.dh import build_xlsx
from tests.support import dh_sets
from tests.support.dh_fakes import FakeCrsService
from tests.support.package import import_geoblender

tabular = import_geoblender("interop.drillholes_tabular")
base = import_geoblender("interop.base")
csv_tables = import_geoblender("interop.csv_tables")
xlsx_tables = import_geoblender("interop.xlsx_tables")
model = import_geoblender("drillholes.model")
conventions = import_geoblender("drillholes.conventions")
validate = import_geoblender("drillholes.validate")
content = import_geoblender("core.content")
errors = import_geoblender("core.errors")

Role = tabular.TableRole
Flag = model.DetectionFlag
H25830 = dh_sets.H25830
V5782 = dh_sets.V5782
CONVENIOS = dh_sets.DATA / "csv_convenios"

# Lo que propone ``suggest_mapping`` con las cabeceras de cada fichero de los juegos.
BASICO_MAPPINGS = {
    Role.COLLAR: {
        "name": "Sondeo", "x": "X", "y": "Y", "z": "Z", "depth": "Profundidad",
        "azimuth": "Azimut", "inclination": "Inclinación", "hole_type": "Tipo",
        "planned": "Planificado", "campaign": "Campaña", "start_date": "Fecha inicio",
        "end_date": "Fecha fin",
    },
    Role.SURVEY: {"hole": "Sondeo", "depth": "Profundidad", "azimuth": "Azimut",
                  "inclination": "Inclinación"},
    Role.LITHOLOGY: {"hole": "Sondeo", "from_m": "Desde", "to_m": "Hasta",
                     "code": "Litología"},
    Role.ASSAY_WIDE: {"hole": "Sondeo", "from_m": "Desde", "to_m": "Hasta",
                      "sample_id": "Muestra", "element:Au": "Au", "element:Ag": "Ag",
                      "element:Cu": "Cu"},
    Role.ASSAY_LONG: {"hole": "Sondeo", "from_m": "Desde", "to_m": "Hasta",
                      "sample_id": "Muestra", "element": "Elemento", "value": "Valor",
                      "unit": "Unidad"},
    Role.LITHOLOGY_CATALOG: {"code": "Código", "description": "Descripción",
                             "color": "Color", "density": "Densidad", "sort_order": "Orden"},
    Role.ELEMENT_CATALOG: {"code": "Código", "name": "Nombre", "unit": "Unidad",
                           "decimals": "Decimales", "detection_limit": "Límite de detección"},
}
CONVENIOS_MAPPINGS = {
    Role.COLLAR: {
        "name": "HoleID", "x": "East", "y": "North", "z": "RL", "depth": "Depth",
        "azimuth": "Azimuth", "inclination": "Dip", "hole_type": "Type",
        "planned": "Planned", "campaign": "Campaign", "start_date": "StartDate",
        "end_date": "EndDate",
    },
    Role.SURVEY: {"hole": "HoleID", "depth": "Depth", "azimuth": "Azimuth",
                  "inclination": "Dip"},
    Role.LITHOLOGY: {"hole": "HoleID", "from_m": "From", "to_m": "To", "code": "Lith"},
    Role.ASSAY_LONG: {"hole": "HoleID", "from_m": "From", "to_m": "To",
                      "sample_id": "SampleID", "element": "Element", "value": "Value",
                      "unit": "Unit"},
    Role.LITHOLOGY_CATALOG: {"code": "Code", "description": "Description", "color": "Color",
                             "density": "Density", "sort_order": "Order"},
    Role.ELEMENT_CATALOG: {"code": "Code", "name": "Name", "unit": "Unit",
                           "decimals": "Decimals", "detection_limit": "DetectionLimit"},
}
# Columnas que dependen de la fuente y no de los valores (el texto original, el azimut medido
# y su referencia): no se comparan entre csv_basico y csv_convenios.
AS_REPORTED = {
    "surveys": ("azimuth_measured", "azimuth_ref", "declination_deg", "convergence_deg"),
    "assays": ("reported_value", "reported_unit"),
}


def _read(path: Path, separator: str = ";") -> object:
    return csv_tables.read_table(path, encoding="utf-8", separator=separator)


def _table(columns: list[str], *rows: list[str]) -> object:
    """Una tabla en memoria (líneas desde la 2: la 1 es la cabecera)."""
    return csv_tables.Table(list(columns), [list(row) for row in rows],
                            list(range(2, len(rows) + 2)))


def _declaration(**changes: object) -> object:
    """La declaración de ``csv_basico/esperado.json`` con ``changes``."""
    found = dh_sets.basico_expected()["declaration"]
    values = dict(
        crs=H25830, vertical=V5782, azimuth_ref=found["azimuth_ref"],
        declination_deg=found["declination_deg"],
        inclination_convention=found["inclination_convention"], units=found["units"],
        value_rules=model.ValueRules(decimal_mark=found["decimal_mark"]),
        all_vertical=found["all_vertical"], density_kind=found["density_kind"],
        date_format=found["date_format"],
    )
    values.update(changes)
    return model.SourceDeclaration(**values)


def _convenios_declaration(variant: str) -> object:
    expected = json.loads((CONVENIOS / "esperado.json").read_text(encoding="utf-8"))
    common, chosen = expected["declaration"], expected["variants"][variant]
    return model.SourceDeclaration(
        crs=H25830, vertical=V5782, azimuth_ref=chosen["azimuth_ref"],
        declination_deg=chosen["declination_deg"],
        inclination_convention=chosen["inclination_convention"], units={},
        value_rules=model.ValueRules(decimal_mark=common["decimal_mark"]),
        all_vertical=common["all_vertical"], density_kind=common["density_kind"],
        date_format=common["date_format"],
    )


def _basico_tables(assays: str = "assay_wide") -> dict:
    tables = dict(dh_sets.basico_tables())
    tables.pop("assay_long" if assays == "assay_wide" else "assay_wide")
    return {Role(role): table for role, table in tables.items()}


def _convenios_tables(variant: str) -> dict:
    names = {Role.COLLAR: f"collars_{variant}.csv", Role.SURVEY: f"surveys_{variant}.csv",
             Role.LITHOLOGY: "lithology.csv", Role.ASSAY_LONG: "assays.csv",
             Role.LITHOLOGY_CATALOG: "lithology_codes.csv",
             Role.ELEMENT_CATALOG: "elements.csv"}
    return {role: _read(CONVENIOS / name, ",") for role, name in names.items()}


def _bits(column: np.ndarray) -> list:
    """Una columna comparable: los bits de cada float64 (NaN, el mismo); lo demás, tal cual."""
    if column.dtype == np.float64:
        array = column.copy()
        array[np.isnan(array)] = math.nan
        return array.view(np.int64).tolist()
    return column.tolist()


def _snapshot(dset: object, skip: dict | None = None) -> dict:
    """Cada columna de cada tabla de ``dset`` (salvo las de ``skip``), sus catálogos, su CRS y
    su referencia vertical."""
    found: dict = {"crs": dset.crs, "vertical": dset.vertical, "catalogs": dset.catalogs}
    for name in model.TABLES:
        columns = getattr(dset, name)
        for item in dataclasses.fields(columns):
            if item.name not in (skip or {}).get(name, ()):
                found[f"{name}.{item.name}"] = _bits(getattr(columns, item.name))
    return found


def _converted(dset: object, declaration: object) -> object:
    """``dset`` con los convenios internos: azimut de cuadrícula con la γ del ``CrsService``
    falso (1,5°), inclinación negativa hacia abajo y leyes en la unidad del catálogo."""
    xy = np.column_stack([dset.collars.x, dset.collars.y])
    gamma = conventions.collar_convergence(xy, FakeCrsService(), dset.crs)
    units = {element.code: element.unit for element in dset.catalogs.elements}
    return dataclasses.replace(
        dset, surveys=conventions.convert_surveys(dset.surveys, declaration, gamma),
        assays=conventions.convert_assays(dset.assays, units))


class _Untouched:
    """Las tablas no cambian al leerlas."""

    def assertUntouched(self, tables: dict, read: object) -> object:
        before = copy.deepcopy({role: (t.columns, t.rows, t.lines) for role, t in tables.items()})
        found = read()
        after = {role: (t.columns, t.rows, t.lines) for role, t in tables.items()}
        self.assertEqual(after, before)
        return found


class MappingTest(unittest.TestCase):
    """RF-005-05: correspondencia propuesta (español e inglés), editable y comprobada."""

    def test_suggested_for_both_languages(self) -> None:
        """RF-005-05: cada fichero de ``csv_basico`` (español) y de ``csv_convenios``
        (inglés) da su correspondencia completa."""
        for role, table in _basico_tables().items():
            with self.subTest(role=role):
                self.assertEqual(tabular.suggest_mapping(role, table.columns),
                                 BASICO_MAPPINGS[role])
        long_table = dh_sets.basico_tables()["assay_long"]
        self.assertEqual(tabular.suggest_mapping("assay_long", long_table.columns),
                         BASICO_MAPPINGS[Role.ASSAY_LONG])
        for variant in ("positive_dip", "magnetic", "from_vertical"):
            for role, table in _convenios_tables(variant).items():
                with self.subTest(variant=variant, role=role):
                    expected = dict(CONVENIOS_MAPPINGS[role])
                    if variant == "from_vertical" and "inclination" in expected:
                        expected["inclination"] = "Inclination"
                    self.assertEqual(tabular.suggest_mapping(role, table.columns), expected)

    def test_without_accents_case_or_spacing(self) -> None:
        """RF-005-05: sin tildes, en mayúsculas o con otros espacios y guiones, lo mismo; las
        columnas que no son de ningún campo quedan fuera (en los análisis en columnas, cada
        una es un elemento: el usuario la quita si no lo es)."""
        columns = ["HOLE_ID", "ESTE", "norte", "COTA", "PROF.", "AZIMUT", "INCLINACION",
                   " fecha  de inicio ", "Observaciones", "Peso (kg)"]
        self.assertEqual(tabular.suggest_mapping(Role.COLLAR, columns), {
            "name": "HOLE_ID", "x": "ESTE", "y": "norte", "z": "COTA", "depth": "PROF.",
            "azimuth": "AZIMUT", "inclination": "INCLINACION",
            "start_date": " fecha  de inicio ", "comments": "Observaciones"})
        self.assertEqual(
            tabular.suggest_mapping(Role.ASSAY_WIDE, ["BHID", "FROM", "TO", "Au", "Cu"]),
            {"hole": "BHID", "from_m": "FROM", "to_m": "TO", "element:Au": "Au",
             "element:Cu": "Cu"})
        # La primera columna que casa se queda con el campo; la otra no se usa dos veces.
        self.assertEqual(tabular.suggest_mapping(Role.LITHOLOGY,
                                                 ["Sondeo", "Hole", "De", "A", "Lito"]),
                         {"hole": "Sondeo", "from_m": "De", "to_m": "A", "code": "Lito"})

    def test_suggested_role_by_name_or_columns(self) -> None:
        """RF-005-05 (spec 005, T25: la correspondencia propuesta es la correcta sin tocarla):
        el papel de cada fichero de ``csv_basico``, de ``csv_convenios`` y de cada hoja del
        libro sale de su nombre (en español o en inglés, sin la extensión, con lo que siga:
        «collars_magnetic»); unos análisis, en filas si tienen elemento y valor y si no, en
        columnas; sin un nombre reconocible, el de sus columnas (bocas, desviaciones,
        análisis en filas, litología); si nada encaja, ninguno."""
        files = {name: role for role, name in dh_sets.basico_expected()["files"].items()}
        for name, role in files.items():
            table = _read(dh_sets.BASICO / name)
            with self.subTest(fichero=name):
                self.assertEqual(tabular.suggest_role(name, table.columns), Role(role))
                stem = name.removesuffix(".csv")
                self.assertEqual(tabular.suggest_role(stem.upper(), table.columns), Role(role))
        convenios = {"collars_magnetic.csv": Role.COLLAR, "surveys_positive_dip.csv":
                     Role.SURVEY, "lithology.csv": Role.LITHOLOGY, "assays.csv":
                     Role.ASSAY_LONG, "lithology_codes.csv": Role.LITHOLOGY_CATALOG,
                     "elements.csv": Role.ELEMENT_CATALOG}
        for name, role in convenios.items():
            with self.subTest(fichero=name):
                table = _read(CONVENIOS / name, ",")
                self.assertEqual(tabular.suggest_role(name, table.columns), role)
        for sheet in build_xlsx.BASICO_SHEETS:
            with self.subTest(hoja=sheet):
                columns = _read(dh_sets.BASICO / f"{sheet}.csv").columns
                self.assertEqual(tabular.suggest_role(sheet, columns),
                                 Role(files[f"{sheet}.csv"]))
        by_columns = {
            Role.COLLAR: ["HoleID", "East", "North", "RL"],
            Role.SURVEY: ["BHID", "Depth", "Azimuth", "Dip"],
            Role.ASSAY_LONG: ["BHID", "From", "To", "Element", "Value"],
            Role.LITHOLOGY: ["BHID", "From", "To", "Lith"],
        }
        for role, columns in by_columns.items():
            with self.subTest(columnas=columns):
                self.assertEqual(tabular.suggest_role("datos_2026.csv", columns), role)
        self.assertIsNone(tabular.suggest_role("datos.csv", ["A", "B", "C"]))
        self.assertIsNone(tabular.suggest_role("", []))
        with self.assertRaises(TypeError):
            tabular.suggest_role(None, [])
        with self.assertRaises(TypeError):
            tabular.suggest_role("bocas", "Sondeo;X")

    def test_aliases_are_unambiguous(self) -> None:
        """Cada nombre habitual es de un solo campo de su papel."""
        for role in Role:
            seen: dict[str, str] = {}
            for name, aliases in tabular.aliases(role).items():
                for alias in aliases:
                    self.assertNotIn(alias, seen, f"{role}: «{alias}» en {name} y {seen.get(alias)}")
                    seen[alias] = name

    def test_edited_mapping_is_checked(self) -> None:
        """RF-005-05: la correspondencia editada se comprueba antes de leer y lo que no vale
        se nombra (``dh.mapping_*``)."""
        columns = ["Sondeo", "Desde", "Hasta", "Litología", "Litología", "Notas"]
        table = _table(columns, ["S-01", "0", "1", "CAL", "CAL", ""])
        cases = [
            ({"hole": "Sondeo", "from_m": "Desde", "to_m": "Hasta"}, "dh.mapping_required",
             "code"),
            ({"hole": "Sondeo", "from_m": "Desde", "to_m": "Hasta", "code": "Lito"},
             "dh.mapping_missing_column", "code"),
            ({"hole": "Sondeo", "from_m": "Desde", "to_m": "Hasta", "code": "Litología"},
             "dh.mapping_ambiguous_column", "code"),
            ({"hole": "Sondeo", "from_m": "Desde", "to_m": "Desde", "code": "Notas"},
             "dh.mapping_repeated_column", "to_m"),
            ({"hole": "Sondeo", "from_m": "Desde", "to_m": "Hasta", "code": "Notas",
              "element:Au": "Notas"}, "dh.mapping_unknown_field", "element:Au"),
            ({"hole": "Sondeo", "from_m": "Desde", "to_m": "Hasta", "code": "Notas",
              "density": "Notas"}, "dh.mapping_unknown_field", "density"),
        ]
        for mapping, code, field in cases:
            with self.subTest(code=code, field=field):
                with self.assertRaises(errors.GeoblenderError) as caught:
                    tabular.read_role(Role.LITHOLOGY, table, mapping, _declaration())
                self.assertEqual(caught.exception.code, code)
                self.assertIn(field, caught.exception.message)
        wide = _table(["Sondeo", "Desde", "Hasta", "Au", "Cu"], ["S-01", "0", "1", "2", "3"])
        for mapping, code in (
            ({"hole": "Sondeo", "from_m": "Desde", "to_m": "Hasta"}, "dh.mapping_required"),
            ({"hole": "Sondeo", "from_m": "Desde", "to_m": "Hasta", "element: ": "Au"},
             "dh.mapping_unknown_field"),
            ({"hole": "Sondeo", "from_m": "Desde", "to_m": "Hasta", "element:Au": "Au",
              "element: au": "Cu"}, "dh.mapping_repeated_element"),
        ):
            with self.subTest(code=code):
                with self.assertRaises(errors.GeoblenderError) as caught:
                    tabular.read_role(Role.ASSAY_WIDE, wide, mapping, _declaration())
                self.assertEqual(caught.exception.code, code)
        with self.assertRaises(TypeError):
            tabular.read_role(Role.LITHOLOGY, table, [("hole", "Sondeo")], _declaration())
        with self.assertRaises(ValueError):
            tabular.suggest_mapping("bocas", columns)


class DeclarationsTest(unittest.TestCase):
    """RF-005-07: cada declaración que falta impide leer y se nombra."""

    def _blocked(self, role: object, table: object, declaration: object,
                 expected: list[str]) -> None:
        mapping = tabular.suggest_mapping(role, table.columns)
        with self.assertRaises(base.DeclarationError) as caught:
            tabular.read_role(role, table, mapping, declaration)
        error = caught.exception
        self.assertEqual(error.code, "dh.declaration_missing")
        self.assertEqual(error.missing, expected)
        for text in expected:
            self.assertIn(text, error.message)
        needs = tabular.needs(role, table, mapping)
        self.assertEqual(base.missing_declarations(declaration, needs), expected)

    def test_each_missing_declaration_is_named(self) -> None:
        """RF-005-07: el CRS, el datum vertical, la referencia del azimut, la declinación
        de un azimut magnético, el convenio de la inclinación, el formato de las fechas y la
        unidad de cada elemento, cada uno por separado."""
        tables = dh_sets.basico_tables()
        collar, survey = tables["collar"], tables["survey"]
        wide, long_table = tables["assay_wide"], tables["assay_long"]
        unit_of = base.missing_unit
        cases = [
            (Role.COLLAR, collar, dict(crs=None), [base.MISSING_CRS]),
            (Role.COLLAR, collar, dict(vertical=None), [base.MISSING_VERTICAL]),
            (Role.COLLAR, collar, dict(azimuth_ref=None), [base.MISSING_AZIMUTH]),
            (Role.COLLAR, collar, dict(inclination_convention=None),
             [base.MISSING_INCLINATION]),
            (Role.COLLAR, collar, dict(date_format=None), [base.MISSING_DATES]),
            (Role.SURVEY, survey, dict(azimuth_ref=None), [base.MISSING_AZIMUTH]),
            (Role.SURVEY, survey, dict(azimuth_ref="magnetic"), [base.MISSING_DECLINATION]),
            (Role.SURVEY, survey, dict(inclination_convention=None),
             [base.MISSING_INCLINATION]),
            (Role.ASSAY_WIDE, wide, dict(units={"Au": "g/t", "Ag": "ppm"}), [unit_of("Cu")]),
            (Role.ASSAY_WIDE, wide, dict(units={"Au": "oz/t", "ag": "ppm", "CU": "%"}),
             [unit_of("Au", "oz/t")]),
        ]
        for role, table, changes, expected in cases:
            with self.subTest(role=role, changes=changes):
                self._blocked(role, table, _declaration(**changes), expected)
        # Análisis en filas sin la columna de la unidad: la de cada elemento, declarada.
        mapping = dict(BASICO_MAPPINGS[Role.ASSAY_LONG])
        del mapping["unit"]
        with self.assertRaises(base.DeclarationError) as caught:
            tabular.read_role(Role.ASSAY_LONG, long_table, mapping, _declaration(units={}))
        self.assertEqual(caught.exception.missing,
                         [unit_of("Au"), unit_of("Ag"), unit_of("Cu")])
        rows = tabular.read_role(Role.ASSAY_LONG, long_table, mapping, _declaration())
        self.assertEqual(sorted(set(rows.assays.unit.tolist())), ["%", "g/t", "ppm"])

    def test_not_needed_is_not_asked(self) -> None:
        """RF-005-07: un papel que no necesita una declaración se lee sin ella (la litología
        y los catálogos, sin CRS ni convenios; unas bocas sin orientación ni fechas, sin
        azimut, inclinación ni formato de fecha); y con todo sin declarar, la lectura entera
        los nombra todos a la vez."""
        nothing = _declaration(crs=None, vertical=None, azimuth_ref=None,
                               inclination_convention=None, units={}, date_format=None)
        tables = dh_sets.basico_tables()
        for role in (Role.LITHOLOGY, Role.LITHOLOGY_CATALOG, Role.ELEMENT_CATALOG):
            table = tables[str(role)]
            rows = tabular.read_role(role, table, tabular.suggest_mapping(role, table.columns),
                                     nothing)
            self.assertEqual(rows.counts.imported, len(table.rows))
        bare = _table(["Sondeo", "X", "Y", "Z", "Azimut", "Inclinación", "Fecha inicio"],
                      ["S-01", "1", "2", "3", "", "", ""])
        rows = tabular.read_role(Role.COLLAR, bare, tabular.suggest_mapping("collar",
                                                                            bare.columns),
                                 _declaration(azimuth_ref=None, inclination_convention=None,
                                              date_format=None))
        self.assertEqual(rows.collars.name.tolist(), ["S-01"])
        self.assertEqual(len(rows.surveys), 0)
        with self.assertRaises(base.DeclarationError) as caught:
            tabular.read_drillholes(_basico_tables(), None, nothing)
        self.assertEqual(caught.exception.missing, [
            base.MISSING_CRS, base.MISSING_VERTICAL, base.MISSING_AZIMUTH,
            base.MISSING_INCLINATION, base.MISSING_DATES, base.missing_unit("Au"),
            base.missing_unit("Ag"), base.missing_unit("Cu")])


class SameSetTest(_Untouched, unittest.TestCase):
    """HU-005-1: los mismos sondeos con otros convenios dan el mismo conjunto."""

    def test_basico_and_convenios_after_converting(self) -> None:
        """HU-005-1, RF-005-05, RF-005-09: ``csv_basico`` (análisis en columnas y en filas)
        y las variantes ``positive_dip``, ``from_vertical`` y ``magnetic`` de
        ``csv_convenios`` dan, tras convertir los convenios, el mismo ``DrillholeSet`` bit a
        bit (salvo el texto original y el azimut medido)."""
        decl = _declaration()
        tables = _basico_tables()
        dset, report = self.assertUntouched(
            tables, lambda: tabular.read_drillholes(tables, None, decl))
        reference = _snapshot(_converted(dset, decl), AS_REPORTED)
        self.assertEqual(reference, _snapshot(dset, AS_REPORTED))  # ya en los internos
        tables = _basico_tables("assay_long")
        long_set, _ = tabular.read_drillholes(tables, None, decl)
        self.assertEqual(_snapshot(_converted(long_set, decl), AS_REPORTED), reference)
        for variant in ("positive_dip", "from_vertical", "magnetic"):
            with self.subTest(variant=variant):
                declaration = _convenios_declaration(variant)
                tables = _convenios_tables(variant)
                found, _ = self.assertUntouched(
                    tables, lambda: tabular.read_drillholes(tables, None, declaration))
                converted = _converted(found, declaration)
                self.assertEqual(_snapshot(converted, AS_REPORTED), reference)
        magnetic = _converted(found, declaration).surveys
        measured = magnetic.source == model.SurveyColumns.code_values("source").index(
            model.StationSource.MEASURED)
        self.assertEqual(set(magnetic.declination_deg[measured].tolist()), {0.25})
        self.assertEqual(set(magnetic.convergence_deg[measured].tolist()), {1.5})
        self.assertEqual(found.surveys.azimuth[measured].tolist(),
                         magnetic.azimuth_measured[measured].tolist())
        # Los análisis de csv_convenios conservan su texto y su unidad originales.
        assays = _converted(found, declaration).assays
        self.assertEqual(assays.reported_value[:3].tolist(), ["<10", "2.9", "1050"])
        self.assertEqual(assays.reported_unit[:3].tolist(), ["ppb", "g/t", "ppm"])

    def test_same_as_the_validation_sets(self) -> None:
        """HU-005-1, RF-005-09: ``csv_basico`` y cada caso de ``csv_errores`` dan
        exactamente el ``DrillholeSet`` con que se probó la validación
        (``tests.support.dh_sets``): orientación en boca, verticales declarados, análisis en
        columnas y en filas, valores especiales, profundidad deducida y nombres repetidos."""
        decl = _declaration()
        for assays in ("assay_wide", "assay_long"):
            dset, _ = tabular.read_drillholes(_basico_tables(assays), None, decl)
            self.assertEqual(_snapshot(dset), _snapshot(dh_sets.basico_set(assays)))
        for case in dh_sets.errores_expected()["cases"]:
            if case["role"] == "collar_geom":
                continue
            with self.subTest(code=case["code"]):
                tables = dict(dh_sets.basico_tables())
                tables[case["role"]] = dh_sets._read(dh_sets.ERRORES / case["file"])
                tables.pop("assay_wide" if case["role"] == "assay_long" else "assay_long")
                all_vertical = case["declaration"].get("all_vertical", True)
                dset, _ = tabular.read_drillholes(
                    {Role(role): table for role, table in tables.items()}, None,
                    _declaration(all_vertical=all_vertical))
                self.assertEqual(_snapshot(dset), _snapshot(dh_sets.error_case(case).dset))

    def test_counts_and_values(self) -> None:
        """RF-005-09, RF-005-12: las filas leídas de cada fichero y los valores de
        ``csv_basico/esperado.json`` (84 leídos, 1 ausente, 2 bajo el límite, 1 sobre el
        límite superior), sin rechazos ni avisos."""
        expected = dh_sets.basico_expected()
        for assays in ("assay_wide", "assay_long"):
            dset, report = tabular.read_drillholes(_basico_tables(assays), None,
                                                   _declaration())
            self.assertEqual(report.rejected, ())
            self.assertEqual(report.warnings, ())
            self.assertEqual(report.duplicate_holes, ())
            for role, count in expected["rows"].items():
                if role in report.per_table:
                    self.assertEqual(report.per_table[role].read, count)
                    self.assertEqual(report.per_table[role].rejected, 0)
            self.assertEqual(report.per_table[assays].imported, expected["values"]["read"])
            flags = [model.AssayColumns.code_values("detection_flag")[code]
                     for code in dset.assays.detection_flag.tolist()]
            self.assertEqual(int(np.isnan(dset.assays.value).sum()),
                             expected["values"]["absent"])
            self.assertEqual(flags.count(Flag.BELOW_DL), expected["values"]["below_dl"])
            self.assertEqual(flags.count(Flag.ABOVE_UL), expected["values"]["above_ul"])
            self.assertEqual(dset.assays.reported_value[0], "<0,01")

    def test_xlsx_book_gives_the_same_set(self) -> None:
        """RF-005-06: las hojas de ``csv_basico.xlsx`` (con coma decimal y fechas
        «%d/%m/%Y») dan el mismo ``DrillholeSet`` que sus CSV."""
        folder = Path(tempfile.mkdtemp(prefix="gb-dhtab-"))
        self.addCleanup(shutil.rmtree, folder, True)
        path = folder / "csv_basico.xlsx"
        build_xlsx.basico_book().write(path)
        names = {role: Path(name).stem
                 for role, name in dh_sets.basico_expected()["files"].items()}
        decl = _declaration()
        tables = {Role(role): xlsx_tables.read_sheet(path, names[role], decimal_mark=",",
                                                     date_format=decl.date_format)
                  for role in names if role != "assay_long"}
        dset, report = tabular.read_drillholes(tables, None, decl)
        self.assertEqual(report.rejected, ())
        # El texto original de una celda numérica es su número («0,96»; en el CSV, «0,960»).
        skip = {"assays": ("reported_value",)}
        expected = dh_sets.basico_set()
        self.assertEqual(_snapshot(dset, skip), _snapshot(expected, skip))
        texts = [(found, wanted) for found, wanted in zip(
            dset.assays.reported_value.tolist(), expected.assays.reported_value.tolist(),
            strict=True) if wanted is None or not wanted[0].isdigit()]
        self.assertEqual([found for found, _ in texts], [wanted for _, wanted in texts])
        self.assertIn("<0,01", [found for found, _ in texts])


class ValuesTest(unittest.TestCase):
    """RF-005-09: valores especiales, rechazos con su fila, campo, valor, sondeo y tramo."""

    def test_assay_values(self) -> None:
        """RF-005-09: vacío y centinelas, ausentes; «<x» y «>x», con su marca; negativo, tal
        cual o «<x» si se declara; lo que no es un número, con el otro separador decimal o
        un error de Excel, rechazado con su fila, campo y valor, y su sondeo y su tramo en
        el motivo; el texto original se conserva."""
        columns = ["Sondeo", "Desde", "Hasta", "Muestra", "Elemento", "Valor", "Unidad"]
        texts = ["<0,01", ">10", "", "ND", "-99", "-0,5", "1,5E-03", "abc", "0.5", "#N/A"]
        rows = [["S-01", f"{k},0", f"{k + 1},0", f"M-{k}", "Au", text, "g/t"]
                for k, text in enumerate(texts)]
        table = _table(columns, *rows)
        mapping = tabular.suggest_mapping(Role.ASSAY_LONG, columns)
        rules = model.ValueRules(decimal_mark=",", sentinels={"ND", "-99"})
        found = tabular.read_role(Role.ASSAY_LONG, table, mapping,
                                  _declaration(value_rules=rules))
        assays = found.assays
        flags = [model.AssayColumns.code_values("detection_flag")[code]
                 for code in assays.detection_flag.tolist()]
        self.assertEqual(_bits(assays.value), _bits(np.array(
            [0.01, 10.0, math.nan, math.nan, math.nan, -0.5, 0.0015])))
        self.assertEqual(flags, [Flag.BELOW_DL, Flag.ABOVE_UL] + [Flag.OK] * 5)
        self.assertEqual(assays.reported_value.tolist(), texts[:2] + [None] + texts[3:7])
        self.assertEqual(found.lines["assays"].tolist(), [2, 3, 4, 5, 6, 7, 8])
        self.assertEqual(found.counts, base.TableCounts(read=10, imported=7, rejected=3))
        self.assertEqual([(r.table, r.row, r.field, r.value) for r in found.rejected],
                         [("assay_long", 9, "Valor", "abc"), ("assay_long", 10, "Valor", "0.5"),
                          ("assay_long", 11, "Valor", "#N/A")])
        self.assertIn("sondeo «S-01», de 7 a 8 m", found.rejected[0].reason)
        self.assertIn("no es un número", found.rejected[0].reason)
        self.assertIn("separador decimal", found.rejected[1].reason)
        self.assertIn("error de Excel", found.rejected[2].reason)
        negative = model.ValueRules(decimal_mark=",", negative_is_below_dl=True)
        below = tabular.read_role(Role.ASSAY_LONG, _table(columns, rows[5]), mapping,
                                  _declaration(value_rules=negative))
        self.assertEqual(below.assays.value.tolist(), [0.5])
        self.assertEqual(below.assays.detection_flag.tolist(),
                         [model.AssayColumns.code_values("detection_flag").index(
                             Flag.BELOW_DL)])

    def test_wide_rejects_only_the_value(self) -> None:
        """RF-005-09: en los análisis en columnas se rechaza el valor, no la muestra; una fila
        sin sondeo o con un tramo que no es un número rechaza sus valores."""
        columns = ["Sondeo", "Desde", "Hasta", "Muestra", "Au", "Cu"]
        table = _table(columns, ["S-01", "0", "2", "M-1", "1,5", "#DIV/0!"],
                       ["S-01", "2", "x", "M-2", "1", "2"], ["", "4", "6", "M-3", "1", "2"])
        found = tabular.read_role(Role.ASSAY_WIDE, table,
                                  tabular.suggest_mapping("assay_wide", columns),
                                  _declaration(units={"Au": "g/t", "Cu": "%"}))
        self.assertEqual(found.assays.element.tolist(), ["Au"])
        self.assertEqual(found.assays.value.tolist(), [1.5])
        self.assertEqual(found.assays.unit.tolist(), ["g/t"])
        self.assertEqual(found.counts, base.TableCounts(read=3, imported=1, rejected=5))
        self.assertEqual([(r.row, r.field, r.value) for r in found.rejected],
                         [(2, "Cu", "#DIV/0!"), (3, "Hasta", "x"), (4, "Sondeo", None)])

    def test_other_fields(self) -> None:
        """RF-005-09: coordenadas con «<» o con otro separador, sí/no, tipos, fechas,
        enteros, un error de Excel en una columna de texto y filas con otro número de
        campos: rechazados con su fila, campo, valor y sondeo; lo que vale, interpretado
        (sí/no y TRUE/FALSE de Excel; tipos por su nombre en español o en inglés)."""
        columns = ["Sondeo", "X", "Y", "Z", "Tipo", "Planificado", "Fecha inicio",
                   "Categoría"]
        table = _table(
            columns,
            ["S-01", "1,5", "2", "3", "Calicata", "TRUE", "01/02/2025", "2"],
            ["S-02", "1", "2", "3", "dd", "no", "", ""],
            ["S-03", "<5", "2", "3", "", "", "", ""],
            ["S-04", "1", "2,5.0", "3", "", "", "", ""],
            ["S-05", "1", "2", "3", "Martillo", "quizá", "31/02/2025", "2,5"],
            ["S-06", "1", "2"],
            ["S-07", "1", "2", "3", "trench", "Sí", "", "1"],
            ["S-08", "1", "2", "3", "#N/A", "", "", ""],
        )
        found = tabular.read_role(Role.COLLAR, table, tabular.suggest_mapping("collar", columns),
                                  _declaration())
        collars = found.collars
        self.assertEqual(collars.name.tolist(), ["S-01", "S-02", "S-07"])
        types = model.CollarColumns.code_values("hole_type")
        self.assertEqual([types[c] for c in collars.hole_type.tolist()],
                         [model.HoleType.CA, model.HoleType.DD, model.HoleType.TR])
        self.assertEqual(collars.planned.tolist(), [True, False, True])
        self.assertEqual(collars.start_date.tolist(), [dt.date(2025, 2, 1), None, None])
        self.assertEqual(collars.category.tolist(), [2, None, 1])
        self.assertEqual(collars.x.tolist(), [1.5, 1.0, 1.0])
        rejected = [(r.row, r.field, r.value) for r in found.rejected]
        self.assertEqual(rejected, [
            (4, "X", "<5"), (5, "Y", "2,5.0"), (6, "Tipo", "Martillo"),
            (6, "Planificado", "quizá"), (6, "Fecha inicio", "31/02/2025"),
            (6, "Categoría", "2,5"), (7, "fila", None), (9, "Tipo", "#N/A")])
        self.assertTrue(all("sondeo «S-0" in r.reason for r in found.rejected))
        self.assertIn("3 campos", found.rejected[-2].reason)
        self.assertIn("error de Excel", found.rejected[-1].reason)
        self.assertEqual(found.counts, base.TableCounts(read=8, imported=3, rejected=5))

    def test_catalogs(self) -> None:
        """RF-005-09, RF-005-10: colores en minúsculas o sin «#»; densidad con su tipo
        declarado; un código repetido en el catálogo (sin distinguir mayúsculas) o un color
        que no lo es, rechazados; una unidad de elemento que no es de ley, rechazada."""
        columns = ["Código", "Descripción", "Color", "Densidad", "Orden"]
        table = _table(columns, ["CAL", "Caliza", "#a1b2c3", "2,7", "1"],
                       ["MAR", "", "a1b2c3", "", ""], ["cal ", "Otra", "#000000", "", "3"],
                       ["PIZ", "Pizarra", "rojo", "2,8", "4"], ["ARE", "", "", "", ""])
        found = tabular.read_role(Role.LITHOLOGY_CATALOG, table,
                                  tabular.suggest_mapping("lithology_catalog", columns),
                                  _declaration(density_kind="MEDIDO"))
        codes = found.catalogs.lithology
        self.assertEqual([(c.code, c.color, c.density, c.density_kind, c.sort_order)
                          for c in codes],
                         [("CAL", "#A1B2C3", 2.7, model.ParamKind.MEDIDO, 1),
                          ("MAR", "#A1B2C3", None, None, 0),
                          ("ARE", model.DEFAULT_COLOR, None, None, 0)])
        self.assertEqual([(r.row, r.field, r.value) for r in found.rejected],
                         [(4, "Código", "cal "), (5, "Color", "rojo")])
        columns = ["Código", "Unidad", "Decimales"]
        table = _table(columns, ["Au", "PPB", "3"], ["Cu", "oz/t", "2"], ["Ag", "", ""])
        found = tabular.read_role(Role.ELEMENT_CATALOG, table,
                                  tabular.suggest_mapping("element_catalog", columns),
                                  _declaration(units={"Ag": "g/t"}))
        self.assertEqual([(e.code, e.unit, e.decimals) for e in found.catalogs.elements],
                         [("Au", "ppb", 3), ("Ag", "g/t", 2)])
        self.assertEqual([(r.row, r.field, r.value) for r in found.rejected],
                         [(3, "Unidad", "oz/t")])

    def test_preview_is_the_first_records(self) -> None:
        """RF-005-05: la vista previa (20 filas) leída da los primeros registros de la
        lectura entera, tal como se van a interpretar."""
        path = dh_sets.BASICO / "desviaciones.csv"
        preview = csv_tables.preview_table(path, encoding="utf-8", separator=";")
        full = _read(path)
        mapping = tabular.suggest_mapping(Role.SURVEY, full.columns)
        first = tabular.read_role(Role.SURVEY, preview, mapping, _declaration())
        whole = tabular.read_role(Role.SURVEY, full, mapping, _declaration())
        self.assertEqual(len(first.surveys), csv_tables.PREVIEW_ROWS)
        self.assertEqual(_snapshot_columns(first.surveys),
                         _snapshot_columns(whole.surveys, csv_tables.PREVIEW_ROWS))


def _snapshot_columns(columns: object, rows: int | None = None) -> dict:
    return {item.name: _bits(getattr(columns, item.name)[:rows])
            for item in dataclasses.fields(columns)}


class HolesAndCodesTest(unittest.TestCase):
    """DH-E01 sobre la fuente, orientación en boca, verticales declarados y códigos nuevos
    (RF-005-10)."""

    def test_repeated_names(self) -> None:
        """DH-E01 (plan §5.4): «S-90» y « s-90 » se listan en el informe (no pasarán a la
        base), siguen en lo leído y la validación los marca."""
        tables = _basico_tables()
        tables[Role.COLLAR] = dh_sets._read(dh_sets.ERRORES / "dh_e01_bocas.csv")
        dset, report = tabular.read_drillholes(tables, None, _declaration())
        self.assertEqual(report.duplicate_holes, (("S-90", " s-90 "),))
        self.assertEqual(report.per_table["collar"],
                         base.TableCounts(read=8, imported=8, rejected=0, duplicated=2))
        self.assertTrue(any("S-90" in text for text in report.warnings))
        issues = validate.validate(dset, dh_sets.params()).issues
        self.assertEqual([(i.code, i.hole_name, i.value) for i in issues],
                         [("DH-E01", "S-90", " s-90 ")])

    def test_collar_orientation_and_declared_vertical(self) -> None:
        """RF-005-05 y spec §8: la orientación en boca es una estación a 0 m de un sondeo sin
        desviaciones (no la de uno que las tiene); los verticales declarados, solo con
        «todos verticales» y en los sondeos sin ninguna estación."""
        collar = _table(["Sondeo", "X", "Y", "Z", "Azimut", "Inclinación"],
                        ["A", "1", "1", "1", "30", "-60"], ["B", "2", "2", "2", "40", ""],
                        ["C", "3", "3", "3", "", ""], ["D", "4", "4", "4", "", ""])
        survey = _table(["Sondeo", "Profundidad", "Azimut", "Inclinación"],
                        ["B", "0", "45", "-50"], ["B", "30", "45", "-50"])
        tables = {Role.COLLAR: collar, Role.SURVEY: survey}
        sources = model.SurveyColumns.code_values("source")
        for all_vertical, expected in (
            (True, [("A", 0.0, 30.0, -60.0, "collar"), ("B", 0.0, 45.0, -50.0, "measured"),
                    ("B", 30.0, 45.0, -50.0, "measured"),
                    ("C", 0.0, 0.0, -90.0, "declared_vertical"),
                    ("D", 0.0, 0.0, -90.0, "declared_vertical")]),
            (False, [("A", 0.0, 30.0, -60.0, "collar"), ("B", 0.0, 45.0, -50.0, "measured"),
                     ("B", 30.0, 45.0, -50.0, "measured")]),
        ):
            with self.subTest(all_vertical=all_vertical):
                dset, _ = tabular.read_drillholes(tables, None,
                                                  _declaration(all_vertical=all_vertical))
                s = dset.surveys
                found = list(zip(s.hole_name.tolist(), s.depth.tolist(), s.azimuth.tolist(),
                                 s.inclination.tolist(),
                                 [str(sources[c]) for c in s.source.tolist()], strict=True))
                self.assertEqual(found, expected)
                self.assertEqual(s.hole.tolist(), [dset.hole_index([n])[0]
                                                   for n in s.hole_name.tolist()])
        # Una boca con solo una de las dos: la estación con el ángulo que falta vacío (lo
        # marca la validación, DH-E08); en el informe de la lectura de las bocas, nada.
        rows = tabular.read_role(Role.COLLAR, collar,
                                 tabular.suggest_mapping("collar", collar.columns),
                                 _declaration())
        self.assertEqual(rows.surveys.hole_name.tolist(), ["A", "B"])
        self.assertTrue(math.isnan(rows.surveys.inclination[1]))
        self.assertEqual(rows.lines["surveys"].tolist(), [2, 3])

    def test_new_codes_and_import_dto(self) -> None:
        """RF-005-10, RF-005-11, RF-005-12: los códigos que no están en los catálogos del
        proyecto (sin distinguir mayúsculas ni espacios), los sondeos que ya existen, los
        recuentos y los rechazos, en el ``ImportDto``."""
        tables = _basico_tables()
        tables[Role.LITHOLOGY] = dh_sets._read(dh_sets.ERRORES / "dh_e11_litologia.csv")
        project = model.Catalogs(
            lithology=(model.LithologyCode(" sue"), model.LithologyCode("CAL"),
                       model.LithologyCode("MIN", log_set="recmin_alteracion")),
            elements=(model.Element("au", "g/t"),))
        dset, report = tabular.read_drillholes(tables, None, _declaration(), project)
        self.assertEqual(report.unknown_codes, {
            "lithology": ("ARC", "ARE", "MAR", "DOL", "PIZ", "MIN", "GRA"),
            "element": ("Ag", "Cu"),
        })
        digest = content.ContentDigest("a" * 64, "b" * 64, content.NORMALIZER, "io.dh_csv@1")
        source = model.ImportSource(name="bocas.csv", roles=("collar",), digest=digest,
                                    prints=(model.FilePrint("c" * 64, size=10),))
        dto = base.to_import_dto(dset, _declaration(), report, (source,),
                                 project_holes=["s-01 ", "S-77", "c-01"])
        self.assertIsInstance(dto, model.ImportDto)
        self.assertEqual(dto.new_codes, report.unknown_codes)
        self.assertEqual(dto.existing_holes, ("S-01", "C-01"))
        self.assertEqual(dto.counts["lithology"],
                         {"read": 24, "imported": 24, "rejected": 0, "duplicated": 0})
        self.assertEqual(dto.sources, (source,))
        self.assertIs(dto.dset, dset)
        with_all = dataclasses.replace(project, lithology=project.lithology + tuple(
            model.LithologyCode(code) for code in report.unknown_codes["lithology"]),
            elements=dset.catalogs.elements)
        self.assertEqual(base.new_codes(dset, with_all), {})

    def test_existing_holes_by_table(self) -> None:
        """RF-005-11 (spec 005, T46; M1 y M5 en pantalla): los sondeos de la fuente que ya
        tienen registros en el proyecto en alguna de las tablas que trae (``project_holes``,
        por tabla de un ``DrillholeSet``; sin distinguir mayúsculas ni espacios), con la grafía
        de la fuente: de las desviaciones solo cuentan las medidas (la orientación en boca de
        S-12 no sustituye ninguna) y un sondeo sin registros en esas tablas no está (C-01 no
        tiene análisis en la fuente). Una lista de nombres son las bocas del proyecto, como
        antes; una tabla que no es de un ``DrillholeSet``, un error."""
        dset, _report = tabular.read_drillholes(_basico_tables(), None, _declaration())
        project = {"collars": [], "surveys": ["s-01 ", "S-12", "S-77"], "lithology": ["S-02"],
                   "assays": ["c-01", "S-03"], "zones": ["S-04"]}
        self.assertEqual(base.existing_tables(dset, project),
                         {"surveys": ("S-01",), "lithology": ("S-02",), "assays": ("S-03",)})
        self.assertEqual(base.existing_holes(dset, project), ("S-01", "S-02", "S-03"))
        self.assertEqual(base.existing_tables(dset, ["s-01 ", "S-77"]), {"collars": ("S-01",)})
        self.assertEqual(base.existing_holes(dset, ["s-01 ", "S-77"]), ("S-01",))
        self.assertEqual(base.existing_tables(dset, {}), {})
        with self.assertRaises(ValueError):
            base.existing_tables(dset, {"bocas": ["S-01"]})

    def test_registrations_of_the_new_codes(self) -> None:
        """RF-005-10 (spec 005, T25): los códigos nuevos como se dan de alta (el parámetro
        ``register_codes`` de ``dh_import_apply``): cada litología con su esquema de logueo
        (también la que el proyecto tiene en otro esquema), cada elemento con la unidad de su
        catálogo de la fuente o, sin catálogo, la de sus análisis; con todo dado de alta,
        nada."""
        tables = _basico_tables()
        tables[Role.LITHOLOGY] = dh_sets._read(dh_sets.ERRORES / "dh_e11_litologia.csv")
        project = model.Catalogs(
            lithology=(model.LithologyCode(" sue"), model.LithologyCode("CAL"),
                       model.LithologyCode("MIN", log_set="recmin_alteracion")),
            elements=(model.Element("au", "g/t"),))
        dset, report = tabular.read_drillholes(tables, None, _declaration(), project)
        found = base.registrations(dset, project)
        self.assertEqual(found, {
            "lithology": [["lithology", code] for code in report.unknown_codes["lithology"]],
            "element": [["Ag", "ppm"], ["Cu", "%"]],
        })
        # Sin catálogo de elementos: la unidad escrita en los análisis en filas.
        without = {role: table for role, table in _basico_tables("assay_long").items()
                   if role is not Role.ELEMENT_CATALOG}
        long_set, _ = tabular.read_drillholes(without, None, _declaration(units={}), project)
        self.assertEqual(long_set.catalogs.elements, ())
        self.assertEqual(base.registrations(long_set, project)["element"],
                         [["Ag", "ppm"], ["Cu", "%"]])
        with_all = dataclasses.replace(project, lithology=project.lithology + tuple(
            model.LithologyCode(code) for code in report.unknown_codes["lithology"]),
            elements=dset.catalogs.elements)
        self.assertEqual(base.registrations(dset, with_all), {})
        self.assertEqual(base.registrations(dset, None)["element"],
                         [["Au", "g/t"], ["Ag", "ppm"], ["Cu", "%"]])
        with self.assertRaises(TypeError):
            base.registrations(dset, {})


if __name__ == "__main__":
    unittest.main()
