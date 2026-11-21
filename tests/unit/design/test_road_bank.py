# SPDX-License-Identifier: GPL-3.0-or-later
"""La comparación del banco de las pistas y rampas, con datos sintéticos y sin el banco (spec 017, T36; CE-017-10; RF-017-13, RF-017-15, RF-017-21, RF-017-24; D-22).

``tests/banco/silvestre/test_roads.py`` solo la ejecuta el arnés de los bancos con el banco real (``tools/check.py --banco``). Aquí, en el «verde», se comprueba que se omite sin la
variable (con la orden que la activa) y **sus ayudas** con datos **sintéticos** (ninguno es del proyecto de referencia): las tolerancias de D-22 (longitud y pendientes ±2 %, volúmenes
±10 % y radio mínimo ≥ el de la referencia), la lectura de la verificación CA-6 (las pistas y la cota mínima alcanzable), la elección de la versión más reciente de cada fichero, la
búsqueda de ejes de pista en los GeoPackage del banco y las cifras de una pista de Geoblender (la esquina de CE-017-02: 71,4159 m, 20 m de radio, la pendiente del terreno y el movimiento
de tierras de la sección y del borde juntos) puestas como las del proyecto de referencia, para contrastarlas el día que el banco traiga los ejes.
"""

from __future__ import annotations

import contextlib
import io
import math
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.banco.silvestre import test_roads as bank
from tests.referencia.des import test_ref_roads as h1
from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.unit.design.test_road_operation import COMMON, axis_job, last

provenance = import_geoblender("design.provenance")
road_store = import_geoblender("design.road_store")

TOL = 1e-9
ARC_M = 10.0 * math.pi
"""El arco de la esquina de CE-017-02: R·Δ = 20 · π/2."""
CORNER_LENGTH_M = 40.0 + 40.0 - 2.0 * 20.0 + ARC_M
"""La longitud del eje de la esquina de 40 m + 40 m con R = 20 m: 71,4159 m."""


def verification(**changes: object) -> dict[str, object]:
    """Una verificación CA-6 **sintética** con la forma del banco: dos pistas (con su nombre, sus cotas, su desnivel, sus pendientes y sus anchuras) y la cota mínima alcanzable."""
    found: dict[str, object] = {
        "CA-6": {
            "criterio": "pendiente media máxima y punta",
            "pistas": [
                {"nombre": "Pista de alimentación al Molino de prueba", "long_m": 1000.0, "cota_ini": 100.0, "cota_fin": 170.0, "desnivel_m": 70.0, "pend_media_pct": 7.0,
                 "pend_max_pct": 10.0, "calzada_m": 10.5, "plataforma_m": 11.5},
                {"nombre": "Acceso al TALLER de prueba", "long_m": 700.0, "cota_ini": 100.0, "cota_fin": 156.0, "desnivel_m": 56.0, "pend_media_pct": 8.0,
                 "pend_max_pct": 10.0, "calzada_m": 10.5, "plataforma_m": 11.5}],
            "referencia": "superficie excavada",
            "cota_min_alcanzable_sup_restaurada": 136.52340698242188,
            "ok": True}}
    found.update(changes)
    return found


def road_values(**changes: float | None) -> dict[str, float | None]:
    """Las veintitrés cifras de una pista con un valor cualquiera (uno cada una; el número de curvas, entero), con ``changes``."""
    values: dict[str, float | None] = {figure.key: 1.0 for figure in provenance.ROAD_FIGURES}
    values["des.road_curves"] = 1
    values.update(changes)
    return values


def with_pistas(*roads: dict[str, object]) -> dict[str, object]:
    """Una verificación con las pistas ``roads``."""
    found = verification()
    found["CA-6"] = {**found["CA-6"], "pistas": list(roads)}  # type: ignore[dict-item]
    return found


class SkippedTest(unittest.TestCase):
    """CE-017-10: sin ``GEOBLENDER_SILVESTRE_DIR`` la comparación se omite con la orden que la activa."""

    def test_it_is_skipped_without_the_variable_and_says_how_to_run_it(self) -> None:
        """CE-017-10: sin la variable, ninguna prueba se ejecuta y la omisión dice ``OMITIDO: silvestre`` y ``tools/check.py --banco``."""
        environ = {key: value for key, value in os.environ.items() if key != bank.bank.ENV}
        suite = unittest.TestLoader().loadTestsFromTestCase(bank.RoadsBankTest)
        result = unittest.TestResult()
        with mock.patch.dict(os.environ, environ, clear=True), contextlib.redirect_stderr(io.StringIO()):
            suite.run(result)
        self.assertTrue(result.wasSuccessful())
        self.assertEqual(result.testsRun, 0)
        ((_, reason),) = result.skipped
        self.assertIn("OMITIDO: silvestre", reason)
        self.assertIn("tools/check.py --banco", reason)


class ToleranceTest(unittest.TestCase):
    """D-22: lo que queda fuera de la tolerancia del banco (RF-017-13, RF-017-15, RF-017-21, RF-017-24)."""

    WANTED = bank.RoadFigures(1_000.0, 7.0, 10.0, 12.1, 5_000.0, 9_000.0)

    def found(self, **changes: float | None) -> object:
        return bank.RoadFigures(**{**{"length_m": 1_000.0, "mean_pct": 7.0, "max_pct": 10.0, "min_radius_m": 12.1, "cut_m3": 5_000.0, "fill_m3": 9_000.0}, **changes})

    def test_the_tolerances_are_the_ones_of_d_22(self) -> None:
        """D-22 (CE-017-10): la longitud y las pendientes, ±2 %; los volúmenes, ±10 %; el radio mínimo, no menor que el de la referencia."""
        self.assertEqual((bank.LENGTH_TOLERANCE, bank.SLOPE_TOLERANCE, bank.VOLUME_TOLERANCE), (0.02, 0.02, 0.10))
        self.assertAlmostEqual(bank.relative(103.0, 100.0), 0.03, places=12)
        self.assertAlmostEqual(bank.relative(97.0, 100.0), -0.03, places=12)

    def test_the_figures_of_the_reference_itself_are_inside(self) -> None:
        """RF-017-13, RF-017-15, RF-017-21: una pista con las cifras de la referencia no tiene nada fuera de la tolerancia."""
        self.assertEqual(bank.outside(self.found(), self.WANTED), [])

    def test_the_length_and_the_slopes_are_compared_at_2_percent(self) -> None:
        """RF-017-13, RF-017-15: la longitud y las pendientes media y máxima se comparan por separado, a ±2 % **relativo** de la referencia; más allá, el nombre de la cifra que falla."""
        self.assertEqual(bank.outside(self.found(length_m=1_019.9, mean_pct=7.13, max_pct=10.19), self.WANTED), [])
        self.assertEqual(bank.outside(self.found(length_m=980.1), self.WANTED), [])
        self.assertEqual(bank.outside(self.found(length_m=1_020.1), self.WANTED), ["longitud"])
        self.assertEqual(bank.outside(self.found(length_m=979.9), self.WANTED), ["longitud"])
        self.assertEqual(bank.outside(self.found(mean_pct=7.15), self.WANTED), ["pendiente media"])
        self.assertEqual(bank.outside(self.found(max_pct=9.79), self.WANTED), ["pendiente máxima"])
        self.assertEqual(bank.outside(self.found(length_m=2_000.0, mean_pct=1.0, max_pct=1.0), self.WANTED), ["longitud", "pendiente media", "pendiente máxima"])

    def test_the_volumes_are_compared_at_10_percent_and_only_if_the_reference_has_them(self) -> None:
        """RF-017-21: el desmonte y el terraplén, a ±10 % de la referencia; una referencia sin volúmenes (las pistas del molino y del taller) no los compara; una pista que no los da, cuando la
        referencia sí, queda fuera."""
        self.assertEqual(bank.outside(self.found(cut_m3=5_499.0, fill_m3=8_101.0), self.WANTED), [])
        self.assertEqual(bank.outside(self.found(cut_m3=5_501.0), self.WANTED), ["desmonte"])
        self.assertEqual(bank.outside(self.found(fill_m3=8_099.0), self.WANTED), ["terraplén"])
        self.assertEqual(bank.outside(self.found(cut_m3=None, fill_m3=None), self.WANTED), ["desmonte", "terraplén"])
        without = bank.RoadFigures(1_000.0, 7.0, 10.0)
        self.assertEqual(bank.outside(self.found(cut_m3=1.0e9, fill_m3=0.0, min_radius_m=1.0), without), [])

    def test_the_minimum_radius_must_not_be_below_the_reference(self) -> None:
        """RF-017-13 (D-22): el radio mínimo ha de ser **mayor o igual** que el de la referencia (12,1 m: una *spline* frente a curvas circulares); una pista sin curvas (sin radio) no tiene
        ninguna más cerrada y cumple."""
        self.assertEqual(bank.outside(self.found(min_radius_m=12.1), self.WANTED), [])
        self.assertEqual(bank.outside(self.found(min_radius_m=40.0), self.WANTED), [])
        self.assertEqual(bank.outside(self.found(min_radius_m=12.09), self.WANTED), ["radio mínimo"])
        self.assertEqual(bank.outside(self.found(min_radius_m=None), self.WANTED), [])

    def test_a_reference_without_a_length_cannot_be_compared(self) -> None:
        """La referencia ha de tener una longitud y unas pendientes positivas: con cero no hay diferencia relativa (``ValueError``)."""
        with self.assertRaises(ValueError):
            bank.relative(1.0, 0.0)
        with self.assertRaises(ValueError):
            bank.outside(self.found(), bank.RoadFigures(0.0, 7.0, 10.0))


class ReferenceTest(unittest.TestCase):
    """La lectura de la verificación CA-6 del banco: las pistas del molino y del taller y la cota mínima alcanzable (CE-017-10, RF-017-15, RF-017-24)."""

    def test_the_two_roads_are_read_by_their_names(self) -> None:
        """CE-017-10: la pista del molino y la del taller, buscadas por su nombre (sin importar mayúsculas ni el resto del nombre), con su longitud, sus cotas, su desnivel, sus pendientes y las
        anchuras de su calzada y de su plataforma; ``figures`` da las de la comparación (longitud y pendientes)."""
        mill, workshop = bank.reference_roads(verification())
        self.assertEqual((mill.length_m, mill.z_start_m, mill.z_end_m, mill.drop_m, mill.mean_pct, mill.max_pct, mill.carriageway_m, mill.platform_m),
                         (1_000.0, 100.0, 170.0, 70.0, 7.0, 10.0, 10.5, 11.5))
        self.assertEqual((workshop.length_m, workshop.drop_m, workshop.mean_pct), (700.0, 56.0, 8.0))
        self.assertEqual(mill.figures, bank.RoadFigures(1_000.0, 7.0, 10.0))
        self.assertEqual(workshop.figures, bank.RoadFigures(700.0, 8.0, 10.0))

    def test_the_minimum_reachable_level_is_read(self) -> None:
        """RF-017-24: la cota mínima alcanzable sobre la superficie restaurada, tal como la da la verificación (float64 del JSON)."""
        self.assertEqual(bank.reference_level(verification()), 136.52340698242188)

    def test_what_the_bank_lacks_is_said(self) -> None:
        """Lo que la verificación no trae se dice con su motivo (``BankShapeError``): sin CA-6, sin pistas, sin la del taller, una cifra que falta o que no es un número, y sin la cota mínima."""
        with self.assertRaisesRegex(bank.BankShapeError, "CA-6"):
            bank.reference_roads({})
        with self.assertRaisesRegex(bank.BankShapeError, "pistas"):
            bank.reference_roads({"CA-6": {"referencia": "x"}})
        mill = verification()["CA-6"]["pistas"][0]  # type: ignore[index]
        with self.assertRaisesRegex(bank.BankShapeError, "taller"):
            bank.reference_roads(with_pistas(mill))
        for key in ("long_m", "pend_media_pct", "calzada_m"):
            with self.subTest(clave=key):
                broken = {name: value for name, value in mill.items() if name != key}
                with self.assertRaisesRegex(bank.BankShapeError, key):
                    bank.reference_roads(with_pistas(broken, verification()["CA-6"]["pistas"][1]))  # type: ignore[index]
        with self.assertRaisesRegex(bank.BankShapeError, "long_m"):
            bank.reference_roads(with_pistas({**mill, "long_m": "mil"}, verification()["CA-6"]["pistas"][1]))  # type: ignore[index]
        with self.assertRaisesRegex(bank.BankShapeError, "cota mínima"):
            bank.reference_level({"CA-6": {"pistas": []}})
        with self.assertRaisesRegex(bank.BankShapeError, "cota mínima"):
            bank.reference_level({"CA-6": {"cota_min_alcanzable_sup_restaurada": None}})

    def test_the_widths_of_the_reference_profile_are_the_ones_of_the_roads(self) -> None:
        """RF-017-21: la calzada y la plataforma que declara la referencia (10,5 y 11,5 m) son las que derivan del perfil de referencia de las pruebas (vehículo de 3,5 m, factor 3, caballón de
        1 m) con ``road_profiles.derived``, a ≤ 10⁻⁹ m; con otro perfil, no."""
        mill, _workshop = bank.reference_roads(verification())
        carriageway, section = bank.widths_of(rd.road_profile(rd.PROFILE))
        self.assertAlmostEqual(carriageway, mill.carriageway_m, delta=TOL)
        self.assertAlmostEqual(section, mill.platform_m, delta=TOL)
        wide = bank.widths_of(rd.road_profile(rd.profile_with(vehicle_width_m=4.0)))
        self.assertNotAlmostEqual(wide[0], mill.carriageway_m, delta=0.1)


class LatestTest(unittest.TestCase):
    """La elección de la versión más reciente de un fichero del banco (``V<nn>_…``)."""

    def test_the_highest_version_is_taken_and_the_copies_count_as_one(self) -> None:
        """Entre ``V9_…`` y ``V10_…`` (el 10 es mayor que el 9, no por orden alfabético) se toma la de número mayor; dos copias iguales de ella cuentan como una y dos distintas, no."""
        with tempfile.TemporaryDirectory(prefix="gb-rb-") as folder:
            root = Path(folder)
            for name, text in (("V9_verificacion.json", "9"), ("V10_verificacion.json", "10"), ("otro.json", "x"), ("V11_otra_cosa.json", "11")):
                (root / name).write_text(text, encoding="utf-8")
            (root / "copia").mkdir()
            (root / "copia" / "V10_verificacion.json").write_text("10", encoding="utf-8")
            found = bank.latest(bank.bank.files(root), bank.VERIFICATION_PATTERN, "la verificación de la V10")
            self.assertEqual(found.read_text(encoding="utf-8"), "10")
            (root / "copia" / "V10_verificacion.json").write_text("diferente", encoding="utf-8")
            with self.assertRaisesRegex(bank.BankShapeError, "la verificación de la V10"):
                bank.latest(bank.bank.files(root), bank.VERIFICATION_PATTERN, "la verificación de la V10")
            with self.assertRaisesRegex(bank.BankShapeError, "ninguna"):
                bank.latest(bank.bank.files(root), bank.FINAL_PATTERN, "la superficie restaurada")

    def test_the_suffix_and_the_pattern_of_each_file(self) -> None:
        """Los patrones (del nombre entero, con su extensión): la verificación es un ``.json`` y las superficies, un GeoTIFF, de ``V<nn>_Superficie_final`` y ``V<nn>_Superficie_excavacion``
        (la explotación), sin confundir una con otra ni con otra extensión."""
        self.assertTrue(bank.VERIFICATION_PATTERN.match("V10_verificacion.json"))
        self.assertTrue(bank.FINAL_PATTERN.match("V10_Superficie_final.tif"))
        self.assertTrue(bank.FINAL_PATTERN.match("v9_superficie_final.TIFF"))
        self.assertTrue(bank.EXPLOITATION_PATTERN.match("V10_Superficie_excavacion.tif"))
        self.assertFalse(bank.FINAL_PATTERN.match("V10_Superficie_excavacion.tif"))
        self.assertFalse(bank.EXPLOITATION_PATTERN.match("V10_Superficie_in_situ.tif"))
        self.assertFalse(bank.VERIFICATION_PATTERN.match("V10_verificacion_antigua.json"))
        self.assertFalse(bank.VERIFICATION_PATTERN.match("V10_verificacion.txt"))
        self.assertFalse(bank.FINAL_PATTERN.match("V10_Superficie_final.npy"))


class AxesTest(unittest.TestCase):
    """La búsqueda de ejes de pista en los GeoPackage del banco: lo que decide si CE-017-10 se puede ejecutar o sigue sin los datos originales."""

    @staticmethod
    def geopackage(path: Path, layer: str, column: str, values: tuple[str, ...]) -> None:
        connection = sqlite3.connect(path)
        try:
            connection.execute("PRAGMA synchronous = OFF")  # un fichero de prueba: sin esperar al disco (el «verde» tiene un margen de décimas de segundo)
            connection.execute("PRAGMA journal_mode = OFF")
            connection.execute("CREATE TABLE gpkg_contents (table_name TEXT, data_type TEXT, srs_id INTEGER)")
            connection.execute("INSERT INTO gpkg_contents VALUES (?, 'features', 25830)", (layer,))
            connection.execute(f'CREATE TABLE "{layer}" (fid INTEGER PRIMARY KEY, geom BLOB, "{column}" TEXT)')
            connection.executemany(f'INSERT INTO "{layer}" (geom, "{column}") VALUES (NULL, ?)', [(value,) for value in values])
            connection.commit()
        finally:
            connection.close()

    def test_a_bank_without_roads_has_no_axes(self) -> None:
        """CE-017-10: un banco con marcas de diseño (talud, zonas, barrancos) y unos límites no trae ningún eje de pista: la comparación sigue sin los datos originales."""
        with tempfile.TemporaryDirectory(prefix="gb-rb-") as folder:
            root = Path(folder)
            self.geopackage(root / "croquis.gpkg", "marcas", "capa", ("talud_restauracion", "zona_roja_minimo", "barranco_no_suavizar"))
            self.geopackage(root / "limites.gpkg", "Limites_v1", "nombre", ("Limite general",))
            (root / "nota.txt").write_text("pista A15", encoding="utf-8")  # un fichero que no es un GeoPackage no cuenta
            self.assertEqual(bank.axis_candidates(bank.bank.files(root)), 0)

    def test_a_layer_or_a_value_that_names_a_road_is_found(self) -> None:
        """CE-017-10: el nombre de una capa o un valor de su campo de nombre (``capa``, ``nombre`` o ``name``) con «pista», «A15», «molino» o «taller» (sin mayúsculas) es un candidato: cuenta cada uno."""
        with tempfile.TemporaryDirectory(prefix="gb-rb-") as folder:
            root = Path(folder)
            self.geopackage(root / "a.gpkg", "marcas", "capa", ("talud", "Pista_A15", "eje_taller"))
            self.geopackage(root / "b.gpkg", "Pistas_V10", "otro", ("sin nombre",))
            self.geopackage(root / "c.gpkg", "zonas", "nombre", ("Acceso al molino",))
            self.assertEqual(bank.axis_candidates(bank.bank.files(root)), 4)

    def test_a_broken_file_is_not_an_axis_and_the_bank_is_not_written(self) -> None:
        """Un ``.gpkg`` que no es una base de datos no es candidato (no rompe la búsqueda) y la búsqueda no escribe nada en el banco (sin ``-wal`` ni ``-journal``; las fechas, iguales)."""
        with tempfile.TemporaryDirectory(prefix="gb-rb-") as folder:
            root = Path(folder)
            (root / "roto.gpkg").write_bytes(b"esto no es sqlite")
            self.geopackage(root / "bueno.gpkg", "marcas", "capa", ("pista",))
            before = {path.name: path.stat().st_mtime_ns for path in root.iterdir()}
            self.assertEqual(bank.axis_candidates(bank.bank.files(root)), 1)
            self.assertEqual({path.name: path.stat().st_mtime_ns for path in root.iterdir()}, before)


class FiguresTest(unittest.TestCase):
    """Las cifras de una pista de Geoblender puestas como las del proyecto de referencia (RF-017-13, RF-017-15, RF-017-21, RF-017-23)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.outcome = last(road_store.road_compute_steps(axis_job(rd.CORNER_LONG, profile=h1.SHORT), COMMON))

    def test_the_corner_of_ce_017_02_gives_its_figures_in_the_form_of_the_reference(self) -> None:
        """RF-017-13, RF-017-15, RF-017-21: la pista «sobre un eje» de la esquina de 40 m + 40 m con R = 20 m sobre el plano del 4 % da, como ``RoadFigures``: la longitud de 71,4159 m, el radio
        mínimo de 20 m, la pendiente máxima del 4 % (la del terreno: pd = 10 % no actúa), la media del cálculo a mano (el terreno sube 1,6 m en los 40 m que avanza hacia el este, sobre
        71,4159 m) y el desmonte y el terraplén de la **sección y del borde juntos**."""
        found = bank.figures_of(self.outcome.figures)
        self.assertAlmostEqual(found.length_m, CORNER_LENGTH_M, delta=TOL)
        self.assertAlmostEqual(found.min_radius_m, 20.0, delta=TOL)
        self.assertAlmostEqual(found.max_pct, 4.0, delta=1e-6)
        self.assertAlmostEqual(found.mean_pct, 160.0 / CORNER_LENGTH_M, delta=1e-6)
        by_key = {figure.key: figure.value for figure in self.outcome.figures}
        self.assertAlmostEqual(found.cut_m3, by_key["des.road_cut_m3"] + by_key["des.road_edge_cut_m3"], delta=TOL)
        self.assertAlmostEqual(found.fill_m3, by_key["des.road_fill_m3"] + by_key["des.road_edge_fill_m3"], delta=TOL)
        self.assertGreater(found.cut_m3, 1.0)
        self.assertGreater(found.fill_m3, 1.0)

    def test_the_same_figures_are_inside_and_other_ones_are_not(self) -> None:
        """CE-017-10: contra sí misma, la pista no tiene nada fuera de la tolerancia; contra una referencia con otra longitud, otra pendiente media y menos radio, sí (con sus nombres)."""
        found = bank.figures_of(self.outcome.figures)
        self.assertEqual(bank.outside(found, found), [])
        other = bank.RoadFigures(found.length_m * 1.05, found.mean_pct * 0.9, found.max_pct, found.min_radius_m * 2.0, found.cut_m3 * 1.05, found.fill_m3 * 0.8)
        self.assertEqual(bank.outside(found, other), ["longitud", "pendiente media", "radio mínimo", "terraplén"])

    def test_a_road_without_curves_has_no_radius(self) -> None:
        """RF-017-13: sin curvas no existe el radio mínimo (``des.road_radius_min_m`` no está): ``min_radius_m`` es ``None``; sin las cifras del grabado, tampoco hay volúmenes."""
        values = road_values(**{"des.road_radius_min_m": None})
        found = bank.figures_of(provenance.road_figures("Pista recta", "RDW-001", values))
        self.assertIsNone(found.min_radius_m)
        self.assertEqual((found.length_m, found.mean_pct, found.max_pct), (1.0, 1.0, 1.0))
        self.assertEqual((found.cut_m3, found.fill_m3), (2.0, 2.0))

    def test_the_figures_of_another_operation_are_rejected(self) -> None:
        """Sin la longitud o las pendientes la pista no se puede comparar: ``KeyError`` con la cifra que falta (las de «Proponer el trazado…» no traen pendiente media, por ejemplo)."""
        proposal = provenance.propose_figures("Trazado", {"des.road_length_m": 100.0, "des.road_gradient_max_pct": 5.0})
        with self.assertRaisesRegex(KeyError, "des.road_gradient_mean_pct"):
            bank.figures_of(proposal)


if __name__ == "__main__":
    unittest.main()
