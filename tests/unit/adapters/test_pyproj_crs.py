# SPDX-License-Identifier: GPL-3.0-or-later
"""Adaptador de CRS con pyproj (spec 006, T11; plan 006 §5.3.3; ADR-0005, ADR-0019).

Con la rueda fijada de pyproj (``.deps/site/``) y las rejillas del IGN de
``geoblender/thirdparty/proj/``:

- **RF-006-04** y **RF-006-05** (sin depender del PROJ del equipo ni de la red): con
  ``PROJ_LIB`` y ``PROJ_DATA`` apuntando a una carpeta con un ``proj.db`` falso, una rejilla
  ``es_ign_SPED2ETV2.tif`` falsa y un ``proj.ini`` con la red activada (y ``PROJ_NETWORK=ON``),
  en un proceso nuevo, EPSG:25830 se resuelve igual que el catálogo de la 002 (el mismo WKT2),
  un ``.prj`` se identifica, la red de pyproj está desactivada y ED50 → ETRS89 da, bit a bit,
  lo mismo que aquí con la rejilla de ``thirdparty/proj/``.
- **RF-006-05** (transformación de precisión conocida, con su rejilla): ED50 → ETRS89 cita
  ``es_ign_SPED2ETV2.tif`` con 0,2 m y reproduce a ≤ 0,2 m el vértice REGENTE 55901 «IGNE»
  de su reseña pública del IGN (3-oct-2026); la altura elipsoidal ETRS89 → Alicante,
  ``es_ign_egm08-rednap.tif`` con 0,05 m (y la de Canarias, la suya); una transformación sin
  precisión conocida (Alicante → Mallorca, solo «ballpark») da ``accuracy_m = None``, igual
  que dos referencias locales distintas.
- **RF-006-07** (factor de escala y convergencia en el destino): +1,93° ± 0,01° en (0° E;
  40° N) y −1,93° en (6° O; 40° N) en EPSG:25830 (inv. 08 §3.3), iguales a los de la
  transversa de Mercator propia de ``core.georef`` (sin pyproj).
- **RF-006-31** (versión de pyproj): con otra versión simulada, o sin pyproj, el servicio
  no se crea y dice la hallada y la esperada; la fijada es la de ``tools/wheels.toml``.
- R10 del plan: si el catálogo de la 002 y el ``proj.db`` difieren, ``gis.crs_catalog_mismatch``.
- ADR-0019: ``thirdparty/proj/`` tiene las tres rejillas con el sha256 de su ``README.md``.
"""

import dataclasses
import hashlib
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from tests.support.package import import_geoblender
from tests.support.repo import EXTENSION_DIR, ROOT

pyproj_crs = import_geoblender("adapters.pyproj_crs")
registry = import_geoblender("adapters.registry")
ports = import_geoblender("gis.ports")
crs = import_geoblender("gis.crs")
georef = import_geoblender("core.georef")

CATALOG = georef.load_catalog()
H25830 = CATALOG.horizontal(25830)
H25831 = CATALOG.horizontal(25831)
H23030 = CATALOG.horizontal(23030)
H4083 = CATALOG.horizontal(4083)
V5782 = CATALOG.vertical(5782)
V9392 = CATALOG.vertical(9392)
V9397 = CATALOG.vertical(9397)
ELLIPSOIDAL = crs.ELLIPSOIDAL_ETRS89

GRIDS_DIR = EXTENSION_DIR / "thirdparty" / "proj"
GRIDS = ("es_ign_SPED2ETV2.tif", "es_ign_egm08-rednap.tif", "es_ign_egm08-rednap-canarias.tif")
WHEELS_TOML = ROOT / "tools" / "wheels.toml"
LICENSES_DIR = ROOT / "LICENSES"

# Un punto en ED50 / UTM 30N (zona de Madrid) para comparar procesos.
ED50_POINT = (440000.0, 4474000.0, 100.0)

# Vértice 55901 «IGNE» (Madrid) de la red REGENTE, huso 30, según su reseña pública del IGN
# (Instituto Geográfico Nacional) de fecha 3-oct-2026, consultada el 08/10/2026:
# https://datos-geodesia.ign.es/Red_Geodesica/Hoja0559/055901.pdf (observado con GPS; «No
# pertenece al bloque de compensación»). Coordenadas UTM en metros; la altitud es la de la
# base del pilar sobre el nivel medio del mar (no cambia: Alicante en los dos lados).
REGENTE_ED50 = (439940.19, 4477691.67, 714.611)
REGENTE_ETRS89 = (439830.795, 4477484.219)
REGENTE_SCALE_ETRS89 = 0.999644563  # publicado con 9 decimales
REGENTE_CONVERGENCE_ETRS89 = -(27 / 60 + 37 / 3600)  # −0° 27' 37'', publicado al segundo
REGENTE_TOLERANCE_M = 0.2  # la precisión de ED50 → ETRS89 con es_ign_SPED2ETV2 (RF-006-05)

SERVICE = None


def setUpModule() -> None:  # noqa: N802 (nombre de unittest)
    global SERVICE
    SERVICE = pyproj_crs.load_service()


def _service():
    assert SERVICE is not None
    return SERVICE


def _edge_points(lon: float, lat: float = 40.0) -> tuple[float, float]:
    """(x, y) en EPSG:25830 de (``lon``, ``lat``) con la transversa de Mercator de
    ``core.georef`` (sin pyproj): (0° E; 40° N) → (756 099,6; 4 432 069,1)."""
    return georef.tm_forward(lon, lat, H25830.projection)


def _convergence_deg(lon: float, lat: float) -> float:
    """Convergencia de cuadrícula sin pyproj: el ángulo horario del norte geográfico al de
    cuadrícula, con el meridiano que pasa por el punto proyectado con ``core.georef``."""
    delta = 1e-5
    x0, y0 = georef.tm_forward(lon, lat - delta, H25830.projection)
    x1, y1 = georef.tm_forward(lon, lat + delta, H25830.projection)
    return -math.degrees(math.atan2(x1 - x0, y1 - y0))


CHILD = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
import numpy as np
from tests.support.package import import_geoblender
pyproj_crs = import_geoblender("adapters.pyproj_crs")
georef = import_geoblender("core.georef")
catalog = georef.load_catalog()
service = pyproj_crs.load_service()
h30, ed50, v = catalog.horizontal(25830), catalog.horizontal(23030), catalog.vertical(5782)
prj = open(sys.argv[2], encoding="utf-8").read()
found = service.identify_wkt(prj)
transform = service.transformer(ed50, v, h30, v)
point = transform.apply(np.array([[float(a) for a in sys.argv[3:6]]]))
print(json.dumps({
    "wkt2_25830": service.wkt2(25830),
    "identified": None if found is None else found.epsg,
    "network": service.network_enabled(),
    "data_dirs": [str(p) for p in service.data_dirs()],
    "description": transform.info.description,
    "accuracy": transform.info.accuracy_m,
    "grids": list(transform.info.grids),
    "point": [repr(float(value)) for value in point[0]],
}))
"""


class IsolationTest(unittest.TestCase):
    """RF-006-04, RF-006-05 (TOP-05 de Silvestre): ni ``PROJ_LIB``/``PROJ_DATA`` ni la red."""

    def test_fake_proj_db_in_a_new_process(self) -> None:
        """RF-006-04 / RF-006-05: en un proceso nuevo con ``PROJ_LIB``, ``PROJ_DATA`` y
        ``PROJ_NETWORK`` del equipo apuntando a datos falsos, todo sale de la rueda y de
        ``thirdparty/proj/``: el mismo WKT2 que el catálogo, la misma identificación del
        ``.prj`` y el mismo resultado bit a bit que en este proceso, sin red."""
        site = Path(importlib.util.find_spec("pyproj").origin).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="gb-proj-falso-") as folder:
            fake = Path(folder)
            (fake / "proj.db").write_bytes(b"esto no es una base de datos de PROJ\n" * 64)
            (fake / "es_ign_SPED2ETV2.tif").write_bytes(b"II*\x00" + b"\x00" * 252)
            (fake / "proj.ini").write_text("[general]\nnetwork = on\n", encoding="utf-8")
            env = dict(os.environ)
            env.update(
                PROJ_LIB=str(fake),
                PROJ_DATA=str(fake),
                PROJ_NETWORK="ON",
                PYTHONPATH=os.pathsep.join([str(ROOT), str(site)]),
            )
            prj = ROOT / "tests" / "data" / "gis" / "asc" / "corner.prj"
            done = subprocess.run(
                [sys.executable, "-B", "-s", "-X", "utf8", "-c", CHILD, str(ROOT), str(prj),
                 *(repr(value) for value in ED50_POINT)],
                env=env, cwd=folder, capture_output=True, text=True, encoding="utf-8",
                timeout=60, check=False,
            )
        self.assertEqual(done.returncode, 0, done.stderr)
        child = json.loads(done.stdout.strip().splitlines()[-1])
        self.assertEqual(child["wkt2_25830"], H25830.wkt2)
        self.assertEqual(child["identified"], 25830)
        self.assertFalse(child["network"])
        for path in child["data_dirs"]:
            self.assertNotIn(Path(folder).name, path)
        self.assertEqual(Path(child["data_dirs"][-1]).resolve(), GRIDS_DIR.resolve())
        self.assertEqual(child["grids"], ["es_ign_SPED2ETV2.tif"])
        self.assertEqual(child["accuracy"], 0.2)
        here = _service().transformer(H23030, V5782, H25830, V5782)
        expected = here.apply(np.array([ED50_POINT]))[0]
        self.assertEqual(child["description"], here.info.description)
        self.assertEqual([float(value) for value in child["point"]], expected.tolist())

    def test_network_disabled_even_if_the_environment_enables_it(self) -> None:
        """RF-006-05: la red de pyproj queda desactivada aunque ``PROJ_NETWORK=ON``."""
        with mock.patch.dict(os.environ, {"PROJ_NETWORK": "ON"}):
            service = pyproj_crs.PyprojCrsService()
        self.assertFalse(service.network_enabled())
        self.assertFalse(_service().network_enabled())

    def test_data_dirs(self) -> None:
        """RF-006-05: los datos de PROJ son los de la rueda y, después, las rejillas de
        ``thirdparty/proj/``."""
        dirs = _service().data_dirs()
        self.assertEqual(len(dirs), 2)
        self.assertTrue((dirs[0] / "proj.db").is_file())
        self.assertEqual(dirs[0].parts[-3:], ("proj_dir", "share", "proj"))
        self.assertEqual(dirs[1].resolve(), GRIDS_DIR.resolve())

    def test_isolation_restored_after_another_user(self) -> None:
        """RF-006-05: si otro (otra extensión en el mismo Blender) cambia la carpeta de
        datos de pyproj (aquí, a una con un ``proj.db`` falso) o activa la red, el servicio
        vuelve a fijar las suyas antes de usarlas."""
        import pyproj.datadir
        import pyproj.network

        service = _service()
        with tempfile.TemporaryDirectory(prefix="gb-proj-otro-") as folder:
            (Path(folder) / "proj.db").write_bytes(b"esto no es una base de datos de PROJ.")
            try:
                pyproj.datadir.set_data_dir(folder)
                pyproj.network.set_network_enabled(True)
                transform = service.transformer(H23030, V5782, H25830, V5782)
                self.assertEqual(transform.info.grids, ("es_ign_SPED2ETV2.tif",))
                dirs = service.data_dirs()
                self.assertEqual(dirs[0].parts[-3:], ("proj_dir", "share", "proj"))
                self.assertEqual(dirs[1].resolve(), GRIDS_DIR.resolve())
                self.assertFalse(service.network_enabled())
            finally:
                service.wkt2(25830)  # deja el servicio aislado aunque la prueba falle


class CatalogTest(unittest.TestCase):
    """R10 del plan 006: el catálogo de la 002 y el ``proj.db`` de la rueda coinciden."""

    def test_catalog_matches(self) -> None:
        """RF-006-05: los 25 CRS del catálogo son los del ``proj.db`` (mismo WKT2)."""
        service = _service()
        service.check_catalog(CATALOG)
        for ref in (*CATALOG.horizontals(), *CATALOG.verticals()):
            with self.subTest(epsg=ref.epsg):
                self.assertEqual(service.wkt2(ref.epsg), ref.wkt2)

    def test_catalog_mismatch(self) -> None:
        """RF-006-05 (R10): un WKT del catálogo que no es el del ``proj.db`` desactiva el
        servicio con ``gis.crs_catalog_mismatch`` y el CRS."""
        wrong = dataclasses.replace(H25830, wkt2=H25831.wkt2)
        horizontals = [wrong if ref.epsg == 25830 else ref for ref in CATALOG.horizontals()]
        fake = georef.CrsCatalog(horizontals, CATALOG.verticals(), CATALOG.source)
        with self.assertRaises(ports.CrsServiceUnavailable) as caught:
            _service().check_catalog(fake)
        self.assertEqual(caught.exception.code, "gis.crs_catalog_mismatch")
        self.assertEqual(caught.exception.values, {"crs": "EPSG:25830"})

    def test_identify_wkt(self) -> None:
        """RF-006-04: un WKT (ESRI del ``.prj``, WKT1 de GDAL, WKT2, compuesto) se
        identifica con su CRS del catálogo; uno ajeno al catálogo o ilegible, ``None``."""
        service = _service()
        prj = (ROOT / "tests" / "data" / "gis" / "asc" / "corner.prj").read_text("utf-8")
        self.assertEqual(service.identify_wkt(prj), H25830)
        for ref in (H25830, H23030, H4083):
            with self.subTest(epsg=ref.epsg):
                self.assertEqual(service.identify_wkt(ref.wkt1), ref)
                self.assertEqual(service.identify_wkt(ref.wkt2), ref)
        compound = f'COMPD_CS["x",{H23030.wkt1},{_vertical_wkt1()}]'
        self.assertEqual(service.identify_wkt(compound), H23030)
        mercator = (
            'PROJCS["WGS 84 / Pseudo-Mercator",GEOGCS["WGS 84",DATUM["WGS_1984",'
            'SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],'
            'UNIT["degree",0.0174532925199433]],PROJECTION["Mercator_1SP"],'
            'PARAMETER["central_meridian",0],PARAMETER["scale_factor",1],'
            'PARAMETER["false_easting",0],PARAMETER["false_northing",0],UNIT["metre",1],'
            'AUTHORITY["EPSG","3857"]]'
        )
        self.assertIsNone(service.identify_wkt(mercator))
        self.assertIsNone(service.identify_wkt("esto no es un WKT"))
        self.assertIsNone(service.identify_wkt(""))


def _vertical_wkt1() -> str:
    return (
        'VERT_CS["Alicante height",VERT_DATUM["Alicante",2005,AUTHORITY["EPSG","5180"]],'
        'UNIT["metre",1,AUTHORITY["EPSG","9001"]],AXIS["Gravity-related height",UP],'
        'AUTHORITY["EPSG","5782"]]'
    )


class TransformTest(unittest.TestCase):
    """RF-006-05: la transformación de mejor precisión con todas sus rejillas presentes."""

    def test_ed50_to_etrs89_uses_the_ign_grid(self) -> None:
        """RF-006-05: ED50 → ETRS89 cita ``es_ign_SPED2ETV2.tif`` con precisión 0,2 m
        (EPSG «ED50 to ETRS89 (12)»), no un Helmert de 1 a 2 m; la cota no cambia."""
        transform = _service().transformer(H23030, V5782, H25830, V5782)
        self.assertIsInstance(transform, ports.Transform)
        self.assertEqual(transform.info.grids, ("es_ign_SPED2ETV2.tif",))
        self.assertEqual(transform.info.accuracy_m, 0.2)
        self.assertIn("ED50 to ETRS89 (12)", transform.info.description)
        source = np.array([ED50_POINT, (440010.5, 4473990.25, 712.125)])
        kept = source.copy()
        result = transform.apply(source)
        np.testing.assert_array_equal(source, kept)  # no se modifica la entrada
        self.assertEqual(result.dtype, np.float64)
        self.assertEqual(result.shape, (2, 3))
        self.assertTrue(np.isfinite(result).all())
        np.testing.assert_array_equal(result[:, 2], source[:, 2])
        shift = result[:, :2] - source[:, :2]
        self.assertTrue((np.hypot(shift[:, 0], shift[:, 1]) > 100.0).all())

    def test_regente_vertex_published_by_the_ign(self) -> None:
        """RF-006-05 / RF-006-07: el vértice 55901 «IGNE» (Madrid) de la red REGENTE, huso
        30, con las coordenadas de su reseña del IGN de fecha 3-oct-2026
        (https://datos-geodesia.ign.es/Red_Geodesica/Hoja0559/055901.pdf): EPSG:23030 →
        EPSG:25830 con la rejilla ``es_ign_SPED2ETV2.tif`` reproduce su X e Y ETRS89 a
        ≤ 0,2 m (distancia 2D), y en ETRS89 su factor de escala (9 decimales) y su
        convergencia (al segundo) son los publicados, dentro de esa precisión."""
        service = _service()
        transform = service.transformer(H23030, V5782, H25830, V5782)
        self.assertEqual(transform.info.grids, ("es_ign_SPED2ETV2.tif",))
        result = transform.apply(np.array([REGENTE_ED50]))[0]
        error = math.hypot(result[0] - REGENTE_ETRS89[0], result[1] - REGENTE_ETRS89[1])
        self.assertLessEqual(error, REGENTE_TOLERANCE_M, result)
        self.assertEqual(result[2], REGENTE_ED50[2])
        published = np.array([REGENTE_ETRS89])
        self.assertAlmostEqual(
            service.scale_factor(H25830, published)[0], REGENTE_SCALE_ETRS89, delta=5e-10
        )
        self.assertAlmostEqual(
            service.grid_convergence(H25830, published)[0],
            REGENTE_CONVERGENCE_ETRS89,
            delta=0.5 / 3600,
        )

    def test_ellipsoidal_to_alicante_uses_the_geoid(self) -> None:
        """RF-006-05: altura elipsoidal ETRS89 → Alicante cita ``es_ign_egm08-rednap.tif``
        con 0,05 m; X e Y no cambian y la ondulación está entre 40 y 60 m (D-8)."""
        transform = _service().transformer(H25830, ELLIPSOIDAL, H25830, V5782)
        self.assertEqual(transform.info.grids, ("es_ign_egm08-rednap.tif",))
        self.assertEqual(transform.info.accuracy_m, 0.05)
        source = np.array([(500000.0, 4427757.0, 700.0), (400000.0, 4100000.0, 0.0)])
        result = transform.apply(source)
        np.testing.assert_allclose(result[:, :2], source[:, :2], rtol=0, atol=1e-6)
        undulation = source[:, 2] - result[:, 2]
        self.assertTrue(((undulation > 40.0) & (undulation < 60.0)).all(), undulation)

    def test_canary_islands_geoid(self) -> None:
        """RF-006-05: en Canarias (REGCAN95), la altura elipsoidal → Gran Canaria cita
        ``es_ign_egm08-rednap-canarias.tif`` con 0,05 m."""
        transform = _service().transformer(H4083, ELLIPSOIDAL, H4083, V9397)
        self.assertEqual(transform.info.grids, ("es_ign_egm08-rednap-canarias.tif",))
        self.assertEqual(transform.info.accuracy_m, 0.05)

    def test_unknown_accuracy_is_none(self) -> None:
        """RF-006-05: sin una transformación de precisión conocida (Alicante → Mallorca:
        solo la «ballpark» de PROJ; dos referencias locales distintas), ``accuracy_m`` es
        ``None``; un cambio de huso es exacto (0 m)."""
        transform = _service().transformer(H25830, V5782, H25830, V9392)
        self.assertIsNone(transform.info.accuracy_m)
        self.assertEqual(transform.info.grids, ())
        local_a = CATALOG.local_vertical("NP-0 del plano 3")
        local_b = CATALOG.local_vertical("Cota de la boca del pozo 2")
        other = _service().transformer(H25830, local_a, H25830, local_b)
        self.assertIsNone(other.info.accuracy_m)
        zone = _service().transformer(H25830, V5782, H25831, V5782)
        self.assertEqual(zone.info.accuracy_m, 0.0)

    def test_same_local_reference_keeps_heights(self) -> None:
        """RF-006-05: con la misma referencia local en los dos lados solo cambia la
        horizontal (ED50 → ETRS89 con su rejilla) y la cota se conserva tal cual."""
        local = CATALOG.local_vertical("NP-0 del plano 3")
        transform = _service().transformer(H23030, local, H25830, local)
        self.assertEqual(transform.info.grids, ("es_ign_SPED2ETV2.tif",))
        result = transform.apply(np.array([ED50_POINT]))
        self.assertEqual(result[0, 2], ED50_POINT[2])

    def test_apply_contract(self) -> None:
        """RF-006-05: ``apply`` exige (n, 3) y devuelve un array nuevo; fuera de la rejilla
        de PROJ el punto sale no finito (lo trata quien remuestrea, T12)."""
        transform = _service().transformer(H23030, V5782, H25830, V5782)
        with self.assertRaises(ValueError):
            transform.apply(np.zeros((2, 2)))
        outside = transform.apply(np.array([(500000.0, 3000000.0, 0.0)]))
        self.assertFalse(np.isfinite(outside[0, :2]).any())
        self.assertEqual(transform.apply(np.zeros((0, 3))).shape, (0, 3))


class FactorsTest(unittest.TestCase):
    """RF-006-07: factor de escala y convergencia de cuadrícula en el destino."""

    def test_convergence_at_the_zone_edges(self) -> None:
        """RF-006-07: +1,93° ± 0,01° en (0° E; 40° N) y −1,93° en (6° O; 40° N) en
        EPSG:25830, y 0° en el meridiano central (inv. 08 §3.3); positiva al este del
        meridiano central, la misma (≤ 10⁻⁶°) que la calculada con ``core.georef``."""
        points = np.array([_edge_points(0.0), _edge_points(-6.0), _edge_points(-3.0)])
        gamma = _service().grid_convergence(H25830, points)
        self.assertEqual(gamma.shape, (3,))
        self.assertAlmostEqual(gamma[0], 1.93, delta=0.01)
        self.assertAlmostEqual(gamma[1], -1.93, delta=0.01)
        self.assertAlmostEqual(gamma[2], 0.0, delta=1e-9)
        for value, lon in zip(gamma, (0.0, -6.0, -3.0), strict=True):
            self.assertAlmostEqual(value, _convergence_deg(lon, 40.0), delta=1e-6)

    def test_scale_factor(self) -> None:
        """RF-006-07: k = 1,000407 en el borde del huso y 0,9996 en el meridiano central
        (inv. 08 §3.3), el mismo (≤ 10⁻⁹) que el de ``core.georef``."""
        points = np.array([_edge_points(0.0), _edge_points(-3.0)])
        k = _service().scale_factor(H25830, points)
        self.assertAlmostEqual(k[0], 1.000407, delta=5e-7)
        self.assertAlmostEqual(k[1], 0.9996, delta=1e-9)
        for value, lon in zip(k, (0.0, -3.0), strict=True):
            expected = georef.tm_scale(lon, 40.0, H25830.projection)
            self.assertAlmostEqual(value, expected, delta=1e-9)


class VersionTest(unittest.TestCase):
    """RF-006-31: la versión de pyproj es la fijada o el servicio no se crea."""

    def test_pinned_version_is_the_wheel(self) -> None:
        """RF-006-31: la versión esperada es la de ``tools/wheels.toml`` y la cargada."""
        wheels = tomllib.loads(WHEELS_TOML.read_text(encoding="utf-8"))["wheel"]
        pinned = {entry["name"]: entry["version"] for entry in wheels}
        self.assertEqual(pyproj_crs.PYPROJ_VERSION, pinned["pyproj"])
        self.assertEqual(pyproj_crs.installed_version("pyproj"), pinned["pyproj"])

    def test_other_version(self) -> None:
        """RF-006-31: con otra versión de pyproj, ``gis.crs_service_version`` con la
        hallada y la esperada; sin pyproj, ``gis.crs_service_broken``."""
        with mock.patch.object(pyproj_crs, "installed_version", return_value="3.7.1"):
            with self.assertRaises(ports.CrsServiceUnavailable) as caught:
                pyproj_crs.load_service()
        self.assertEqual(caught.exception.code, "gis.crs_service_version")
        self.assertEqual(caught.exception.values, {"found": "3.7.1", "expected": "3.8.0"})
        with mock.patch.object(pyproj_crs, "installed_version", return_value=None):
            with self.assertRaises(ports.CrsServiceUnavailable) as caught:
                registry.crs_service()
        self.assertEqual(caught.exception.code, "gis.crs_service_broken")
        self.assertIn("pyproj", caught.exception.values["detail"])

    def test_registry(self) -> None:
        """RF-006-05: ``adapters.registry`` da el servicio (un ``CrsService``)."""
        self.assertIsInstance(registry.crs_service(), ports.CrsService)


class GridsFolderTest(unittest.TestCase):
    """ADR-0019: las rejillas del IGN sin modificar, con su licencia y su sha256."""

    def test_grids_with_readme_and_license(self) -> None:
        """RF-006-05: ``thirdparty/proj/`` tiene las tres rejillas del plan, su ``LICENSE``
        (CC BY 4.0, igual a ``LICENSES/CC-BY-4.0.txt``) y un ``README.md`` con la
        atribución al IGN y el sha256 de cada rejilla, que coincide."""
        names = sorted(path.name for path in GRIDS_DIR.iterdir())
        self.assertEqual(names, sorted([*GRIDS, "LICENSE", "README.md"]))
        self.assertEqual(pyproj_crs.GRIDS, GRIDS)
        self.assertEqual(
            (GRIDS_DIR / "LICENSE").read_bytes(), (LICENSES_DIR / "CC-BY-4.0.txt").read_bytes()
        )
        readme = (GRIDS_DIR / "README.md").read_text(encoding="utf-8")
        self.assertIn("Instituto Geográfico Nacional", readme)
        self.assertIn("CC BY 4.0", readme)
        listed = dict(re.findall(r"\| `([^`]+\.tif)` \| `([0-9a-f]{64})` \|", readme))
        self.assertEqual(sorted(listed), sorted(GRIDS))
        for name in GRIDS:
            with self.subTest(grid=name):
                digest = hashlib.sha256((GRIDS_DIR / name).read_bytes()).hexdigest()
                self.assertEqual(digest, listed[name])


if __name__ == "__main__":
    unittest.main()
