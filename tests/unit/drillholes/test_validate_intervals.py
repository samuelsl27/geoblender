# SPDX-License-Identifier: GPL-3.0-or-later
"""Validación de los tramos y los catálogos (spec 005, T09; HU-005-3; RF-005-16, RF-005-17;
spec §4.4.1 y §8; plan 005 §5.3.2 y §5.4).

- **CE-005-01** con todo ``tests/data/dh/csv_errores``: cada código de la tabla 4.4.1 que se
  valida sin MDT (todos salvo DH-W05, de la T10) sale en su caso (100 %) y cada caso da
  exactamente sus incidencias (0 falsos positivos); ``csv_basico``, ninguna.
- **Alcance T** (RF-005-17): un error de los tramos o de los catálogos excluye solo esa tabla
  (el esquema de logueo o el elemento) de ese sondeo, nada más: su traza se calcula (un
  solape de litología no la excluye).
- **Cada comprobación**, con conjuntos pequeños: tramos fuera de rango (DH-E09; esos tramos
  no entran en las demás comprobaciones de tramos), solapes y huecos por esquema de logueo o
  por elemento, contra el tramo más hondo anterior (DH-E10, DH-W01; contiguos, ni uno ni
  otro), códigos fuera de catálogo (DH-E11), valores primarios repetidos (DH-E12, no DH-E10),
  unidades (DH-W07), valores ≤ 0 sin marca (DH-W08), tramos cortos (DH-W09), litologías sin
  densidad (DH-W10), muestras repetidas (DH-W11) y sondeos planificados con análisis
  (DH-W12), con los umbrales en su límite.
- **Contrato**: mensajes con sus valores en español, orden determinista y entrada sin
  modificar; las filas sin boca (DH-E04) y las de un nombre repetido (DH-E01) no se
  comprueban aquí.
"""

from __future__ import annotations

import dataclasses
import math
import unittest

import numpy as np

from tests.support import dh_sets
from tests.support.package import import_geoblender

validate = import_geoblender("drillholes.validate")
desurvey = import_geoblender("drillholes.desurvey")
model = import_geoblender("drillholes.model")

INTERVAL_CODES = frozenset({
    "DH-E09", "DH-E10", "DH-E11", "DH-E12",
    "DH-W01", "DH-W07", "DH-W08", "DH-W09", "DH-W10", "DH-W11", "DH-W12",
})
"""Los códigos de esta tarea (T09)."""
WITHOUT_DEM = frozenset(validate.CODES) - {"DH-W05"}
"""Los códigos que se validan sin MDT (DH-W05 llega con la T10)."""

PARAMS = dh_sets.params()
TOLERANCE = PARAMS.depth_tolerance_m
GAP = PARAMS.gap_tolerance_m
MIN_LENGTH = PARAMS.min_interval_m
CASES = dh_sets.error_cases()
WINDOW = dh_sets.work_window()
X0, Y0, Z0 = 700_010.5, 4_400_040.5, 800.0
NAN = math.nan
UNITS = {"Au": "g/t", "Cu": "%"}


def _lithology_code(code: str, log_set: str = "lithology", density: float | None = 2.65):
    return model.LithologyCode(code, log_set=log_set, density=density,
                               density_kind=None if density is None else "ADOPTADO")


CATALOGS = model.Catalogs(
    lithology=(_lithology_code("CAL"), _lithology_code("DOL", density=2.8),
               _lithology_code("ALT", log_set="alteration", density=2.5)),
    elements=(model.Element("Au", "g/t"), model.Element("Cu", "%")),
    sectors=(model.CatalogEntry("N"),),
    groups=(model.CatalogEntry("G1"),),
    zones=(model.CatalogEntry("Z1"),),
)


def _run(case: dh_sets.ErrorCase):
    return validate.validate(case.dset, PARAMS, work_window=WINDOW,
                             stored_geom_xyz=case.stored_geom_xyz)


def _collar(name: str, depth: float | None = 100.0, k: int = 0, **fields):
    return model.Collar(name, X0 + 10.0 * k, Y0, Z0, depth, **fields)


def _set(collars, *, lithology=(), assays=(), zones=(), structures=(), catalogs=CATALOGS):
    """Un conjunto con las bocas ``collars``, cada una declarada vertical (sin incidencias
    de las desviaciones), sus tramos y los catálogos ``catalogs``."""
    stations = [model.SurveyStation(collar.name, 0.0, 0.0, -90.0, source="declared_vertical")
                for collar in collars]
    return model.DrillholeSet.from_records(
        crs=dh_sets.H25830, vertical=dh_sets.V5782, collars=collars, surveys=stations,
        lithology=lithology, assays=assays, zones=zones, structures=structures,
        catalogs=catalogs)


def _li(hole: str, start: float, end: float, code: str = "CAL", **fields):
    return model.LithologyInterval(hole, start, end, code, **fields)


def _as(hole: str | None, start: float | None, end: float | None, element: str = "Au",
        value: float | None = 1.0, unit: str | None = None, **fields):
    return model.AssayValue(hole, start, end, element, value,
                            unit or UNITS.get(element, "ppm"), **fields)


def _check(dset, **options):
    return validate.validate(dset, PARAMS, **options)


def _found(report, codes=INTERVAL_CODES) -> list[tuple]:
    return [(i.code, i.hole_name, i.depth_from, i.depth_to, i.field, i.value)
            for i in report.issues if i.code in codes]


def _issue(report, code: str, row: int, table: str | None = None):
    """La primera incidencia ``code`` de la fila ``row`` (de la tabla ``table``, si se da)."""
    return next(i for i in report.issues if i.code == code and i.row_ref == row
                and table in (None, i.table))


def _snapshot(dset) -> dict:
    """Una copia comparable de todas las columnas de un conjunto de sondeos."""
    found = {}
    for name in model.TABLES:
        columns = getattr(dset, name)
        for item in dataclasses.fields(columns):
            array = getattr(columns, item.name)
            found[(name, item.name)] = (array.tobytes() if array.dtype != object
                                        else repr(array.tolist()))
    return found


class CsvErrorsTest(unittest.TestCase):
    """CE-005-01: un caso por código, al 100 % y sin falsos positivos, y el juego limpio."""

    def test_each_case_gives_exactly_its_issues(self) -> None:
        """RF-005-16: cada caso de ``csv_errores`` da exactamente sus incidencias de DH-E09 a
        E12, W01 y W07 a W12, con código, nivel, alcance, sondeo, tabla, entrada del
        catálogo, tramo, campo y valor; los casos de los demás códigos, ninguna de estos."""
        for case in CASES:
            with self.subTest(case=case.code):
                got = [dh_sets.issue_key(issue) for issue in _run(case).issues
                       if issue.code in INTERVAL_CODES]
                want = [dh_sets.expected_key(item) for item in case.issues
                        if item["code"] in INTERVAL_CODES]
                self.assertCountEqual(got, want)

    def test_ce_005_01(self) -> None:
        """CE-005-01, RF-005-16: con todo ``csv_errores``, cada caso da exactamente sus
        incidencias de todos los códigos que se validan sin MDT (0 falsos positivos), y cada
        uno de esos códigos sale en su caso (100 %); ``csv_basico``, con los análisis en
        columnas o en filas, da 0 incidencias."""
        self.assertEqual({case.code for case in CASES} - {"DH-W05"}, WITHOUT_DEM)
        detected = set()
        for case in CASES:
            with self.subTest(case=case.code):
                issues = _run(case).issues
                codes = {issue.code for issue in issues}
                got = [dh_sets.issue_key(issue) for issue in issues]
                want = [dh_sets.expected_key(item) for item in case.issues
                        if item["code"] in WITHOUT_DEM]
                self.assertCountEqual(got, want)
                if case.code in WITHOUT_DEM:
                    self.assertIn(case.code, codes)
                detected |= codes
        self.assertEqual(detected, WITHOUT_DEM)
        for assays in ("assay_wide", "assay_long"):
            with self.subTest(assays=assays):
                report = _check(dh_sets.basico_set(assays), work_window=WINDOW)
                self.assertEqual(report.issues, ())

    def test_scope_t_exclusions(self) -> None:
        """RF-005-17: los errores de los tramos y los catálogos (alcance T) excluyen solo esa
        tabla de ese sondeo (el esquema de logueo o el elemento): ningún sondeo entero ni
        ningún registro; la traza de todos se calcula (un solape de litología no la
        excluye)."""
        cases_with_t = 0
        for case in CASES:
            want = {(int(case.dset.hole_index([item["hole"]])[0]), item["table"])
                    for item in case.issues if item["scope"] == "table"}
            if not want:
                continue
            cases_with_t += 1
            with self.subTest(case=case.code):
                excluded = _run(case).excluded()
                self.assertEqual({(hole, table) for hole, table, _ in excluded.tables}, want)
                self.assertFalse(excluded.holes.any())
                self.assertEqual(excluded.records, frozenset())
                mask = validate.hole_exclusions(case.dset, depth_tolerance_m=TOLERANCE)
                self.assertFalse(mask.any())
                self.assertTrue(desurvey.desurvey(case.dset, holes=~mask).computed.all())
        self.assertEqual(cases_with_t, 4)
        by_code = {case.code: case for case in CASES}
        self.assertEqual(_run(by_code["DH-E10"]).excluded().tables,
                         frozenset({(2, "dh_lithology", "lithology")}))
        self.assertEqual(_run(by_code["DH-E12"]).excluded().tables,
                         frozenset({(0, "dh_assay", "Au")}))


class IntervalChecksTest(unittest.TestCase):
    """Cada comprobación de los tramos, los valores y los catálogos (spec §4.4.1)."""

    def test_interval_range(self) -> None:
        """RF-005-16, RF-005-17, DH-E09: desde < 0 o ausente; hasta ausente o ≤ desde; hasta
        por debajo del fondo más la tolerancia (justo en el fondo más la tolerancia, no; sin
        profundidad total válida, no se evalúa), en la litología, los análisis (un material
        de referencia sin tramo, no) y las zonas; una incidencia por campo. Esos tramos no
        entran en las demás comprobaciones de tramos (ni solape ni tramo corto)."""
        dset = _set(
            [_collar("A-1", 50.0), _collar("A-2", 50.0, k=1), _collar("A-3", 50.0, k=2),
             _collar("A-4", None, k=3)],
            lithology=[
                _li("A-1", 0.0, 50.0), _li("A-1", -0.5, 3.0), _li("A-1", 3.0, 3.0),
                _li("A-1", 10.0, 5.0), _li("A-1", NAN, 20.0), _li("A-1", 20.0, NAN),
                _li("A-1", -1.0, -2.0),
                _li("A-2", 0.0, 50.0 + TOLERANCE), _li("A-3", 0.0, 50.02),
                _li("A-4", 0.0, 500.0)],
            assays=[_as("A-1", 0.0, 50.0), _as("A-1", 60.0, 62.0),
                    _as("A-1", None, None, qaqc_type="crm")],
            zones=[model.ZoneInterval("A-1", 5.0, 4.0, "Z1")])
        report = _check(dset)
        self.assertEqual(_found(report), [
            ("DH-E09", "A-1", -0.5, 3.0, "from_m", -0.5),
            ("DH-E09", "A-1", 3.0, 3.0, "to_m", 3.0),
            ("DH-E09", "A-1", 10.0, 5.0, "to_m", 5.0),
            ("DH-E09", "A-1", None, 20.0, "from_m", ""),
            ("DH-E09", "A-1", 20.0, None, "to_m", ""),
            ("DH-E09", "A-1", -1.0, -2.0, "from_m", -1.0),
            ("DH-E09", "A-1", -1.0, -2.0, "to_m", -2.0),
            ("DH-E09", "A-1", 60.0, 62.0, "to_m", 62.0),
            ("DH-E09", "A-1", 5.0, 4.0, "to_m", 4.0),
            ("DH-E09", "A-3", 0.0, 50.02, "to_m", 50.02),
        ])
        below = _issue(report, "DH-E09", 8)
        self.assertEqual((below.table, below.log_set), ("dh_lithology", "lithology"))
        self.assertIn("50,02 m", below.message())
        self.assertIn("0,01 m", below.message())
        self.assertEqual(_issue(report, "DH-E09", 1, "dh_assay").element, "Au")
        excluded = report.excluded()
        self.assertEqual(excluded.tables, frozenset({
            (0, "dh_lithology", "lithology"), (0, "dh_assay", "Au"),
            (0, "dh_zone_interval", None), (2, "dh_lithology", "lithology")}))
        self.assertFalse(excluded.holes[[0, 1, 2]].any())

    def test_overlaps_and_gaps(self) -> None:
        """RF-005-16, DH-E10 y DH-W01 (spec §8): por sondeo y esquema de logueo, en
        cualquier orden de filas, un tramo que empieza antes del fin del más hondo anterior
        se solapa (también uno contenido en otro o repetido entero); uno que empieza más de
        la tolerancia después deja un hueco (justo la tolerancia, no); los contiguos, ni uno
        ni otro; otro esquema de logueo no cuenta."""
        dset = _set(
            [_collar("B-1"), _collar("B-2", k=1), _collar("B-3", k=2)],
            lithology=[
                _li("B-1", 30.0, 40.0), _li("B-1", 0.0, 10.0), _li("B-1", 10.0, 30.0, "DOL"),
                _li("B-1", 40.0, 60.0), _li("B-1", 55.0, 70.0, "DOL"),
                _li("B-1", 70.0 + GAP, 80.0), _li("B-1", 81.0, 90.0),
                _li("B-1", 0.0, 100.0, "ALT", log_set="alteration"),
                _li("B-2", 0.0, 100.0), _li("B-2", 0.0, 100.0, "DOL"), _li("B-2", 10.0, 20.0),
                _li("B-2", 30.0, 40.0, "DOL"),
                _li("B-3", 0.0, 50.0), _li("B-3", 10.0, 20.0, "DOL"), _li("B-3", 60.0, 70.0),
            ])
        report = _check(dset)
        self.assertEqual(_found(report), [
            ("DH-E10", "B-1", 55.0, 60.0, "from_m", 55.0),
            ("DH-W01", "B-1", 80.0, 81.0, "from_m", 81.0),
            ("DH-E10", "B-2", 0.0, 100.0, "from_m", 0.0),
            ("DH-E10", "B-2", 10.0, 20.0, "from_m", 10.0),
            ("DH-E10", "B-2", 30.0, 40.0, "from_m", 30.0),
            ("DH-E10", "B-3", 10.0, 20.0, "from_m", 10.0),
            ("DH-W01", "B-3", 50.0, 60.0, "from_m", 60.0),
        ])
        overlap = _issue(report, "DH-E10", 4)
        self.assertEqual((overlap.table, overlap.log_set), ("dh_lithology", "lithology"))
        self.assertIn("de 55 a 60 m", overlap.message())
        self.assertIn("«lithology»", overlap.message())
        self.assertEqual(report.excluded().tables, frozenset({
            (0, "dh_lithology", "lithology"), (1, "dh_lithology", "lithology"),
            (2, "dh_lithology", "lithology")}))
        self.assertFalse(report.excluded().holes.any())

    def test_primary_assay_values(self) -> None:
        """RF-005-16, DH-E12, DH-E10 y DH-W01 en los análisis: más de un valor primario del
        mismo elemento en el mismo tramo es DH-E12 (una incidencia por cada repetido, el
        valor «» si falta), no DH-E10; un duplicado no primario, otro elemento en el mismo
        tramo o el tramo siguiente, nada; un solape o un hueco entre valores primarios del
        mismo elemento, DH-E10 o DH-W01."""
        dset = _set([_collar("C-1")], assays=[
            _as("C-1", 0.0, 2.0, value=1.0), _as("C-1", 0.0, 2.0, "Cu", 0.5),
            _as("C-1", 0.0, 2.0, value=1.1), _as("C-1", 0.0, 2.0, value=None),
            _as("C-1", 0.0, 2.0, value=1.2, qaqc_type="field_dup", is_primary=False),
            _as("C-1", 2.0, 4.0), _as("C-1", 3.0, 5.0), _as("C-1", 5.0, 7.0),
            _as("C-1", 8.0, 10.0),
        ])
        report = _check(dset)
        self.assertEqual(_found(report), [
            ("DH-E10", "C-1", 3.0, 4.0, "from_m", 3.0),
            ("DH-E12", "C-1", 0.0, 2.0, "value", 1.1),
            ("DH-E12", "C-1", 0.0, 2.0, "value", ""),
            ("DH-W01", "C-1", 7.0, 8.0, "from_m", 8.0),
        ])
        self.assertEqual({(i.table, i.element) for i in report.issues},
                         {("dh_assay", "Au")})
        self.assertIn("Au", _issue(report, "DH-E12", 2).message())
        self.assertEqual(report.excluded().tables, frozenset({(0, "dh_assay", "Au")}))

    def test_catalog_codes(self) -> None:
        """RF-005-16, RF-005-17, DH-E11: litología fuera del catálogo de su esquema de
        logueo, elemento, sector, grupo y zona (de una intersección o de un corte) fuera de
        catálogo, comparando sin mayúsculas ni espacios exteriores; excluye esa tabla
        (esquema o elemento) de ese sondeo."""
        dset = _set(
            [_collar("D-1", sector="N", group="g1 "),
             _collar("D-2", k=1, sector="S", group="G2")],
            lithology=[_li("D-1", 0.0, 10.0, " cal"), _li("D-1", 10.0, 20.0, "GRA"),
                       _li("D-1", 0.0, 20.0, "CAL", log_set="alteration"),
                       _li("D-1", 20.0, 30.0, "alt", log_set="Alteration ")],
            assays=[_as("D-1", 0.0, 2.0, "Zn"), _as("D-1", 0.0, 2.0, "au", unit="g/t")],
            zones=[model.ZoneInterval("D-1", 5.0, 6.0, "Z2"),
                   model.ZoneInterval("D-1", 6.0, 7.0, "z1")],
            structures=[model.StructureMeasure("D-1", 8.0, "fault", zone="Z3"),
                        model.StructureMeasure("D-1", 9.0, "fault")])
        report = _check(dset)
        self.assertEqual(_found(report), [
            ("DH-E11", "D-1", 10.0, 20.0, "lithology", "GRA"),
            ("DH-E11", "D-1", 0.0, 20.0, "lithology", "CAL"),
            ("DH-E11", "D-1", 0.0, 2.0, "element", "Zn"),
            ("DH-E11", "D-1", 5.0, 6.0, "zone", "Z2"),
            ("DH-E11", "D-1", 8.0, 8.0, "zone", "Z3"),
            ("DH-E11", "D-2", None, None, "sector", "S"),
            ("DH-E11", "D-2", None, None, "group", "G2"),
        ])
        self.assertEqual([i.table for i in report.issues], [
            "dh_lithology", "dh_lithology", "dh_assay", "dh_zone_interval", "dh_structure",
            "dh_collar", "dh_collar"])
        text = _issue(report, "DH-E11", 1).message()
        self.assertIn("«GRA»", text)
        self.assertIn("«lithology»", text)
        self.assertEqual(report.excluded().tables, frozenset({
            (0, "dh_lithology", "lithology"), (0, "dh_lithology", "alteration"),
            (0, "dh_assay", "Zn"), (0, "dh_zone_interval", None), (0, "dh_structure", None),
            (1, "dh_collar", None)}))
        self.assertFalse(report.excluded().holes.any())

    def test_units_and_values(self) -> None:
        """RF-005-16, DH-W07 y DH-W08 (spec §8): unidad distinta de la de su catálogo (un
        elemento sin catálogo es DH-E11, no DH-W07); valor ≤ 0 sin marca de límite de
        detección (con «<x», vacío o > 0, no; también de un elemento sin catálogo)."""
        dset = _set([_collar("E-1")], assays=[
            _as("E-1", 0.0, 2.0), _as("E-1", 2.0, 4.0, value=1000.0, unit="ppb"),
            _as("E-1", 4.0, 6.0, value=None, unit="oz/t"),
            _as("E-1", 0.0, 2.0, "Cu", 0.0), _as("E-1", 2.0, 4.0, "Cu", -0.5),
            _as("E-1", 4.0, 6.0, "Cu", 0.0, detection_flag="below_dl"),
            _as("E-1", 6.0, 8.0, "Cu", None), _as("E-1", 6.0, 8.0, "Zn", -1.0),
        ])
        report = _check(dset)
        self.assertEqual(_found(report), [
            ("DH-E11", "E-1", 6.0, 8.0, "element", "Zn"),
            ("DH-W07", "E-1", 2.0, 4.0, "unit", "ppb"),
            ("DH-W07", "E-1", 4.0, 6.0, "unit", "oz/t"),
            ("DH-W08", "E-1", 0.0, 2.0, "value", 0.0),
            ("DH-W08", "E-1", 2.0, 4.0, "value", -0.5),
            ("DH-W08", "E-1", 6.0, 8.0, "value", -1.0),
        ])
        unit = _issue(report, "DH-W07", 1).message()
        self.assertIn("ppb", unit)
        self.assertIn("g/t", unit)
        self.assertIn("-0,5", _issue(report, "DH-W08", 4).message())
        self.assertEqual(report.excluded().tables, frozenset({(0, "dh_assay", "Zn")}))

    def test_short_intervals(self) -> None:
        """RF-005-16, DH-W09: un tramo más corto que la longitud mínima, de litología o un
        valor primario (justo la longitud mínima, no; un duplicado no primario, no); sin
        campo ni valor (es un cálculo)."""
        dset = _set([_collar("F-1")], lithology=[
            _li("F-1", 0.0, 84.98), _li("F-1", 84.98, 85.0, "DOL"),
            _li("F-1", 85.0, 85.0 + MIN_LENGTH), _li("F-1", 85.0 + MIN_LENGTH, 100.0, "DOL"),
        ], assays=[_as("F-1", 0.0, 0.03), _as("F-1", 0.03, 0.04, qaqc_type="field_dup",
                                              is_primary=False)])
        report = _check(dset)
        self.assertEqual(_found(report), [
            ("DH-W09", "F-1", 84.98, 85.0, None, None),
            ("DH-W09", "F-1", 0.0, 0.03, None, None),
        ])
        text = _issue(report, "DH-W09", 1).message()
        self.assertIn("84,98", text)
        self.assertIn("0,05 m", text)

    def test_lithology_without_density(self) -> None:
        """RF-005-16, DH-W10: cada litología del catálogo sin densidad, con su código y su
        esquema de logueo, sin sondeo; al final del informe."""
        catalogs = dataclasses.replace(CATALOGS, lithology=(
            _lithology_code("CAL"), _lithology_code("DOL", density=None),
            _lithology_code("ALT", log_set="alteration", density=None)))
        dset = _set([_collar("H-1", None)], catalogs=catalogs)
        report = _check(dset)
        self.assertEqual([(i.code, i.hole, i.hole_name, i.table, i.catalog_code, i.log_set,
                           i.row_ref, i.field, i.value) for i in report.issues], [
            ("DH-E03", 0, "H-1", "dh_collar", None, None, 0, "depth", ""),
            ("DH-W10", -1, None, "dh_lithology_code", "DOL", "lithology", 1, "density", ""),
            ("DH-W10", -1, None, "dh_lithology_code", "ALT", "alteration", 2, "density", ""),
        ])
        self.assertIn("«DOL»", report.issues[1].message())
        self.assertEqual(report.excluded().tables, frozenset())

    def test_repeated_samples(self) -> None:
        """RF-005-16, DH-W11: un código de muestra (sin mayúsculas ni espacios exteriores) en
        otro tramo, del mismo sondeo o de otro: una incidencia por tramo repetido (no por
        elemento), con el primero en el mensaje; la misma muestra con otro elemento o sin
        código, nada."""
        dset = _set([_collar("G-1"), _collar("G-2", k=1)], assays=[
            _as("G-1", 0.0, 2.0, sample_id="M-1"), _as("G-1", 0.0, 2.0, "Cu", sample_id="M-1"),
            _as("G-1", 2.0, 4.0, sample_id="M-2"), _as("G-2", 0.0, 2.0, sample_id="m-1 "),
            _as("G-2", 0.0, 2.0, "Cu", sample_id="m-1 "),
            _as("G-1", 4.0, 6.0, sample_id="M-2"), _as("G-1", 6.0, 8.0),
            _as("G-1", 8.0, 10.0, sample_id="M-3"),
        ])
        report = _check(dset)
        self.assertEqual(_found(report), [
            ("DH-W11", "G-1", 4.0, 6.0, "sample_id", "M-2"),
            ("DH-W11", "G-2", 0.0, 2.0, "sample_id", "m-1 "),
        ])
        self.assertEqual([i.row_ref for i in report.issues], [5, 3])
        text = report.issues[1].message()
        self.assertIn("«G-1»", text)
        self.assertIn("de 0 a 2 m", text)

    def test_planned_with_assays(self) -> None:
        """RF-005-16, DH-W12: un sondeo planificado con análisis (sin análisis, o sin
        planificar, nada)."""
        dset = _set([_collar("P-1", planned=True), _collar("P-2", k=1, planned=True),
                     _collar("P-3", k=2)],
                    assays=[_as("P-1", 0.0, 2.0), _as("P-3", 0.0, 2.0)])
        report = _check(dset)
        self.assertEqual(_found(report), [("DH-W12", "P-1", None, None, "planned", True)])
        self.assertEqual((report.issues[0].table, report.issues[0].row_ref), ("dh_collar", 0))
        self.assertIn("planificado", report.issues[0].message())


class ContractTest(unittest.TestCase):
    def test_messages(self) -> None:
        """RF-005-16: cada código de esta tarea tiene su mensaje (``msgid`` en inglés con su
        español; la cobertura y los marcadores, en ``test_validate_holes``)."""
        self.assertLessEqual(INTERVAL_CODES,
                             {key.split(".")[0] for key in validate.MESSAGES})

    def test_unchecked_records(self) -> None:
        """RF-005-16, RF-005-17: las filas de un sondeo sin boca (DH-E04) y las de un nombre
        repetido (DH-E01) no se comprueban aquí: no se sabe de qué boca son."""
        dset = _set([_collar("J-1"), _collar(" j-1", k=1, planned=True)],
                    lithology=[_li("J-1", 0.0, 10.0, "GRA"), _li("J-1", 5.0, 10.0),
                               _li("X-9", 0.0, -1.0)],
                    assays=[_as("J-1", 0.0, 2.0, value=0.0), _as("X-9", 0.0, 2.0, "Zn", 0.0)])
        self.assertEqual([i.code for i in _check(dset).issues],
                         ["DH-E01", "DH-E04", "DH-E04"])

    def test_order_and_input_unchanged(self) -> None:
        """RF-005-16: el informe sale en el mismo orden cada vez (por boca, código, tabla y
        fila; lo que no es de una boca, al final) y la entrada no cambia."""
        catalogs = dataclasses.replace(CATALOGS, lithology=(_lithology_code("CAL", density=None),
                                                            _lithology_code("DOL")))
        dset = _set([_collar("O-1"), _collar("O-2", k=1, planned=True)],
                    lithology=[_li("O-2", 5.0, 10.0), _li("O-2", 0.0, 6.0, "GRA"),
                               _li("X-1", 0.0, 1.0)],
                    assays=[_as("O-2", 0.0, 2.0, value=-1.0), _as("O-1", 0.0, 0.01)],
                    catalogs=catalogs)
        before = _snapshot(dset)
        first, second = _check(dset), _check(dset)
        self.assertEqual(first.issues, second.issues)
        self.assertEqual(_snapshot(dset), before)
        self.assertEqual([(i.code, i.hole, i.table, i.row_ref) for i in first.issues], [
            ("DH-W09", 0, "dh_assay", 1),
            ("DH-E10", 1, "dh_lithology", 0),
            ("DH-E11", 1, "dh_lithology", 1),
            ("DH-W08", 1, "dh_assay", 0),
            ("DH-W12", 1, "dh_collar", 1),
            ("DH-E04", -1, "dh_lithology", 2),
            ("DH-W10", -1, "dh_lithology_code", 0),
        ])
        np.testing.assert_array_equal(first.excluded().holes, [False, False])


if __name__ == "__main__":
    unittest.main()
