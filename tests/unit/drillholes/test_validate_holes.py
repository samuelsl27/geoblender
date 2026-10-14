# SPDX-License-Identifier: GPL-3.0-or-later
"""Validación de las bocas y las desviaciones (spec 005, T08; HU-005-3; RF-005-16,
RF-005-17; spec §4.4.1 y §8; plan 005 §5.3.2, §5.4 y §5.6.6).

- ``tests/data/dh/csv_errores``: cada caso de DH-E01 a DH-E08, DH-W02, DH-W03, DH-W04,
  DH-W06, DH-W14, DH-W15 y DH-W16 da **exactamente** sus incidencias (código, nivel, alcance,
  sondeo, tabla, tramo o profundidad, campo y valor), y los demás casos, ninguna de esos
  códigos (0 falsos positivos); ``csv_basico`` da 0 incidencias.
- **Alcance S** (RF-005-17): ``hole_exclusions`` (la parte de ``dh.desurvey``) da los mismos
  sondeos que el informe, solo los de los errores de alcance S; con ellos fuera, las trazas
  de los demás se calculan; un aviso no excluye nada y DH-E04 solo excluye su registro.
- **Cada comprobación**, con conjuntos pequeños: nombres repetidos, coordenadas y profundidad
  total, estaciones (repetidas, por encima de la boca, por debajo del fondo con su
  tolerancia), ángulos (360° vale), prolongaciones (solo de estaciones medidas, las mismas
  que avisa la traza), cambio de dirección, inclinaciones positivas, ventana de trabajo,
  posición en la capa, profundidad deducida y registros sin boca.
- **Contrato**: umbrales, nivel y alcance de cada código de la tabla 4.4.1, mensajes en
  español en el catálogo de idioma (con los mismos marcadores y coma decimal), orden
  determinista y entrada sin modificar.
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
georef = import_geoblender("core.georef")
i18n = import_geoblender("core.i18n")

IMPLEMENTED = frozenset({
    "DH-E01", "DH-E02", "DH-E03", "DH-E04", "DH-E05", "DH-E06", "DH-E07", "DH-E08",
    "DH-W02", "DH-W03", "DH-W04", "DH-W06", "DH-W14", "DH-W15", "DH-W16",
    # T09 (tramos, valores y catálogos; sus pruebas, en test_validate_intervals)
    "DH-E09", "DH-E10", "DH-E11", "DH-E12",
    "DH-W01", "DH-W07", "DH-W08", "DH-W09", "DH-W10", "DH-W11", "DH-W12",
})
"""Los códigos que valida ``validate`` (T08 y T09); T10 añade DH-W05."""

PARAMS = dh_sets.params()
TOLERANCE = PARAMS.depth_tolerance_m
CASES = dh_sets.error_cases()
WINDOW = dh_sets.work_window()
X0, Y0, Z0 = 700_010.5, 4_400_040.5, 800.0
NAN = math.nan


def _run(case: dh_sets.ErrorCase):
    return validate.validate(case.dset, PARAMS, work_window=WINDOW,
                             stored_geom_xyz=case.stored_geom_xyz)


def _collar(name: str, depth: float | None = 100.0, k: int = 0, **fields):
    xyz = {"x": X0 + 10.0 * k, "y": Y0, "z": Z0}
    xyz.update({axis: fields.pop(axis) for axis in ("x", "y", "z") if axis in fields})
    return model.Collar(name, xyz["x"], xyz["y"], xyz["z"], depth, **fields)


def _st(hole: str, md: float, azimuth: float = 0.0, inclination: float = -90.0,
        source: str = "measured"):
    return model.SurveyStation(hole, md, azimuth, inclination, source=source)


def _vertical(hole: str):
    """La estación de un sondeo declarado vertical (sin aviso de prolongación)."""
    return _st(hole, 0.0, source="declared_vertical")


def _set(collars, stations=(), **children):
    return model.DrillholeSet.from_records(crs=dh_sets.H25830, vertical=dh_sets.V5782,
                                           collars=collars, surveys=stations, **children)


def _check(dset, **options):
    return validate.validate(dset, PARAMS, **options)


def _found(report) -> list[tuple]:
    return [(i.code, i.hole_name, i.depth_from, i.depth_to, i.field, i.value)
            for i in report.issues]


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
    """CE-005-01 (lo de esta tarea): un caso por código y el juego limpio."""

    def test_each_case_gives_exactly_its_issues(self) -> None:
        """RF-005-16: cada caso de ``csv_errores`` da exactamente sus incidencias de
        DH-E01 a E08, W02, W03, W04, W06, W14, W15 y W16, con código, nivel, alcance,
        sondeo, tabla, tramo o profundidad, campo y valor; los casos de los demás códigos
        no dan ninguna de estos (0 falsos positivos)."""
        for case in CASES:
            with self.subTest(case=case.code):
                got = [dh_sets.issue_key(issue) for issue in _run(case).issues]
                want = [dh_sets.expected_key(item) for item in case.issues
                        if item["code"] in IMPLEMENTED]
                self.assertCountEqual(got, want)

    def test_every_code_is_detected(self) -> None:
        """RF-005-16: cada código de esta tarea sale en su caso, con un mensaje en español
        que no es su ``msgid`` (inglés) y sin marcadores sin rellenar."""
        seen = set()
        for case in CASES:
            for issue in _run(case).issues:
                seen.add(issue.code)
                text = issue.message()
                self.assertNotEqual(text, issue.message_id)
                self.assertNotIn("{", text)
                self.assertTrue(issue.message("en"))
        self.assertEqual(seen, IMPLEMENTED)

    def test_clean_set_has_no_issues(self) -> None:
        """RF-005-16: ``csv_basico`` (con los análisis en columnas o en filas) da 0
        incidencias con la ventana de trabajo, y no excluye nada."""
        for assays in ("assay_wide", "assay_long"):
            with self.subTest(assays=assays):
                dset = dh_sets.basico_set(assays)
                report = _check(dset, work_window=WINDOW)
                self.assertEqual(report.issues, ())
                excluded = report.excluded()
                self.assertFalse(excluded.holes.any())
                self.assertEqual(excluded.records, frozenset())
                self.assertFalse(validate.hole_exclusions(
                    dset, depth_tolerance_m=TOLERANCE).any())

    def test_scope_s_exclusions(self) -> None:
        """RF-005-17: ``hole_exclusions`` da los sondeos del informe con un error de alcance
        S, y solo esos; quitándolos, las trazas de los demás se calculan; los avisos no
        excluyen, DH-E04 solo excluye sus registros y los errores de alcance T (T09), solo
        su tabla de su sondeo."""
        for case in CASES:
            with self.subTest(case=case.code):
                report = _run(case)
                mask = validate.hole_exclusions(case.dset, depth_tolerance_m=TOLERANCE)
                excluded = report.excluded()
                np.testing.assert_array_equal(excluded.holes, mask)
                names = {model.name_key(name)
                         for name in case.dset.collars.name[mask].tolist()}
                want = {model.name_key(item["hole"]) for item in case.issues
                        if item["scope"] == "hole"}
                self.assertEqual(names, want)
                traces = desurvey.desurvey(case.dset, holes=~mask)
                np.testing.assert_array_equal(traces.computed, ~mask)
                records = {(i.table, i.row_ref) for i in report.issues if i.code == "DH-E04"}
                self.assertEqual(excluded.records, frozenset(records))
                tables = {(int(case.dset.hole_index([item["hole"]])[0]), item["table"])
                          for item in case.issues if item["scope"] == "table"}
                self.assertEqual({(hole, table) for hole, table, _ in excluded.tables},
                                 tables)


class HoleChecksTest(unittest.TestCase):
    """Cada comprobación de las bocas y las desviaciones (spec §4.4.1)."""

    def test_repeated_names(self) -> None:
        """RF-005-16, RF-005-17, DH-E01: un nombre repetido sin distinguir mayúsculas ni
        espacios exteriores da una incidencia por repetición (el sondeo, la primera
        grafía; el valor, la repetida), excluye todas sus bocas y no da más incidencias
        (sus filas hijas no se sabe de cuál son)."""
        dset = _set([_collar("A-1"), _collar(" a-1", k=1, z=None), _collar("B-1", k=2),
                     _collar("A-1 ", k=3)],
                    [_st("A-1", 0.0), _vertical("B-1"), _st("A-1", 0.0)])
        report = _check(dset)
        self.assertEqual(_found(report), [
            ("DH-E01", "A-1", None, None, "name", " a-1"),
            ("DH-E01", "A-1", None, None, "name", "A-1 "),
        ])
        self.assertEqual([(i.hole, i.row_ref, i.table, str(i.scope)) for i in report.issues],
                         [(0, 1, "dh_collar", "hole"), (0, 3, "dh_collar", "hole")])
        np.testing.assert_array_equal(report.excluded().holes, [True, True, False, True])
        np.testing.assert_array_equal(
            validate.hole_exclusions(dset, depth_tolerance_m=TOLERANCE),
            [True, True, False, True])

    def test_collar_coordinates_and_depth(self) -> None:
        """RF-005-16, DH-E02 y DH-E03: una incidencia por coordenada ausente o no finita y
        por profundidad total ausente (no deducible), ≤ 0 o no finita; el valor, el número
        guardado o «» si no hay."""
        inf = math.inf
        dset = _set([_collar("P-1", x=None, z=inf), _collar("P-2", 0.0, k=1),
                     _collar("P-3", -5.0, k=2), _collar("P-4", None, k=3),
                     _collar("P-5", inf, k=4), _collar("P-6", k=5, y=-inf)],
                    [_st(f"P-{k}", 0.0) for k in range(1, 7)])
        self.assertEqual(_found(_check(dset)), [
            ("DH-E02", "P-1", None, None, "x", ""),
            ("DH-E02", "P-1", None, None, "z", inf),
            ("DH-E03", "P-2", None, None, "depth", 0.0),
            ("DH-E03", "P-3", None, None, "depth", -5.0),
            ("DH-E03", "P-4", None, None, "depth", ""),
            ("DH-E03", "P-5", None, None, "depth", inf),
            ("DH-E02", "P-6", None, None, "y", -inf),
        ])

    def test_station_depths(self) -> None:
        """RF-005-16, DH-E05, DH-E06 y DH-E07: sin estaciones; repetidas (una incidencia por
        cada repetición); por encima de la boca o sin profundidad; por debajo del fondo
        más la tolerancia (justo en el fondo más la tolerancia, no)."""
        dset = _set([_collar("Q-1", 50.0), _collar("Q-2", 50.0, k=1),
                     _collar("Q-3", 50.0, k=2), _collar("Q-4", 50.0, k=3)], [
            _st("Q-1", 20.0), _st("Q-1", 0.0), _st("Q-1", 20.0), _st("Q-1", 20.0),
            _st("Q-2", -0.5), _st("Q-2", 0.0), _st("Q-2", NAN),
            _st("Q-3", 0.0), _st("Q-3", 50.0 + TOLERANCE), _st("Q-3", 50.02),
        ])
        self.assertEqual(_found(_check(dset)), [
            ("DH-E06", "Q-1", 20.0, 20.0, "depth", 20.0),
            ("DH-E06", "Q-1", 20.0, 20.0, "depth", 20.0),
            ("DH-E07", "Q-2", -0.5, -0.5, "depth", -0.5),
            ("DH-E07", "Q-2", None, None, "depth", ""),
            ("DH-E07", "Q-3", 50.02, 50.02, "depth", 50.02),
            ("DH-E05", "Q-4", None, None, None, None),
        ])
        np.testing.assert_array_equal(
            validate.hole_exclusions(dset, depth_tolerance_m=TOLERANCE), [True] * 4)
        self.assertFalse(validate.hole_exclusions(dset, depth_tolerance_m=0.05)[2])

    def test_angles(self) -> None:
        """RF-005-16, DH-E08 (spec §8): 0°, 360° (se guarda como 0) y ±90° valen; 361°,
        −0,001°, un azimut ausente y 90,001° no; una incidencia por campo."""
        dset = _set([_collar("R-1", 20.0), _collar("R-2", k=1)], [
            _st("R-1", 0.0, 0.0, -90.0), _st("R-1", 10.0, 360.0, -90.0),
            _st("R-1", 20.0, 359.99, 90.0),
            _st("R-2", 0.0, 361.0, -60.0), _st("R-2", 10.0, -0.001, -60.0),
            _st("R-2", 20.0, NAN, 90.001), _st("R-2", 30.0, 10.0, -90.5),
        ])
        report = _check(dset)
        self.assertEqual([item for item in _found(report) if item[0] == "DH-E08"], [
            ("DH-E08", "R-2", 0.0, 0.0, "azimuth", 361.0),
            ("DH-E08", "R-2", 10.0, 10.0, "azimuth", -0.001),
            ("DH-E08", "R-2", 20.0, 20.0, "azimuth", ""),
            ("DH-E08", "R-2", 20.0, 20.0, "inclination", 90.001),
            ("DH-E08", "R-2", 30.0, 30.0, "inclination", -90.5),
        ])
        np.testing.assert_array_equal(report.excluded().holes, [False, True])

    def test_prolongations_only_of_measured_stations(self) -> None:
        """RF-005-16, DH-W02 y DH-W03: la primera estación medida por debajo de la boca y la
        última por encima del fondo, con su tramo; la orientación en boca y la vertical
        declarada, no; las mismas que avisa la traza (``desurvey.TraceWarning``)."""
        dset = _set([_collar("T-1", 150.0), _collar("T-2", 80.0, k=1),
                     _collar("T-3", 60.0, k=2), _collar("T-4", 40.0, k=3)], [
            _st("T-1", 30.0, 45.0, -60.0), _st("T-1", 120.0, 45.0, -60.0),
            _st("T-2", 0.0, 300.0, -75.0, source="collar"),
            _st("T-3", 0.0, source="declared_vertical"),
            _st("T-4", 0.0), _st("T-4", 20.0),
        ])
        report = _check(dset)
        self.assertEqual(_found(report), [
            ("DH-W02", "T-1", 0.0, 30.0, "depth", 30.0),
            ("DH-W03", "T-1", 120.0, 150.0, "depth", 120.0),
            ("DH-W03", "T-4", 20.0, 40.0, "depth", 20.0),
        ])
        traced = {(w.code, w.name, w.depth_from, w.depth_to)
                  for w in desurvey.desurvey(dset).warnings}
        self.assertEqual({(i.code, i.hole_name, i.depth_from, i.depth_to)
                          for i in report.issues}, traced)
        self.assertFalse(report.excluded().holes.any())

    def test_dogleg(self) -> None:
        """RF-005-16, DH-W04: el cambio de dirección entre dos estaciones, β·30/ΔMD, por
        encima del umbral (°/30 m), con el par de estaciones; el campo es el ángulo que más
        cambia (el azimut por su componente horizontal); un sondeo excluido (DH-E07) no se
        evalúa."""
        dset = _set([_collar("U-1", 60.0), _collar("U-2", 30.0, k=1),
                     _collar("U-3", 30.0, k=2), _collar("U-4", 20.0, k=3)], [
            _st("U-1", 0.0, 30.0, -60.0), _st("U-1", 30.0, 30.0, -62.9),
            _st("U-1", 60.0, 30.0, -66.1),
            _st("U-2", 0.0, 355.0, -45.0), _st("U-2", 30.0, 5.0, -45.0),
            _st("U-3", 0.0, 0.0, -90.0), _st("U-3", 30.0, 170.0, -89.0),
            _st("U-4", 0.0, 0.0, -45.0), _st("U-4", 10.0, 90.0, -45.0),
            _st("U-4", 25.0, 90.0, -45.0),
        ])
        self.assertEqual(_found(_check(dset)), [
            ("DH-W04", "U-1", 30.0, 60.0, "inclination", None),
            ("DH-W04", "U-2", 0.0, 30.0, "azimuth", None),
            ("DH-E07", "U-4", 25.0, 25.0, "depth", 25.0),
        ])
        rate = _check(dset).issues[0].message_args
        self.assertAlmostEqual(dict(rate)["rate"], 3.2, delta=0.01)

    def test_positive_inclination(self) -> None:
        """RF-005-16, DH-W14 (spec §8): todas las estaciones con la inclinación > 0; con
        una ≤ 0, no."""
        dset = _set([_collar("V-1"), _collar("V-2", k=1)], [
            _st("V-1", 0.0, 10.0, 60.0), _st("V-1", 50.0, 10.0, 60.0),
            _st("V-2", 0.0, 10.0, 60.0), _st("V-2", 50.0, 10.0, 0.0),
        ])
        found = [item for item in _found(_check(dset)) if item[0] == "DH-W14"]
        self.assertEqual(found, [("DH-W14", "V-1", None, None, "inclination", None)])

    def test_work_window(self) -> None:
        """RF-005-16, DH-W06: la boca fuera de la ventana de trabajo (el borde es dentro);
        sin X o Y (DH-E02) o sin ventana, no se evalúa."""
        window = georef.Window(X0, Y0 - 10.0, X0 + 20.0, Y0 + 10.0)
        dset = _set([_collar("W-1"), _collar("W-2", k=2), _collar("W-3", k=3),
                     _collar("W-4", k=1, y=Y0 + 10.0), _collar("W-5", k=9, y=None)],
                    [_vertical(f"W-{k}") for k in range(1, 6)])
        self.assertEqual(_found(_check(dset, work_window=window)), [
            ("DH-W06", "W-3", None, None, None, None),
            ("DH-E02", "W-5", None, None, "y", ""),
        ])
        self.assertEqual([i.code for i in _check(dset).issues], ["DH-E02"])

    def test_moved_collar(self) -> None:
        """RF-005-16, DH-W15 (spec §8): la posición de la boca en la capa distinta de su
        X, Y, Z (un milímetro basta; la que falta en las dos, igual); sin posición, no se
        evalúa. Una posición que no es (bocas, 3) en float64 es un error del programa."""
        dset = _set([_collar("G-1"), _collar("G-2", k=1), _collar("G-3", k=2, z=None),
                     _collar("G-4", k=3)], [_vertical(f"G-{k}") for k in range(1, 5)])
        geom = np.column_stack((dset.collars.x, dset.collars.y, dset.collars.z))
        geom[1, 2] += 0.001
        geom[3, 0] = NAN
        found = [item for item in _found(_check(dset, stored_geom_xyz=geom))
                 if item[0] == "DH-W15"]
        self.assertEqual(found, [("DH-W15", "G-2", None, None, "geom", None),
                                 ("DH-W15", "G-4", None, None, "geom", None)])
        with self.assertRaises(ValueError):
            _check(dset, stored_geom_xyz=geom[:3])
        with self.assertRaises(TypeError):
            _check(dset, stored_geom_xyz=geom.astype(np.float32))

    def test_deduced_depth(self) -> None:
        """RF-005-16, DH-W16 y DH-E03 (spec §8): sin profundidad total, la más honda de la
        última estación y del último hasta (litología, análisis, zonas), CALCULADO, con
        DH-W16 (el valor de la fuente, «»); sin nada de donde deducirla, sigue ausente y es
        DH-E03; la que trae la fuente no cambia; la entrada no cambia."""
        dset = _set(
            [_collar("D-1", None), _collar("D-2", None, k=1), _collar("D-3", None, k=2),
             _collar("D-4", 70.0, k=3)],
            [_st("D-1", 0.0), _st("D-1", 40.0), _st("D-2", 0.0), _st("D-3", 0.0),
             _st("D-4", 0.0), _st("D-4", 90.0)],
            lithology=[model.LithologyInterval("D-1", 0.0, 52.5, "CAL"),
                       model.LithologyInterval("D-4", 0.0, 95.0, "CAL")],
            assays=[model.AssayValue("D-2", 10.0, 12.0, "Au", 1.0, "g/t")],
            zones=[model.ZoneInterval("D-1", 50.0, 51.0, "Z1")])
        before = _snapshot(dset)
        deduced = validate.deduce_depths(dset)
        self.assertEqual(_snapshot(dset), before)
        np.testing.assert_array_equal(deduced.collars.depth, [52.5, 12.0, NAN, 70.0])
        kinds = model.CollarColumns.code_values("depth_kind")
        self.assertEqual([kinds[k] for k in deduced.collars.depth_kind.tolist()],
                         ["CALCULADO", "CALCULADO", "MEDIDO", "MEDIDO"])
        report = _check(deduced)
        self.assertEqual([item for item in _found(report)
                          if item[0] in ("DH-W16", "DH-E03")], [
            ("DH-W16", "D-1", None, None, "depth", ""),
            ("DH-W16", "D-2", None, None, "depth", ""),
            ("DH-E03", "D-3", None, None, "depth", ""),
        ])
        w16 = next(i for i in report.issues if i.code == "DH-W16")
        self.assertIn("52,5 m", w16.message())
        self.assertIs(validate.deduce_depths(deduced), deduced)

    def test_records_without_collar(self) -> None:
        """RF-005-16, RF-005-17, DH-E04 (alcance R): una estación, un tramo, un análisis,
        una intersección o un corte de un sondeo sin boca, con su tramo o profundidad; un
        material de referencia sin sondeo, no; solo se excluye el registro."""
        dset = _set([_collar("K-1")], [_vertical("K-1"), _st("X-1", 5.0)],
                    lithology=[model.LithologyInterval("X-2", 0.0, 3.0, "CAL")],
                    assays=[model.AssayValue("X-3", 1.0, 2.0, "Au", 1.0, "g/t"),
                            model.AssayValue(None, None, None, "Au", 1.0, "g/t",
                                             qaqc_type="crm"),
                            model.AssayValue(None, 4.0, 5.0, "Au", 1.0, "g/t")],
                    zones=[model.ZoneInterval("X-4", 7.0, 8.0, "Z1")],
                    structures=[model.StructureMeasure("X-5", 9.0, "fault")])
        report = _check(dset)
        self.assertEqual(_found(report), [
            ("DH-E04", "X-1", 5.0, 5.0, "hole", "X-1"),
            ("DH-E04", "X-2", 0.0, 3.0, "hole", "X-2"),
            ("DH-E04", "X-3", 1.0, 2.0, "hole", "X-3"),
            ("DH-E04", None, 4.0, 5.0, "hole", ""),
            ("DH-E04", "X-4", 7.0, 8.0, "hole", "X-4"),
            ("DH-E04", "X-5", 9.0, 9.0, "hole", "X-5"),
        ])
        self.assertEqual([(i.table, i.row_ref, i.hole) for i in report.issues], [
            ("dh_survey", 1, -1), ("dh_lithology", 0, -1), ("dh_assay", 0, -1),
            ("dh_assay", 2, -1), ("dh_zone_interval", 0, -1), ("dh_structure", 0, -1),
        ])
        excluded = report.excluded()
        self.assertFalse(excluded.holes.any())
        self.assertEqual(excluded.records, frozenset({
            ("dh_survey", 1), ("dh_lithology", 0), ("dh_assay", 0), ("dh_assay", 2),
            ("dh_zone_interval", 0), ("dh_structure", 0)}))
        self.assertEqual(report.issues[1].log_set, "lithology")
        self.assertEqual(report.issues[2].element, "Au")


class ContractTest(unittest.TestCase):
    def test_params(self) -> None:
        """RF-005-16: los umbrales son números finitos ≥ 0 en float64 (de ``core.params``;
        sin valor por defecto: no se escriben a mano)."""
        good = dataclasses.asdict(PARAMS)
        self.assertEqual(set(good), {"depth_tolerance_m", "gap_tolerance_m", "min_interval_m",
                                     "dogleg_max_deg_30m", "collar_dem_tolerance_m"})
        self.assertIs(type(validate.ValidationParams(**{**good, "gap_tolerance_m": 1})
                           .gap_tolerance_m), float)
        for name in good:
            for wrong, error in ((-0.01, ValueError), (NAN, ValueError),
                                 (math.inf, ValueError), (True, TypeError), ("1", TypeError)):
                with self.subTest(name=name, wrong=wrong), self.assertRaises(error):
                    validate.ValidationParams(**{**good, name: wrong})
        with self.assertRaises(TypeError):
            validate.ValidationParams(depth_tolerance_m=0.01)

    def test_codes_of_the_spec(self) -> None:
        """RF-005-16, RF-005-17: los códigos de la tabla 4.4.1 (sin DH-W13, R-14) con su
        nivel y su alcance (S, T o R; los avisos, ninguno)."""
        hole = ("DH-E01", "DH-E02", "DH-E03", "DH-E05", "DH-E06", "DH-E07", "DH-E08")
        table = ("DH-E09", "DH-E10", "DH-E11", "DH-E12")
        warnings = tuple(f"DH-W{k:02d}" for k in (*range(1, 13), 14, 15, 16))
        expected = {**{code: ("error", "hole") for code in hole},
                    "DH-E04": ("error", "record"),
                    **{code: ("error", "table") for code in table},
                    **{code: ("warning", None) for code in warnings}}
        self.assertEqual({code: (str(level), None if scope is None else str(scope))
                          for code, (level, scope) in validate.CODES.items()}, expected)
        with self.assertRaises(ValueError):
            validate.Issue("DH-W13", -1, None, "dh_assay", message_id="x")
        issue = validate.Issue("DH-E03", 0, "S-1", "dh_collar", message_id="x")
        self.assertEqual((issue.level, issue.scope), ("error", "hole"))

    def test_messages_in_the_language_catalog(self) -> None:
        """RF-005-16: cada mensaje tiene su ``msgid`` en inglés y su español en
        ``core/i18n/messages.toml`` con los mismos marcadores; los números salen con coma
        decimal en español y con punto en inglés."""
        msgids = sorted(validate.MESSAGES.values())
        self.assertEqual(i18n.untranslated(msgids), [])
        table = i18n.load_messages()
        for msgid in msgids:
            with self.subTest(msgid=msgid):
                self.assertEqual(i18n.placeholders(table[msgid]), i18n.placeholders(msgid))
        dset = _set([_collar("M-1", 150.0)], [_st("M-1", 0.0), _st("M-1", 150.02)])
        issue = _check(dset).issues[0]
        self.assertEqual(dict(issue.message_args),
                         {"depth": 150.02, "bottom": 150.0, "tolerance": TOLERANCE})
        self.assertIn("150,02 m", issue.message())
        self.assertIn("0,01 m", issue.message())
        self.assertIn("150.02 m", issue.message("en"))
        with self.assertRaises(ValueError):
            issue.message("fr")

    def test_order_and_input_unchanged(self) -> None:
        """RF-005-16: el informe sale en el mismo orden cada vez (por boca y código; los
        registros sin boca, al final) y la entrada no cambia."""
        case = next(c for c in CASES if c.code == "DH-E08")
        before = _snapshot(case.dset)
        first, second = _run(case), _run(case)
        self.assertEqual(first.issues, second.issues)
        self.assertEqual(first.hole_count, len(case.dset.collars))
        self.assertEqual(_snapshot(case.dset), before)
        dset = _set([_collar("O-1", None), _collar("O-2", k=1)],
                    [_vertical("O-2"), _st("Z-9", 1.0), _st("O-1", 0.0)])
        self.assertEqual([(i.code, i.hole) for i in _check(dset).issues],
                         [("DH-E03", 0), ("DH-E04", -1)])
        with self.assertRaises(TypeError):
            validate.validate("no", PARAMS)


if __name__ == "__main__":
    unittest.main()
