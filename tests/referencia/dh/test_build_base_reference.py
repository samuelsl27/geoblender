# SPDX-License-Identifier: GPL-3.0-or-later
"""Casos de referencia de la base de los sondeos con el servicio de CRS real (spec 005, T41;
RF-005-08, RF-005-27; plan 005 §5.4, §5.6.1 y D-23).

Con el servicio de la 006 (``adapters.registry.crs_service()``: pyproj de ``.deps/site`` y las
rejillas del IGN de ``thirdparty/proj``) y lo importado leído fichero a fichero con el lector
real (``interop.drillholes_tabular.read_role``), en un proyecto EPSG:25830 + EPSG:5782:

- **Reproyección** (RF-005-08): las bocas de ``csv_convenios`` (azimut magnético) con las
  coordenadas de ``csv_basico`` llevadas a ED50 / UTM 30N (EPSG:23030, con la inversa de la
  misma transformación) y declaradas así vuelven a las de ``csv_basico`` dentro de la
  precisión anotada de la transformación («ED50 to ETRS89 (12)», rejilla
  ``es_ign_SPED2ETV2.tif``, 0,2 m) y a ≤ 1 mm de lo que da ``pyproj`` con la misma cadena de
  PROJ (``Transformer.from_pipeline`` con la ``definition`` de la que elige el servicio;
  D-23: sin ``GEOBLENDER_PROJ_BIN``, en lugar de ``cs2cs``, que es la misma PROJ). La base
  dice la transformación, su precisión y su rejilla.
- **Cota elipsoidal** (RF-005-08, D-12): las bocas declaradas en altura elipsoidal ETRS89 (la
  cota de ``csv_basico`` más la ondulación del geoide, ≈ 51 m) llegan a Alicante (EPSG:5782)
  con la rejilla ``es_ign_egm08-rednap.tif`` (0,05 m), a ≤ 1 mm de ``pyproj`` con la misma
  cadena; X e Y no cambian.
- **Azimut de cuadrícula a mano** (RF-005-27): A = (A_m + δ − γ) mod 360 con δ = +0,25° y la
  γ de la serie de Snyder (1987, cap. 8; la de ``test_convenios``) en cada boca ya en ETRS89,
  ≤ 10⁻⁶°; cada estación guarda A_m, «magnetic», δ y γ.
- **Azimut de cuadrícula de unas bocas en otro CRS**: unas desviaciones de cuadrícula de unas
  bocas declaradas en ED50 pasan a la cuadrícula del proyecto con A = A_g + γ_ED50 − γ_ETRS89
  (cada γ con su elipsoide y la posición de la boca en su CRS), ≤ 10⁻⁶°, y guardan la γ neta.
"""

from __future__ import annotations

import dataclasses
import json
import math
import unittest

import numpy as np

from tests.referencia.dh.test_convenios import _snyder_convergence
from tests.support import dh_sets
from tests.support.package import import_geoblender

build = import_geoblender("drillholes.build_base")
model = import_geoblender("drillholes.model")
tabular = import_geoblender("interop.drillholes_tabular")
csv_tables = import_geoblender("interop.csv_tables")
georef = import_geoblender("core.georef")
registry = import_geoblender("adapters.registry")
gis_crs = import_geoblender("gis.crs")

CATALOG = georef.load_catalog()
H25830 = CATALOG.horizontal(25830)
H23030 = CATALOG.horizontal(23030)
V5782 = CATALOG.vertical(5782)
ELLIPSOIDAL = gis_crs.ELLIPSOIDAL_ETRS89
PROJECT_UID = "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"
CONVENIOS = dh_sets.DATA / "csv_convenios"
MM = 1e-3  # RF-005-08: ≤ 1 mm frente a PROJ con la misma transformación
ANGLE_TOLERANCE_DEG = 1e-6  # RF-005-27
DECLINATION = 0.25  # la de csv_convenios/esperado.json

SERVICE = None


def setUpModule() -> None:  # noqa: N802 (nombre de unittest)
    global SERVICE
    SERVICE = registry.crs_service()


def _uid(number: int) -> str:
    return f"{number:08x}-0000-4000-8000-{number:012x}"


def _magnetic(**changes: object) -> object:
    """La declaración de la variante ``magnetic`` de ``csv_convenios`` con ``changes``."""
    expected = json.loads((CONVENIOS / "esperado.json").read_text(encoding="utf-8"))
    common, chosen = expected["declaration"], expected["variants"]["magnetic"]
    values = dict(
        crs=H25830, vertical=V5782, azimuth_ref=chosen["azimuth_ref"],
        declination_deg=chosen["declination_deg"],
        inclination_convention=chosen["inclination_convention"], units={},
        value_rules=model.ValueRules(decimal_mark=common["decimal_mark"]),
        all_vertical=common["all_vertical"], density_kind=common["density_kind"],
        date_format=common["date_format"])
    values.update(changes)
    return model.SourceDeclaration(**values)


def _basico(**changes: object) -> object:
    """La declaración de ``csv_basico/esperado.json`` (azimut de cuadrícula) con ``changes``."""
    found = dh_sets.basico_expected()["declaration"]
    values = dict(
        crs=H25830, vertical=V5782, azimuth_ref=found["azimuth_ref"],
        declination_deg=found["declination_deg"],
        inclination_convention=found["inclination_convention"], units=found["units"],
        value_rules=model.ValueRules(decimal_mark=found["decimal_mark"]),
        all_vertical=found["all_vertical"], density_kind=found["density_kind"],
        date_format=found["date_format"])
    values.update(changes)
    return model.SourceDeclaration(**values)


def _entry(number: int, role: str, table: object, declaration: object) -> object:
    rows = tabular.read_role(role, table, tabular.suggest_mapping(role, table.columns),
                             declaration)
    return build.SourceEntry(_uid(number), declaration, collars=rows.collars,
                             surveys=rows.surveys, label=role)


def _convenios(name: str) -> object:
    return csv_tables.read_table(CONVENIOS / name, encoding="utf-8", separator=",")


def _xyz(collars: object) -> np.ndarray:
    return np.column_stack([collars.x, collars.y, collars.z])


def _moved(entry: object, xyz: np.ndarray) -> object:
    """``entry`` con sus bocas en ``xyz`` (las mismas filas, otras coordenadas)."""
    collars = entry.collars.take(np.arange(len(entry.collars)), x=xyz[:, 0].copy(),
                                 y=xyz[:, 1].copy(), z=xyz[:, 2].copy())
    return dataclasses.replace(entry, collars=collars)


def _pipeline(src: object, src_v: object, dst: object, dst_v: object) -> tuple[object, object]:
    """``pyproj.Transformer`` con la misma cadena de PROJ (``definition``) que la
    transformación que elige el servicio, y su ``TransformInfo``."""
    import pyproj

    transform = SERVICE.transformer(src, src_v, dst, dst_v)
    definition = transform._transformer.definition  # la cadena que usa el adaptador
    return pyproj.Transformer.from_pipeline(definition), transform.info


def _by_name(base: object) -> dict[str, int]:
    return {name: k for k, name in enumerate(base.columns["dh_collar"]["name"].tolist())}


def _azimuth_error(found: float, expected: float) -> float:
    difference = abs(found - expected) % 360.0
    return min(difference, 360.0 - difference)


class Ed50Test(unittest.TestCase):
    """RF-005-08 y RF-005-27 con unas bocas declaradas en ED50 y azimut magnético."""

    @classmethod
    def setUpClass(cls) -> None:
        declared = _magnetic(crs=H23030)
        collars = _entry(1, "collar", _convenios("collars_magnetic.csv"), declared)
        cls.basico = _xyz(collars.collars)  # las cifras de csv_basico (EPSG:25830)
        cls.ed50 = SERVICE.transformer(H25830, V5782, H23030, V5782).apply(cls.basico)
        cls.names = collars.collars.name.tolist()
        surveys = _entry(2, "survey", _convenios("surveys_magnetic.csv"), declared)
        cls.base = build.build_base([_moved(collars, cls.ed50), surveys], SERVICE, H25830,
                                    V5782, project_uid=PROJECT_UID)

    def test_reprojected_collars(self) -> None:
        """RF-005-08: las bocas en ED50 llegan a EPSG:25830 dentro de la precisión de la
        transformación (0,2 m) de las de ``csv_basico`` y a ≤ 1 mm de ``pyproj`` con la misma
        cadena; la base dice la transformación (rejilla del IGN y precisión en m)."""
        pipeline, info = _pipeline(H23030, V5782, H25830, V5782)
        px, py, pz = pipeline.transform(self.ed50[:, 0], self.ed50[:, 1], self.ed50[:, 2])
        expected = np.column_stack([px, py, pz])
        columns, rows = self.base.columns["dh_collar"], _by_name(self.base)
        found = np.array([[columns[axis][rows[name]] for axis in "xyz"] for name in self.names])
        self.assertLessEqual(float(np.abs(found - expected).max()), MM)
        self.assertLessEqual(float(np.abs(found - self.basico).max()), info.accuracy_m)
        self.assertTrue((np.hypot(*(self.ed50 - self.basico)[:, :2].T) > 100.0).all())
        (transform,) = self.base.transforms
        self.assertEqual(transform.input_uid, _uid(1))
        self.assertEqual((transform.source, transform.target),
                         ("EPSG:23030 + EPSG:5782", "EPSG:25830 + EPSG:5782"))
        self.assertEqual(transform.info, info)
        self.assertEqual(transform.info.grids, ("es_ign_SPED2ETV2.tif",))
        self.assertEqual(transform.info.accuracy_m, 0.2)
        self.assertIn("precisión 0,2 m", transform.summary)
        self.assertEqual(transform.holes, len(self.names))

    def test_magnetic_azimuth_by_hand(self) -> None:
        """RF-005-27: cada estación medida (y la orientación en boca de S-12) da
        A = (A_m + 0,25° − γ) mod 360, con la γ de Snyder en su boca ya en ETRS89, a
        ≤ 10⁻⁶°, y guarda A_m, «magnetic», δ y γ (la de Snyder, a ≤ 10⁻⁶°)."""
        collars, surveys = self.base.columns["dh_collar"], self.base.columns["dh_survey"]
        rows = np.flatnonzero(surveys["source"] != "declared_vertical")
        self.assertEqual(len(rows), 30)  # 29 medidas y la orientación en boca de S-12
        worst = 0.0
        for row in rows.tolist():
            hole = int(surveys["hole_id"][row]) - 1
            lon, lat = georef.tm_inverse(float(collars["x"][hole]), float(collars["y"][hole]),
                                         H25830.projection)
            gamma = _snyder_convergence(lon, lat, H25830.projection)
            measured = float(surveys["azimuth_measured"][row])
            expected = (measured + DECLINATION - gamma) % 360.0
            error = _azimuth_error(float(surveys["azimuth"][row]), expected)
            worst = max(worst, error)
            self.assertLessEqual(error, ANGLE_TOLERANCE_DEG)
            self.assertLessEqual(abs(float(surveys["convergence_deg"][row]) - gamma),
                                 ANGLE_TOLERANCE_DEG)
            self.assertEqual(surveys["azimuth_ref"][row], "magnetic")
            self.assertEqual(surveys["declination_deg"][row], DECLINATION)
            self.assertAlmostEqual(gamma, 1.49, delta=0.01)
        self.assertLess(worst, ANGLE_TOLERANCE_DEG)


class EllipsoidalTest(unittest.TestCase):
    def test_ellipsoidal_heights_reach_the_project_datum(self) -> None:
        """RF-005-08 (D-12): unas bocas declaradas en altura elipsoidal ETRS89 llegan a
        Alicante con la rejilla del geoide del IGN (0,05 m): Z a ≤ 1 mm de ``pyproj`` con la
        misma cadena y de la de ``csv_basico`` dentro de esa precisión; X e Y no cambian."""
        declared = _magnetic(vertical=ELLIPSOIDAL)
        collars = _entry(1, "collar", _convenios("collars_magnetic.csv"), declared)
        basico = _xyz(collars.collars)
        heights = SERVICE.transformer(H25830, V5782, H25830, ELLIPSOIDAL).apply(basico)
        undulation = heights[:, 2] - basico[:, 2]
        self.assertTrue(((undulation > 40.0) & (undulation < 60.0)).all(), undulation)
        base = build.build_base([_moved(collars, heights)], SERVICE, H25830, V5782,
                                project_uid=PROJECT_UID)
        pipeline, info = _pipeline(H25830, ELLIPSOIDAL, H25830, V5782)
        px, py, pz = pipeline.transform(heights[:, 0], heights[:, 1], heights[:, 2])
        columns, rows = base.columns["dh_collar"], _by_name(base)
        order = [rows[name] for name in collars.collars.name.tolist()]
        found = np.column_stack([columns[axis][order] for axis in "xyz"])
        self.assertLessEqual(float(np.abs(found - np.column_stack([px, py, pz])).max()), MM)
        self.assertLessEqual(float(np.abs(found[:, 2] - basico[:, 2]).max()), info.accuracy_m)
        self.assertLessEqual(float(np.abs(found[:, :2] - basico[:, :2]).max()), MM)
        (transform,) = base.transforms
        self.assertEqual(transform.info.grids, ("es_ign_egm08-rednap.tif",))
        self.assertEqual(transform.info.accuracy_m, 0.05)
        self.assertEqual(transform.source, "EPSG:25830 + altura elipsoidal ETRS89")


class GridFromAnotherCrsTest(unittest.TestCase):
    def test_grid_azimuth_of_ed50_collars(self) -> None:
        """RF-005-27: las desviaciones de cuadrícula de ``csv_basico`` con sus bocas
        declaradas en ED50 pasan a la cuadrícula del proyecto: A = A_g + γ_ED50 − γ_ETRS89
        (Snyder con el elipsoide Internacional 1924 en la boca en ED50 y con el GRS 1980 en la
        boca ya en ETRS89), ≤ 10⁻⁶°; la referencia sigue «grid» y guarda la γ neta."""
        tables = dh_sets.basico_tables()
        declared = _basico(crs=H23030)
        collars = _entry(1, "collar", tables["collar"], declared)
        ed50 = SERVICE.transformer(H25830, V5782, H23030, V5782).apply(_xyz(collars.collars))
        surveys = _entry(2, "survey", tables["survey"], _basico())
        base = build.build_base([_moved(collars, ed50), surveys], SERVICE, H25830, V5782,
                                project_uid=PROJECT_UID)
        source = {name: xy for name, xy in zip(collars.collars.name.tolist(), ed50[:, :2],
                                               strict=True)}
        columns, stations = base.columns["dh_collar"], base.columns["dh_survey"]
        rows = np.flatnonzero(stations["source"] != "declared_vertical")
        self.assertEqual(len(rows), 30)
        for row in rows.tolist():
            hole = int(stations["hole_id"][row]) - 1
            lon, lat = georef.tm_inverse(float(columns["x"][hole]), float(columns["y"][hole]),
                                         H25830.projection)
            target = _snyder_convergence(lon, lat, H25830.projection)
            x, y = source[columns["name"][hole]]
            lon, lat = georef.tm_inverse(float(x), float(y), H23030.projection)
            origin = _snyder_convergence(lon, lat, H23030.projection)
            measured = float(stations["azimuth_measured"][row])
            expected = (measured + origin - target) % 360.0
            self.assertLessEqual(_azimuth_error(float(stations["azimuth"][row]), expected),
                                 ANGLE_TOLERANCE_DEG)
            self.assertLessEqual(abs(float(stations["convergence_deg"][row])
                                     - (target - origin)), ANGLE_TOLERANCE_DEG)
            self.assertEqual(stations["azimuth_ref"][row], "grid")
            self.assertTrue(math.isnan(stations["declination_deg"][row]))
            self.assertGreater(abs(target - origin), 1e-4)  # ED50 y ETRS89 no dan la misma γ


if __name__ == "__main__":
    unittest.main()
