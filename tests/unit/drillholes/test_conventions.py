# SPDX-License-Identifier: GPL-3.0-or-later
"""Convenios de los sondeos: inclinación interna, azimut de cuadrícula, convergencia en las
bocas y unidades de las leyes (spec 005, T04; HU-005-1; plan 005 §5.3.2, §5.4 y §5.6.12).

- **RF-005-28**: la inclinación positiva hacia abajo y la medida desde la vertical pasan a la
  interna (desde la horizontal, negativa hacia abajo) de forma exacta: las variantes
  ``positive_dip`` y ``from_vertical`` de ``tests/data/dh/csv_convenios`` dan, bit a bit, las
  estaciones de ``csv_basico``; desde la vertical, el decimal de la fuente menos 90 (8,04 →
  −81,96, no −81,96000000000001).
- **RF-005-27**: el azimut magnético y el geográfico pasan al de cuadrícula con
  A = (A_m + δ − γ) mod 360, γ la convergencia en la boca que da el ``CrsService`` (aquí, el
  falso de ``tests.support.dh_fakes``, que cumple el puerto de la 006 tal cual); cada estación
  conserva el azimut medido, su referencia, δ y γ. La variante ``magnetic`` da, bit a bit,
  los azimutes de ``csv_basico`` (S-03 pasa por 0°); 360 → 0, y un azimut fuera de [0, 360]
  no se corrige (lo ve la validación, DH-E08).
- **RF-005-29**: g/t, ppm, ppb y % se convierten con el factor exacto de ``core.units`` (el
  mismo resultado, bit a bit, que ``core.units.convert``), conservando el valor y la unidad
  originales: los análisis de ``csv_convenios`` (ppb, g/t y ppm) dan los de ``csv_basico``.

Los casos calculados a mano y la convergencia frente a Snyder con el servicio real de la 006
están en ``tests/referencia/dh/test_convenios.py``.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import math
import random
import unittest

import numpy as np

from tests.support.dh_fakes import FakeCrsService
from tests.support.package import import_geoblender
from tests.support.repo import ROOT

conventions = import_geoblender("drillholes.conventions")
model = import_geoblender("drillholes.model")
units = import_geoblender("core.units")
georef = import_geoblender("core.georef")
ports = import_geoblender("gis.ports")
csv_tables = import_geoblender("interop.csv_tables")

CATALOG = georef.load_catalog()
H25830 = CATALOG.horizontal(25830)
V5782 = CATALOG.vertical(5782)

DATA = ROOT / "tests" / "data" / "dh"
BASICO = DATA / "csv_basico"
CONVENIOS = DATA / "csv_convenios"

Inc = model.InclinationConvention
Ref = model.AzimuthRef
Flag = model.DetectionFlag
GRADES = ("g/t", "ppm", "ppb", "%")


def _bits(values: np.ndarray) -> list[int]:
    """Los bits de cada float64 (distingue −0,0 de 0,0); un NaN (ausente), el mismo NaN."""
    array = np.array(values, dtype=np.float64)
    array[np.isnan(array)] = math.nan
    return array.view(np.int64).tolist()


def _floats(*values: float) -> np.ndarray:
    return np.array(values, dtype=np.float64)


def _number(text: str, decimal: str) -> float:
    return float(text.replace(",", ".") if decimal == "," else text)


def _read(path, separator: str):
    return csv_tables.read_table(path, encoding="utf-8", separator=separator)


def _dset(folder, collar_file: str, survey_file: str, separator: str, decimal: str):
    """Bocas y estaciones de un juego de ``tests/data/dh``, tal como vienen (la orientación de
    una boca, una estación ``collar`` a 0 m delante de las medidas)."""
    collars, stations = [], []
    for row in _read(folder / collar_file, separator).rows:
        name, x, y, z, depth, azimuth, inclination = row[:7]
        collars.append(model.Collar(name, _number(x, decimal), _number(y, decimal),
                                    _number(z, decimal), _number(depth, decimal)))
        if azimuth:
            stations.append(model.SurveyStation(
                name, 0.0, _number(azimuth, decimal), _number(inclination, decimal),
                source="collar"))
    for name, depth, azimuth, inclination in _read(folder / survey_file, separator).rows:
        stations.append(model.SurveyStation(name, _number(depth, decimal),
                                            _number(azimuth, decimal),
                                            _number(inclination, decimal)))
    return model.DrillholeSet.from_records(crs=H25830, vertical=V5782, collars=collars,
                                           surveys=stations)


def _basico():
    return _dset(BASICO, "bocas.csv", "desviaciones.csv", ";", ",")


def _variants() -> dict:
    return json.loads((CONVENIOS / "esperado.json").read_text(encoding="utf-8"))["variants"]


def _variant(name: str):
    variant = _variants()[name]
    return variant, _dset(CONVENIOS, variant["collar"], variant["survey"], ",", ".")


def _declaration(azimuth_ref, inclination, declination=None):
    return model.SourceDeclaration(
        crs=H25830, vertical=V5782, azimuth_ref=azimuth_ref, declination_deg=declination,
        inclination_convention=inclination, units={},
        value_rules=model.ValueRules(decimal_mark="."), all_vertical=True)


def _code(columns, field: str, value) -> int:
    return columns.code_values(field).index(value)


def _value(text: str, decimal: str) -> tuple[float | None, object]:
    """Un valor de laboratorio de los CSV de prueba («<x», «>x», vacío o número)."""
    if not text:
        return None, Flag.OK
    flag = {"<": Flag.BELOW_DL, ">": Flag.ABOVE_UL}.get(text[0], Flag.OK)
    return _number(text.lstrip("<>"), decimal), flag


def _assays(path, separator: str, decimal: str, *, reported: bool = True):
    rows = []
    for hole, start, end, sample, element, text, unit in _read(path, separator).rows:
        value, flag = _value(text, decimal)
        rows.append(model.AssayValue(
            hole, _number(start, decimal), _number(end, decimal), element, value, unit,
            detection_flag=flag, reported_value=(text or None) if reported else None,
            sample_id=sample))
    return model.AssayColumns.from_records(rows, model.CollarColumns.empty())


def _snapshot(columns) -> dict[str, list]:
    """Una copia comparable de todas las columnas (los float64 por sus bits)."""
    found = {}
    for item in dataclasses.fields(columns):
        name = item.name
        array = getattr(columns, name)
        found[name] = _bits(array) if array.dtype == np.float64 else array.tolist()
    return found


class InclinationTest(unittest.TestCase):
    """RF-005-28: inclinación interna, desde la horizontal y negativa hacia abajo."""

    def test_conventions_are_exact(self) -> None:
        """RF-005-28: negativa hacia abajo, tal cual; positiva hacia abajo, −v; desde la
        vertical (0 = hacia abajo), el decimal de la fuente menos 90, redondeado una vez
        (8,04 → −81,96 y 89,99 → −0,01, que restando en float64 darían −81,96000000000001 y
        −0,010000000000005116). Sin −0,0; NaN sigue ausente; lo que está fuera de
        [−90, 90] sale fuera (lo ve la validación, DH-E08); la entrada no cambia."""
        cases = {
            Inc.NEGATIVE_DOWN: (_floats(-60, -90, 0, 12.5, math.nan, -95),
                                _floats(-60, -90, 0, 12.5, math.nan, -95)),
            Inc.POSITIVE_DOWN: (_floats(60, 75, 90, 0, -5, 95, math.nan),
                                _floats(-60, -75, -90, 0, 5, -95, math.nan)),
            Inc.FROM_VERTICAL: (_floats(30, 15, 0, 90, 180, 8.04, 89.99, 44.99, 0.1, 60.15,
                                        -0.5, math.nan),
                                _floats(-60, -75, -90, 0, 90, -81.96, -0.01, -45.01, -89.9,
                                        -29.85, -90.5, math.nan)),
        }
        for convention, (values, expected) in cases.items():
            with self.subTest(convenio=convention):
                kept = values.copy()
                result = conventions.to_internal_inclination(values, convention)
                self.assertIsNot(result, values)
                self.assertEqual(result.dtype, np.float64)
                self.assertEqual(_bits(result), _bits(expected))
                self.assertEqual(_bits(values), _bits(kept))
        self.assertEqual(float(np.float64(8.04) - 90.0), -81.96000000000001)  # lo que se evita
        negative_zero = conventions.to_internal_inclination(_floats(-0.0), Inc.NEGATIVE_DOWN)
        self.assertEqual(_bits(negative_zero), _bits(_floats(0.0)))
        text = conventions.to_internal_inclination(_floats(60.0), "positive_down")
        self.assertEqual(text.tolist(), [-60.0])

    def test_rejected(self) -> None:
        """RF-005-07, RF-005-02: sin convenio declarado no se convierte (nada se supone); un
        float32 no es un valor de la fuente."""
        with self.assertRaises(ValueError):
            conventions.to_internal_inclination(_floats(60.0), None)
        with self.assertRaises(ValueError):
            conventions.to_internal_inclination(_floats(60.0), "dip")
        with self.assertRaises(TypeError):
            conventions.to_internal_inclination(np.array([60.0], dtype=np.float32),
                                                Inc.POSITIVE_DOWN)


class AzimuthTest(unittest.TestCase):
    """RF-005-27: azimut de cuadrícula en [0, 360)."""

    def test_grid(self) -> None:
        """RF-005-27 y §8 de la spec: de cuadrícula, tal cual, y 360 → 0; 361, −1, NaN o
        infinito no se corrigen (DH-E08 los ve en la base)."""
        values = _floats(0, 45, 359.75, 360, 361, -1, math.nan, math.inf)
        kept = values.copy()
        result = conventions.to_grid_azimuth(values, Ref.GRID, None, None)
        self.assertEqual(_bits(result), _bits(_floats(0, 45, 359.75, 0, 361, -1, math.nan,
                                                      math.inf)))
        self.assertEqual(_bits(values), _bits(kept))

    def test_magnetic_and_true(self) -> None:
        """RF-005-27: magnético, A = (A_m + δ − γ) mod 360; geográfico, (A_m − γ) mod 360,
        con γ por estación: 46,25 + 0,25 − 1,5 = 45; 0,75 + 0,25 − 1,5 = −0,5 → 359,5;
        359 − (−1,5) = 360,5 → 0,5; 1,5 − 1,5 = 0."""
        magnetic = conventions.to_grid_azimuth(_floats(46.25, 0.75, 360), Ref.MAGNETIC, 0.25,
                                               _floats(1.5, 1.5, 1.5))
        self.assertEqual(magnetic.tolist(), [45.0, 359.5, 358.75])
        true = conventions.to_grid_azimuth(_floats(359, 1.5, 200), "true", None,
                                           _floats(-1.5, 1.5, 1.25))
        self.assertEqual(true.tolist(), [0.5, 0.0, 198.75])
        scalar = conventions.to_grid_azimuth(_floats(10, 20), Ref.TRUE, None, 2.0)
        self.assertEqual(scalar.tolist(), [8.0, 18.0])

    def test_never_360(self) -> None:
        """RF-005-27: un resto que redondea a 360 (−10⁻²⁰ mod 360) es 0, y nunca −0,0."""
        result = conventions.to_grid_azimuth(_floats(0.0, 0.0), Ref.TRUE, None,
                                             _floats(1e-20, 0.0))
        self.assertEqual(_bits(result), _bits(_floats(0.0, 0.0)))

    def test_declaration_rules(self) -> None:
        """RF-005-07: la declinación solo con azimut magnético, y es obligatoria con él; la
        convergencia, obligatoria con el magnético y el geográfico, una por estación."""
        values = _floats(10.0, 20.0)
        gamma = _floats(1.0, 1.0)
        bad = [
            (Ref.GRID, 0.5, None),
            (Ref.TRUE, 0.5, gamma),
            (Ref.MAGNETIC, None, gamma),
            (Ref.MAGNETIC, 0.5, None),
            (Ref.TRUE, None, None),
            (Ref.TRUE, None, _floats(1.0, 1.0, 1.0)),
            (Ref.MAGNETIC, 200.0, gamma),
            (None, None, None),
        ]
        for ref, declination, convergence in bad:
            with self.subTest(ref=ref, declinacion=declination):
                with self.assertRaises(ValueError):
                    conventions.to_grid_azimuth(values, ref, declination, convergence)


class ConvergenceTest(unittest.TestCase):
    """RF-005-27: la convergencia de cuadrícula en las bocas, del ``CrsService`` de la 006."""

    def test_fake_service_matches_the_port(self) -> None:
        """El falso de las pruebas cumple ``gis.ports.CrsService`` tal cual: los mismos
        métodos con los mismos parámetros, e ``isinstance``."""
        fake = FakeCrsService()
        self.assertIsInstance(fake, ports.CrsService)
        for name in ("identify_wkt", "transformer", "scale_factor", "grid_convergence"):
            with self.subTest(metodo=name):
                port = inspect.signature(getattr(ports.CrsService, name))
                mine = inspect.signature(getattr(FakeCrsService, name))
                self.assertEqual([(p.name, p.kind) for p in mine.parameters.values()],
                                 [(p.name, p.kind) for p in port.parameters.values()])

    def test_collar_convergence(self) -> None:
        """RF-005-27: ``collar_convergence(xy_abs, service, crs)`` pide al servicio la γ de
        las bocas con X e Y finitas (una sola vez, en float64 (n, 2) y con el CRS dado) y
        deja NaN en las demás (DH-E02); la entrada no cambia."""
        service = FakeCrsService(lambda xy: (xy[:, 0] - 700_000.0) / 100.0)
        xy = np.array([(700_010.5, 4_400_040.5), (math.nan, 4_400_000.0),
                       (700_050.5, 4_400_040.5)])
        kept = xy.copy()
        gamma = conventions.collar_convergence(xy, service, H25830)
        self.assertEqual(gamma.dtype, np.float64)
        self.assertEqual(_bits(gamma), _bits(_floats(0.105, math.nan, 0.505)))
        self.assertEqual(len(service.calls), 1)
        name, crs, sent = service.calls[0]
        self.assertEqual((name, crs), ("grid_convergence", H25830))
        self.assertEqual(sent.tolist(), [[700_010.5, 4_400_040.5], [700_050.5, 4_400_040.5]])
        np.testing.assert_array_equal(xy, kept)

    def test_shapes(self) -> None:
        """Sin bocas, sin llamar al servicio; (n, 2) o error; el servicio da una γ por boca o
        error; el CRS es un ``CrsRef`` del catálogo."""
        service = FakeCrsService()
        empty = conventions.collar_convergence(np.zeros((0, 2)), service, H25830)
        self.assertEqual(empty.shape, (0,))
        self.assertEqual(service.calls, [])
        with self.assertRaises(ValueError):
            conventions.collar_convergence(np.zeros((2, 3)), service, H25830)
        short = FakeCrsService(lambda xy: np.zeros(len(xy) - 1))
        with self.assertRaises(ValueError):
            conventions.collar_convergence(np.zeros((2, 2)), short, H25830)
        with self.assertRaises(TypeError):
            conventions.collar_convergence(np.zeros((2, 2)), service, 25830)
        with self.assertRaises(TypeError):
            conventions.collar_convergence(np.zeros((2, 2), dtype=np.float32), service, H25830)


class SurveysTest(unittest.TestCase):
    """RF-005-27, RF-005-28: las estaciones de una fuente, a los convenios internos."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.basico = _basico().surveys

    def _check_same_stations(self, converted) -> None:
        basico = self.basico
        self.assertEqual(converted.hole_name.tolist(), basico.hole_name.tolist())
        for name in ("depth", "azimuth", "inclination"):
            with self.subTest(columna=name):
                self.assertEqual(_bits(getattr(converted, name)), _bits(getattr(basico, name)))

    def test_positive_dip_and_from_vertical(self) -> None:
        """RF-005-28: las variantes ``positive_dip`` y ``from_vertical`` de
        ``csv_convenios`` dan, bit a bit, las estaciones de ``csv_basico`` (también la de la
        boca de S-12); de cuadrícula, sin δ ni γ, con el azimut medido."""
        for name in ("positive_dip", "from_vertical"):
            with self.subTest(variante=name):
                variant, dset = _variant(name)
                before = _snapshot(dset.surveys)
                declaration = _declaration(variant["azimuth_ref"],
                                           variant["inclination_convention"])
                converted = conventions.convert_surveys(dset.surveys, declaration)
                self._check_same_stations(converted)
                self.assertEqual(_bits(converted.azimuth_measured), _bits(dset.surveys.azimuth))
                grid = _code(converted, "azimuth_ref", Ref.GRID)
                self.assertEqual(set(converted.azimuth_ref.tolist()), {grid})
                self.assertTrue(np.isnan(converted.declination_deg).all())
                self.assertTrue(np.isnan(converted.convergence_deg).all())
                self.assertEqual(_snapshot(dset.surveys), before)

    def test_magnetic(self) -> None:
        """RF-005-27: la variante ``magnetic`` (δ = +0,25°, γ = +1,50° del servicio falso en
        cada boca) da, bit a bit, los azimutes de ``csv_basico`` (S-03: 0,75° → 359,5°) y
        cada estación guarda el azimut medido, «magnetic», δ y γ."""
        variant, dset = _variant("magnetic")
        self.assertEqual((variant["declination_deg"], variant["convergence_deg"]), (0.25, 1.5))
        xy = np.column_stack([dset.collars.x, dset.collars.y])
        gamma = conventions.collar_convergence(xy, FakeCrsService(), H25830)
        declaration = _declaration(variant["azimuth_ref"], variant["inclination_convention"],
                                   model.parse_declination("0,25"))
        converted = conventions.convert_surveys(dset.surveys, declaration, gamma)
        self._check_same_stations(converted)
        self.assertEqual(_bits(converted.azimuth_measured), _bits(dset.surveys.azimuth))
        self.assertIn(0.75, converted.azimuth_measured.tolist())
        magnetic = _code(converted, "azimuth_ref", Ref.MAGNETIC)
        self.assertEqual(set(converted.azimuth_ref.tolist()), {magnetic})
        self.assertEqual(set(converted.declination_deg.tolist()), {0.25})
        self.assertEqual(set(converted.convergence_deg.tolist()), {1.5})

    def test_basico_is_already_internal(self) -> None:
        """RF-005-27, RF-005-28: ``csv_basico`` (cuadrícula, negativa hacia abajo) no
        cambia."""
        declaration = _declaration(Ref.GRID, Inc.NEGATIVE_DOWN)
        self._check_same_stations(conventions.convert_surveys(self.basico, declaration))

    def test_declared_vertical_and_orphans(self) -> None:
        """RF-005-27: una estación de un sondeo declarado vertical ya es interna (0°, −90°,
        de cuadrícula) y no se convierte; una sin boca (DH-E04) no tiene γ: su azimut
        magnético queda NaN y su inclinación se convierte."""
        stations = [
            model.SurveyStation("A", 0.0, 0.0, -90.0, source="declared_vertical"),
            model.SurveyStation("A", 10.0, 100.0, 60.0),
            model.SurveyStation("Z", 10.0, 100.0, 60.0),
        ]
        dset = model.DrillholeSet.from_records(
            crs=H25830, vertical=V5782,
            collars=[model.Collar("A", 700_000.0, 4_400_000.0, 800.0, 50.0)],
            surveys=stations)
        declaration = _declaration(Ref.MAGNETIC, Inc.POSITIVE_DOWN, 0.5)
        converted = conventions.convert_surveys(dset.surveys, declaration, _floats(2.0))
        self.assertEqual(_bits(converted.azimuth), _bits(_floats(0.0, 98.5, math.nan)))
        self.assertEqual(converted.inclination.tolist(), [-90.0, -60.0, -60.0])
        codes = converted.code_values("azimuth_ref")
        self.assertEqual([codes[c] for c in converted.azimuth_ref.tolist()],
                         [Ref.GRID, Ref.MAGNETIC, Ref.MAGNETIC])
        self.assertEqual(_bits(converted.declination_deg), _bits(_floats(math.nan, 0.5, 0.5)))
        self.assertEqual(_bits(converted.convergence_deg),
                         _bits(_floats(math.nan, 2.0, math.nan)))
        self.assertEqual(converted.azimuth_measured.tolist(), [0.0, 100.0, 100.0])

    def test_undeclared(self) -> None:
        """RF-005-07: sin referencia del azimut, sin convenio de inclinación o sin la γ de
        las bocas (magnético o geográfico), no se convierte; una γ por boca."""
        surveys = _basico().surveys
        cases = [
            (_declaration(None, Inc.NEGATIVE_DOWN), None),
            (_declaration(Ref.GRID, None), None),
            (_declaration(Ref.TRUE, Inc.NEGATIVE_DOWN), None),
            (_declaration(Ref.MAGNETIC, Inc.NEGATIVE_DOWN), _floats(*[1.0] * 6)),
            (_declaration(Ref.TRUE, Inc.NEGATIVE_DOWN), _floats(1.0, 1.0)),
        ]
        for declaration, gamma in cases:
            with self.subTest(ref=declaration.azimuth_ref,
                              inclinacion=declaration.inclination_convention):
                with self.assertRaises(ValueError):
                    conventions.convert_surveys(surveys, declaration, gamma)
        empty = model.SurveyColumns.empty()
        self.assertEqual(len(conventions.convert_surveys(empty, _declaration(None, None))), 0)


class UnitsTest(unittest.TestCase):
    """RF-005-29: leyes en g/t, ppm, ppb y % con el factor exacto."""

    def test_same_as_core_units(self) -> None:
        """RF-005-29 (D-18): entre g/t, ppm, ppb y %, ``convert_values`` da, bit a bit, lo
        que ``core.units.convert`` da con cada valor (el factor exacto, un solo redondeo),
        también con 0, −0, subnormales y valores grandes; NaN sigue ausente."""
        rng = random.Random(5004)
        values = [0.0, -0.0, 5e-324, 1.23, 4860.0, 0.35, 1e-7, 123456.789, -5.0, 1e290]
        values += [rng.uniform(0.0, 1e4) * 10.0 ** rng.randint(-6, 3) for _ in range(300)]
        array = np.array(values)
        for source in GRADES:
            for target in GRADES:
                with self.subTest(de=source, a=target):
                    result = conventions.convert_values(array, source, target)
                    expected = [units.convert(v, source, target) for v in values]
                    self.assertEqual(_bits(result), _bits(np.array(expected)))
        nan = conventions.convert_values(_floats(math.nan, 4860.0), "ppb", "g/t")
        self.assertEqual(_bits(nan), _bits(_floats(math.nan, 4.86)))

    def test_exact_factors(self) -> None:
        """RF-005-29: 1 g/t = 1 ppm = 1000 ppb = 10⁻⁴ %: 4860 ppb = 4,86 g/t, 1050 ppm =
        0,105 %, 1 % = 10 000 g/t, 0,35 g/t = 350 ppb; la entrada no cambia."""
        cases = [
            (4860.0, "ppb", "g/t", 4.86),
            (1050.0, "ppm", "%", 0.105),
            (1.0, "%", "g/t", 10_000.0),
            (0.35, "g/t", "ppb", 350.0),
            (2.9, "g/t", "ppm", 2.9),
            (25_000_000.0, "ppb", "%", 2.5),
        ]
        for value, source, target, expected in cases:
            with self.subTest(valor=value, de=source, a=target):
                array = _floats(value)
                self.assertEqual(conventions.convert_values(array, source, target).tolist(),
                                 [expected])
                self.assertEqual(array.tolist(), [value])

    def test_rejected(self) -> None:
        """RF-005-29: una unidad fuera del catálogo o de otra magnitud no se convierte (el
        ``UnitError`` de ``core.units``); un valor que no cabe, tampoco; float32, nunca."""
        for source, target, code in (("text", "g/t", "core.unit_unknown"),
                                     ("oz/t", "g/t", "core.unit_unknown"),
                                     ("%", "m", "core.unit_not_convertible")):
            with self.subTest(de=source, a=target):
                with self.assertRaises(units.UnitError) as caught:
                    conventions.convert_values(_floats(1.0), source, target)
                self.assertEqual(caught.exception.code, code)
        with self.assertRaises(units.UnitError) as caught:
            conventions.convert_values(_floats(1.0, 1e305), "%", "ppb")
        self.assertEqual(caught.exception.code, "core.quantity_not_finite")
        with self.assertRaises(TypeError):
            conventions.convert_values(np.array([1.0], dtype=np.float32), "ppb", "g/t")

    def test_assays_of_csv_convenios(self) -> None:
        """RF-005-29: los análisis de ``csv_convenios`` (Au en ppb, Ag en g/t y Cu en ppm,
        con «<10», «<0.5» y «>10000»), llevados a las unidades de su catálogo (g/t, ppm y %),
        dan bit a bit los valores, las unidades y las marcas de ``csv_basico``, y conservan
        el texto y la unidad originales; la entrada no cambia."""
        source = _assays(CONVENIOS / "assays.csv", ",", ".")
        expected = _assays(BASICO / "analisis_filas.csv", ";", ",")
        catalog = {row[0]: row[2] for row in _read(CONVENIOS / "elements.csv", ",").rows}
        self.assertEqual(catalog, {"Au": "g/t", "Ag": "ppm", "Cu": "%"})
        before = _snapshot(source)
        converted = conventions.convert_assays(source, catalog)
        self.assertEqual(converted.element.tolist(), expected.element.tolist())
        self.assertEqual(_bits(converted.value), _bits(expected.value))
        self.assertEqual(converted.unit.tolist(), expected.unit.tolist())
        self.assertEqual(converted.detection_flag.tolist(), expected.detection_flag.tolist())
        self.assertEqual(converted.reported_value.tolist(), source.reported_value.tolist())
        self.assertEqual(converted.reported_unit.tolist(), source.unit.tolist())
        self.assertIn("<10", converted.reported_value.tolist())
        self.assertIn(">10000", converted.reported_value.tolist())
        self.assertEqual(_snapshot(source), before)

    def test_assays_kept_as_they_are(self) -> None:
        """RF-005-29: no se tocan los valores ya en la unidad del catálogo, los de un
        elemento sin catálogo, los de texto ni los de una unidad que no se puede convertir
        (DH-W07 los avisa); sin texto original, se guarda el decimal del valor convertido
        de la fuente; una unidad original ya puesta se conserva."""
        rows = [
            model.AssayValue("A", 0.0, 1.0, "au", 4860.0, "ppb"),
            model.AssayValue("A", 0.0, 1.0, "Au", 1.5, "g/t", reported_value="1,5"),
            model.AssayValue("A", 0.0, 1.0, "Au", 2.0, "oz/t"),
            model.AssayValue("A", 0.0, 1.0, "Ag", 3.0, "ppm"),
            model.AssayValue("A", 0.0, 1.0, "Ox", None, "text", reported_value="sí"),
            model.AssayValue("A", 0.0, 1.0, "Cu", 1050.0, "ppm", reported_unit="ppm"),
            model.AssayValue("A", 0.0, 1.0, "Cu", None, "ppm"),
        ]
        assays = model.AssayColumns.from_records(rows, model.CollarColumns.empty())
        converted = conventions.convert_assays(assays, {"Au": "g/t", "Cu": "%",
                                                        "Ox": "text"})
        self.assertEqual(_bits(converted.value),
                         _bits(_floats(4.86, 1.5, 2.0, 3.0, math.nan, 0.105, math.nan)))
        self.assertEqual(converted.unit.tolist(),
                         ["g/t", "g/t", "oz/t", "ppm", "text", "%", "%"])
        self.assertEqual(converted.reported_value.tolist(),
                         ["4860", "1,5", None, None, "sí", "1050", None])
        self.assertEqual(converted.reported_unit.tolist(),
                         ["ppb", None, None, None, None, "ppm", "ppm"])
        with self.assertRaises(ValueError):
            conventions.convert_assays(assays, {"Au": "g/t", " au ": "ppm"})


if __name__ == "__main__":
    unittest.main()
