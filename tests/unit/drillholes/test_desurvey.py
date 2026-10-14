# SPDX-License-Identifier: GPL-3.0-or-later
"""Trazas de los sondeos (spec 005, T06; HU-005-4; RF-005-20; plan 005 §5.4).

- **Prolongación**: si la primera estación está por debajo de la boca, su orientación se
  prolonga hasta la boca (DH-W02, de la boca a la estación), y si la última está por encima
  del fondo, hasta el fondo (DH-W03, de la estación al fondo); la orientación en boca y la
  vertical declarada (una estación en la boca) llegan al fondo sin aviso.
- **Una estación**: un sondeo recto con esa orientación.
- **β ≈ 0**: dos estaciones paralelas o casi no dan divisiones por cero ni avisos de numpy;
  el factor de razón tiende a 1 sin salto en el umbral de su serie y el ángulo de *dogleg*
  es exacto también cuando es diminuto.
- **Contrato**: estaciones desordenadas, varios sondeos, ``holes`` (posiciones o máscara),
  los desplazamientos ``hole_start``, el método registrado (también por su texto), sondeos
  que no se pueden calcular (con su código de la validación) y la entrada sin modificar.
- ``tests/data/dh/csv_basico``: el fondo de cada sondeo, el analítico de ``esperado.json``.

Los casos analíticos (recto por los tres métodos, arco en plano inclinado y tres estaciones a
mano) están en ``tests/referencia/dh/test_desurvey_reference.py``.
"""

from __future__ import annotations

import contextlib
import json
import math
import random
import unittest
import warnings

import numpy as np

from tests.support.package import import_geoblender
from tests.support.repo import ROOT

desurvey = import_geoblender("drillholes.desurvey")
model = import_geoblender("drillholes.model")
georef = import_geoblender("core.georef")
csv_tables = import_geoblender("interop.csv_tables")

CATALOG = georef.load_catalog()
H25830 = CATALOG.horizontal(25830)
V5782 = CATALOG.vertical(5782)
BASICO = ROOT / "tests" / "data" / "dh" / "csv_basico"

Method = desurvey.Method
Warning_ = desurvey.TraceWarning

COLLAR = (701_000.5, 4_401_000.5, 815.375)


def _t(azimuth: float, inclination: float) -> np.ndarray:
    """La dirección unitaria (E, N, Z arriba) de una estación, a mano (plan §5.4)."""
    i, a = math.radians(90.0 + inclination), math.radians(azimuth)
    return np.array([math.sin(i) * math.sin(a), math.sin(i) * math.cos(a), -math.cos(i)])


def _station(hole: str, md: float, azimuth: float, inclination: float,
             source: str = "measured"):
    return model.SurveyStation(hole, md, azimuth, inclination, source=source)


def _dset(collars, stations):
    """Un conjunto con bocas (nombre, profundidad) en :data:`COLLAR` desplazadas 10 m al
    este una de otra (o ``model.Collar``) y las estaciones dadas."""
    records = []
    for k, item in enumerate(collars):
        if isinstance(item, model.Collar):
            records.append(item)
        else:
            name, depth = item
            records.append(model.Collar(name, COLLAR[0] + 10.0 * k, COLLAR[1], COLLAR[2],
                                        depth))
    return model.DrillholeSet.from_records(crs=H25830, vertical=V5782, collars=records,
                                           surveys=stations)


@contextlib.contextmanager
def _no_numpy_warnings():
    """Un contexto en el que un aviso de numpy (división por cero, inválido) es un error."""
    with warnings.catch_warnings(), np.errstate(all="raise"):
        warnings.simplefilter("error")
        yield


class ProlongationTest(unittest.TestCase):
    def test_extends_to_the_collar_and_the_bottom(self) -> None:
        """RF-005-20, DH-W02 y DH-W03: con estaciones a 30 y 120 m en un sondeo de 150 m,
        la orientación de la primera se prolonga hasta la boca y la de la última hasta el
        fondo, por los tres métodos, y la traza lo avisa con su tramo."""
        dset = _dset([("P-1", 150.0)], [_station("P-1", 120.0, 50.0, -58.0),
                                        _station("P-1", 30.0, 45.0, -60.0)])
        for method in Method:
            with self.subTest(method=method):
                traces = desurvey.desurvey(dset, method)
                np.testing.assert_array_equal(traces.md, [0.0, 30.0, 120.0, 150.0])
                self.assertEqual(traces.xyz[0].tolist(), list(COLLAR))
                np.testing.assert_allclose(traces.xyz[1] - traces.xyz[0], 30.0 * _t(45, -60),
                                           rtol=0, atol=1e-9)
                np.testing.assert_allclose(traces.xyz[3] - traces.xyz[2], 30.0 * _t(50, -58),
                                           rtol=0, atol=1e-9)
                np.testing.assert_array_equal(traces.tangent[0], traces.tangent[1])
                np.testing.assert_array_equal(traces.tangent[3], traces.tangent[2])
                np.testing.assert_allclose(traces.tangent[1], _t(45, -60), rtol=0, atol=1e-15)
                self.assertEqual(traces.warnings, (
                    Warning_("DH-W02", 0, "P-1", 0.0, 30.0),
                    Warning_("DH-W03", 0, "P-1", 120.0, 150.0),
                ))

    def test_collar_orientation_and_declared_vertical(self) -> None:
        """RF-005-20 (spec §8): la orientación en boca y la vertical declarada son una
        estación en la boca y dan un sondeo recto hasta el fondo, sin DH-W03; una estación
        medida en la boca, sí lo avisa."""
        dset = _dset([("S-12", 160.0), ("C-01", 4.5), ("M-1", 80.0)], [
            _station("S-12", 0.0, 300.0, -75.0, source="collar"),
            _station("C-01", 0.0, 0.0, -90.0, source="declared_vertical"),
            _station("M-1", 0.0, 10.0, -70.0),
        ])
        traces = desurvey.desurvey(dset)
        np.testing.assert_array_equal(traces.hole_start, [0, 2, 4, 6])
        np.testing.assert_array_equal(traces.md, [0.0, 160.0, 0.0, 4.5, 0.0, 80.0])
        np.testing.assert_allclose(traces.xyz[1] - traces.xyz[0], 160.0 * _t(300, -75),
                                   rtol=0, atol=1e-9)
        self.assertEqual(traces.xyz[3, :2].tolist(), traces.xyz[2, :2].tolist())  # exacta
        self.assertAlmostEqual(traces.xyz[3, 2] - traces.xyz[2, 2], -4.5, delta=1e-12)
        self.assertEqual(traces.warnings, (Warning_("DH-W03", 2, "M-1", 0.0, 80.0),))

    def test_last_station_below_the_bottom(self) -> None:
        """RF-005-20: una estación algo más profunda que el fondo (dentro de la tolerancia
        de la validación) alarga la traza hasta ella, sin prolongar ni avisar."""
        dset = _dset([("P-2", 100.0)], [_station("P-2", 0.0, 0.0, -90.0),
                                        _station("P-2", 100.004, 0.0, -90.0)])
        traces = desurvey.desurvey(dset)
        np.testing.assert_array_equal(traces.md, [0.0, 100.004])
        self.assertEqual(traces.warnings, ())


class SingleStationTest(unittest.TestCase):
    def test_single_station_is_straight(self) -> None:
        """RF-005-20 (spec §8, «una sola estación»): un sondeo recto con esa orientación,
        prolongada hasta la boca y el fondo, por los tres métodos."""
        dset = _dset([("U-1", 100.0)], [_station("U-1", 40.0, 135.0, -45.0)])
        for method in Method:
            with self.subTest(method=method):
                traces = desurvey.desurvey(dset, method)
                np.testing.assert_array_equal(traces.md, [0.0, 40.0, 100.0])
                expected = np.array(COLLAR) + traces.md[:, None] * _t(135, -45)
                np.testing.assert_allclose(traces.xyz, expected, rtol=0, atol=1e-9)
                self.assertEqual([w.code for w in traces.warnings], ["DH-W02", "DH-W03"])


class NearlyParallelTest(unittest.TestCase):
    def test_parallel_and_nearly_parallel_stations(self) -> None:
        """RF-005-20 (β ≈ 0): estaciones paralelas (β = 0) o a 10⁻⁹° no dan avisos de numpy
        ni NaN, y la mínima curvatura coincide con la tangente equilibrada a 10⁻¹² m."""
        for delta in (0.0, 1e-9, 1e-7):
            with self.subTest(delta=delta), _no_numpy_warnings():
                dset = _dset([("B-1", 90.0)], [
                    _station("B-1", 0.0, 77.0, -63.0),
                    _station("B-1", 30.0, 77.0, -63.0 + delta),
                    _station("B-1", 90.0, 77.0 + delta, -63.0 + delta),
                ])
                curvature = desurvey.desurvey(dset)
                balanced = desurvey.desurvey(dset, Method.BALANCED_TANGENT)
                self.assertTrue(np.isfinite(curvature.xyz).all())
                np.testing.assert_allclose(curvature.xyz, balanced.xyz, rtol=0, atol=1e-12)

    def test_ratio_factor_series_and_threshold(self) -> None:
        """RF-005-20: RF(β) = (2/β)·tan(β/2), 1 en β = 0, sin salto en el umbral de la
        serie 1 + β²/12, y con su valor exacto en β = 90°."""
        rf = desurvey.ratio_factor
        with _no_numpy_warnings():
            self.assertEqual(rf(np.array([0.0])).tolist(), [1.0])
            for beta in (1e-6 * (1 - 1e-9), 1e-6, 1e-6 * (1 + 1e-9), 1e-4, 1e-2):
                # tan(h)/h = 1 + h²/3 + 2h⁴/15 + 17h⁶/315 + …, con h = β/2
                exact = 1.0 + beta**2 / 12.0 + beta**4 / 120.0 + 17.0 * beta**6 / 20160.0
                self.assertAlmostEqual(float(rf(np.array([beta]))[0]), exact, delta=4e-16)
            self.assertAlmostEqual(float(rf(np.array([math.pi / 2]))[0]), 4.0 / math.pi,
                                   delta=1e-15)

    def test_dogleg_is_exact_near_zero(self) -> None:
        """RF-005-20: el ángulo entre dos direcciones (β = 2·atan2(|t₂ − t₁|, |t₂ + t₁|))
        es 0 entre direcciones iguales, π/2 entre perpendiculares y exacto a 10⁻⁶ relativo
        con 10⁻⁹ rad, donde el arco coseno da 0."""
        t1 = np.array([[0.0, 0.0, -1.0], [1.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
        tiny = 1e-9
        t2 = np.array([[0.0, 0.0, -1.0], [0.0, 1.0, 0.0],
                       [math.cos(tiny), math.sin(tiny), 0.0]])
        beta = desurvey.dogleg(t1, t2)
        self.assertEqual(beta[0], 0.0)
        self.assertAlmostEqual(beta[1], math.pi / 2, delta=1e-15)
        self.assertAlmostEqual(beta[2] / tiny, 1.0, delta=1e-6)
        self.assertEqual(math.acos(float(np.dot(t1[2], t2[2]))), 0.0)

    def test_direction(self) -> None:
        """RF-005-20 (plan §5.4): t = (sin I·sin A, sin I·cos A, −cos I), I = 90° + θ; la
        vertical hacia abajo es exacta, (0, 0, −1)."""
        result = desurvey.direction(np.array([0.0, 45.0, 300.0]),
                                    np.array([-90.0, -60.0, 10.0]))
        self.assertEqual(result[0].tolist(), [0.0, 0.0, -1.0])
        np.testing.assert_allclose(result[1:], [_t(45, -60), _t(300, 10)], rtol=0,
                                   atol=1e-16)


class ContractTest(unittest.TestCase):
    def _three(self):
        stations = [
            _station("A-1", 0.0, 10.0, -60.0), _station("A-1", 50.0, 12.0, -61.0),
            _station("A-1", 100.0, 15.0, -62.0),
            _station("B-1", 0.0, 200.0, -80.0), _station("B-1", 60.0, 205.0, -78.0),
            _station("C-1", 10.0, 90.0, -45.0),
        ]
        return stations, [("A-1", 100.0), ("B-1", 120.0), ("C-1", 30.0)]

    def test_unsorted_stations_and_offsets(self) -> None:
        """RF-005-20: las estaciones de varios sondeos, en cualquier orden, dan las mismas
        trazas, ordenadas por sondeo y profundidad, con ``hole_start`` de una más que bocas
        y la boca de cada sondeo en su primer punto."""
        stations, collars = self._three()
        reference = desurvey.desurvey(_dset(collars, stations))
        shuffled = list(stations)
        random.Random(5).shuffle(shuffled)
        traces = desurvey.desurvey(_dset(collars, shuffled))
        np.testing.assert_array_equal(traces.hole_start, [0, 3, 6, 9])
        np.testing.assert_array_equal(traces.md,
                                      [0, 50, 100, 0, 60, 120, 0, 10, 30])
        np.testing.assert_array_equal(traces.xyz, reference.xyz)
        np.testing.assert_array_equal(traces.node_hole, [0, 0, 0, 1, 1, 1, 2, 2, 2])
        np.testing.assert_array_equal(traces.computed, [True, True, True])
        for k in range(3):
            np.testing.assert_array_equal(traces.xyz[traces.hole_start[k]],
                                          [COLLAR[0] + 10.0 * k, COLLAR[1], COLLAR[2]])
        self.assertEqual([(w.code, w.name) for w in traces.warnings],
                         [("DH-W03", "B-1"), ("DH-W02", "C-1"), ("DH-W03", "C-1")])

    def test_selected_holes(self) -> None:
        """RF-005-20: ``holes`` (posiciones o máscara) calcula solo esos sondeos; los demás
        tienen un tramo vacío en ``hole_start`` y no se comprueban."""
        stations, collars = self._three()
        stations.append(_station("B-1", 60.0, 999.0, -78.0))  # B-1: DH-E06 y DH-E08
        dset = _dset(collars, stations)
        full = desurvey.desurvey(_dset(*reversed(self._three())))
        for holes in (np.array([2, 0]), np.array([True, False, True])):
            with self.subTest(holes=holes):
                traces = desurvey.desurvey(dset, holes=holes)
                np.testing.assert_array_equal(traces.hole_start, [0, 3, 3, 6])
                np.testing.assert_array_equal(traces.computed, [True, False, True])
                np.testing.assert_array_equal(traces.xyz[:3], full.xyz[:3])
                np.testing.assert_array_equal(traces.xyz[3:], full.xyz[6:])
        with self.assertRaises(ValueError):
            desurvey.desurvey(dset, holes=np.array([0, 0]))
        with self.assertRaises(IndexError):
            desurvey.desurvey(dset, holes=np.array([3]))
        with self.assertRaises(ValueError):
            desurvey.desurvey(dset, holes=np.array([True, False]))

    def test_untraceable_holes_are_refused(self) -> None:
        """RF-005-20, RF-005-17: un sondeo que no se puede calcular (sus errores de alcance
        S, que la validación excluye) no se calcula a medias: ``ValueError`` con su nombre y
        su código."""
        good = [_station("Q-1", 0.0, 0.0, -90.0)]
        cases = {
            "DH-E02": ([model.Collar("Q-1", math.nan, 1.0, 2.0, 50.0)], good),
            "DH-E03": ([("Q-1", 0.0)], good),
            "DH-E05": ([("Q-1", 50.0), ("Q-2", 10.0)], good),
            "DH-E06": ([("Q-1", 50.0)], good + [_station("Q-1", 0.0, 5.0, -80.0)]),
            "DH-E07": ([("Q-1", 50.0)], good + [_station("Q-1", -2.0, 0.0, -90.0)]),
            "DH-E08": ([("Q-1", 50.0)], good + [_station("Q-1", 20.0, 360.0, -90.0)]),
        }
        for code, (collars, stations) in cases.items():
            with self.subTest(code=code):
                with self.assertRaises(ValueError) as caught:
                    desurvey.desurvey(_dset(collars, stations))
                self.assertIn(code, str(caught.exception))
                self.assertIn("Q-2" if code == "DH-E05" else "Q-1", str(caught.exception))
        for bad in ((math.nan, -60.0), (10.0, -90.5), (10.0, math.inf), (-0.5, -60.0)):
            with self.subTest(bad=bad), self.assertRaises(ValueError) as caught:
                desurvey.desurvey(_dset([("Q-1", 50.0)],
                                        good + [_station("Q-1", 25.0, *bad)]))
            self.assertIn("DH-E08", str(caught.exception))
        with self.assertRaises(ValueError) as caught:
            desurvey.desurvey(_dset([("Q-1", math.nan)], good))
        self.assertIn("DH-E03", str(caught.exception))

    def test_stations_without_collar_are_ignored(self) -> None:
        """RF-005-20: una estación de un sondeo sin boca (DH-E04, alcance R) no entra en
        ninguna traza."""
        dset = _dset([("A-1", 30.0)], [_station("A-1", 0.0, 0.0, -90.0),
                                       _station("Z-9", 10.0, 999.0, 5.0)])
        traces = desurvey.desurvey(dset)
        np.testing.assert_array_equal(traces.md, [0.0, 30.0])

    def test_method_by_text_and_empty_set(self) -> None:
        """RF-005-20: el método se registra en la traza y se acepta por su texto; un texto
        que no es un método no se calcula; un conjunto sin bocas da una traza vacía."""
        stations, collars = self._three()
        dset = _dset(collars, stations)
        self.assertIs(desurvey.desurvey(dset, "tangent").method, Method.TANGENT)
        self.assertEqual([m.value for m in Method],
                         ["minimum_curvature", "tangent", "balanced_tangent"])
        with self.assertRaises(ValueError):
            desurvey.desurvey(dset, "spline")
        empty = desurvey.desurvey(model.DrillholeSet(crs=H25830, vertical=V5782))
        np.testing.assert_array_equal(empty.hole_start, [0])
        self.assertEqual(empty.xyz.shape, (0, 3))
        self.assertEqual(empty.tangent.shape, (0, 3))
        self.assertEqual(empty.md.dtype, np.float64)

    def test_input_is_not_modified(self) -> None:
        """RF-005-20: calcular las trazas no cambia el conjunto de sondeos."""
        stations, collars = self._three()
        dset = _dset(collars, stations)
        before = {name: getattr(dset.surveys, name).copy()
                  for name in ("hole", "depth", "azimuth", "inclination", "source")}
        x = dset.collars.x.copy()
        desurvey.desurvey(dset)
        for name, values in before.items():
            np.testing.assert_array_equal(getattr(dset.surveys, name), values)
        np.testing.assert_array_equal(dset.collars.x, x)

    def test_traces_check_their_arrays(self) -> None:
        """RF-005-20: unas trazas con arrays de otra forma o tipo no se crean."""
        traces = desurvey.desurvey(_dset(*reversed(self._three())))
        with self.assertRaises((TypeError, ValueError)):
            desurvey.Traces(hole_start=traces.hole_start, md=traces.md.astype(np.float32),
                            xyz=traces.xyz, tangent=traces.tangent, method=traces.method,
                            warnings=())
        with self.assertRaises((TypeError, ValueError)):
            desurvey.Traces(hole_start=traces.hole_start, md=traces.md, xyz=traces.xyz[:-1],
                            tangent=traces.tangent, method=traces.method, warnings=())


def _basico():
    """Las bocas y desviaciones de ``csv_basico`` (ya en los convenios internos: azimut de
    cuadrícula e inclinación negativa hacia abajo), con la orientación en boca de S-12 y la
    vertical declarada de C-01, como las deja el lector."""
    def number(text: str) -> float:
        return float(text.replace(",", "."))

    def read(name: str):
        return csv_tables.read_table(BASICO / name, encoding="utf-8", separator=";").rows

    collars, stations = [], []
    measured = {row[0] for row in read("desviaciones.csv")}
    for name, x, y, z, depth, azimuth, inclination, *_ in read("bocas.csv"):
        collars.append(model.Collar(name, number(x), number(y), number(z), number(depth)))
        if azimuth:
            stations.append(_station(name, 0.0, number(azimuth), number(inclination),
                                     source="collar"))
        elif name not in measured:
            stations.append(_station(name, 0.0, 0.0, -90.0, source="declared_vertical"))
    for name, depth, azimuth, inclination in read("desviaciones.csv"):
        stations.append(_station(name, number(depth), number(azimuth), number(inclination)))
    return model.DrillholeSet.from_records(crs=H25830, vertical=V5782, collars=collars,
                                           surveys=stations)


class BasicoTest(unittest.TestCase):
    def test_bottoms_of_csv_basico(self) -> None:
        """RF-005-20: por mínima curvatura, el fondo de cada sondeo de ``csv_basico`` es el
        analítico de ``esperado.json`` (a la micra, tolerancia 10⁻⁶ m), sin avisos; los
        rectos y verticales dan el mismo fondo por los tres métodos."""
        expected = json.loads((BASICO / "esperado.json").read_text(encoding="utf-8"))["holes"]
        dset = _basico()
        traces = desurvey.desurvey(dset)
        self.assertEqual(traces.warnings, ())
        names = dset.collars.name.tolist()
        for hole in expected:
            k = names.index(hole["name"])
            end = traces.hole_start[k + 1] - 1
            with self.subTest(hole=hole["name"]):
                self.assertEqual(traces.md[end], hole["depth"])
                np.testing.assert_allclose(traces.xyz[end], hole["bottom"], rtol=0, atol=1e-6)
                if hole["trajectory"] != "arc":
                    for method in (Method.TANGENT, Method.BALANCED_TANGENT):
                        other = desurvey.desurvey(dset, method, holes=np.array([k]))
                        np.testing.assert_allclose(other.xyz[-1], hole["bottom"], rtol=0,
                                                   atol=1e-6)


if __name__ == "__main__":
    unittest.main()
