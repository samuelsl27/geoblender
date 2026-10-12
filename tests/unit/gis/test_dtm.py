# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que preparan sin Blender las órdenes de un MDT (spec 006, T28; plan 006 §5.3.5, §5.6.1 y
§5.6.4): ``gis.dtm``.

- RF-006-09: el lector sale de la extensión del fichero (GeoTIFF ``.tif``/``.tiff``, ESRI
  ASCII Grid ``.asc`` y XYZ en malla ``.xyz``); otra es ``gis.dtm_format_unsupported`` con el
  fichero y la extensión, y un GeoTIFF con una característica no admitida (JPEG) se rechaza al
  leer su cabecera, antes de leer ninguna celda ni empezar nada.
- RF-006-04: el CRS horizontal y el datum vertical son los tecleados o, si no, los que declara
  el fichero (las claves de un GeoTIFF; el ``.prj`` de un ASC, si el servicio de CRS lo
  reconoce); sin uno de los dos, ``gis.crs_undeclared`` o ``gis.vertical_undeclared``, nunca
  los del proyecto. Un CRS tecleado que no es del catálogo es ``gis.crs_text_invalid``. Lo que
  el servicio reconoció en el ``.prj`` (también con el CRS tecleado) va al trabajo en
  ``prj_crs``, que no tiene el servicio (T52).
- RF-006-08: los ajustes de lectura (el sin dato forzado, con coma o punto decimal; el
  separador y el decimal de un XYZ) son los de su lector, y el trabajo de la importación los
  recibe sin ninguna ruta: la fuente va aparte, por papel (``source_main``, ``source_prj``).
- RF-006-06: las posiciones con que se compara un MDT nuevo con uno del proyecto son centros
  de celdas con dato (como mucho ``gis.vertical.MAX_SAMPLES``, repartidas por toda la
  rejilla), en float64 y sin redondear.
- RF-006-26: la biblioteca de las transformaciones y su versión (la fijada en
  ``tools/wheels.toml``) salen de ``adapters.registry`` sin importar pyproj.
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

from tests.support.package import import_geoblender
from tests.support.repo import ROOT

dtm = import_geoblender("gis.dtm")
content = import_geoblender("gis.content")
crs_mod = import_geoblender("gis.crs")
grid_mod = import_geoblender("gis.grid")
raster_mod = import_geoblender("gis.raster")
messages = import_geoblender("gis.messages")
vertical = import_geoblender("gis.vertical")
georef = import_geoblender("core.georef")
errors = import_geoblender("core.errors")
pyproj_crs = import_geoblender("adapters.pyproj_crs")

DATA = ROOT / "tests" / "data" / "gis"
CATALOG = georef.load_catalog()
H25830 = CATALOG.horizontal(25830)
H23030 = CATALOG.horizontal(23030)
V5782 = CATALOG.vertical(5782)


class _Identify:
    """El ``identify_wkt`` de un servicio de CRS de prueba: da ``found`` y apunta el WKT."""

    def __init__(self, found: object) -> None:
        self.found = found
        self.seen: list[str] = []

    def __call__(self, wkt: str) -> object:
        self.seen.append(wkt)
        return self.found


class ReaderTest(unittest.TestCase):
    def test_reader_by_extension(self) -> None:
        """RF-006-08, RF-006-09: GeoTIFF (``.tif``, ``.tiff``, en mayúsculas o no), ASC y XYZ
        en malla tienen su lector; otra extensión se rechaza con el fichero y la extensión."""
        for name, reader in (("mdt.tif", content.GEOTIFF), ("MDT.TIFF", content.GEOTIFF),
                             ("mdt05.asc", content.ASC), ("malla.XYZ", content.XYZ_GRID)):
            with self.subTest(fichero=name):
                self.assertIs(dtm.dtm_reader(Path("entregas") / name), reader)
        with self.assertRaises(messages.GisError) as caught:
            dtm.dtm_reader(Path("entregas") / "ortofoto.png")
        error = caught.exception
        self.assertEqual((error.code, error.value), ("gis.dtm_format_unsupported", ".png"))
        self.assertEqual(str(error), "MDT «ortofoto.png»: la extensión «.png» no es de un "
                                     "formato admitido (GeoTIFF .tif o .tiff, ESRI ASCII Grid "
                                     ".asc o XYZ en malla .xyz).")

    def test_crs_text(self) -> None:
        """RF-006-04: el CRS tecleado, con o sin «EPSG:», es uno del catálogo; vacío, ninguno
        (el que declare el fichero); otro texto o un código fuera del catálogo se rechaza."""
        for text in ("EPSG:23030", "epsg: 23030", " 23030 "):
            with self.subTest(texto=text):
                self.assertEqual(dtm.parse_crs(text), H23030)
        self.assertIsNone(dtm.parse_crs("  "))
        for text in ("EPSG:4326", "UTM 30", "EPSG:"):
            with self.subTest(texto=text), self.assertRaises(messages.GisError) as caught:
                dtm.parse_crs(text)
            self.assertEqual((caught.exception.code, caught.exception.value),
                             ("gis.crs_text_invalid", text))


class PlanTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="gb-t28-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def copy(self, relative: str, *, name: str | None = None) -> Path:
        source = DATA / relative
        target = self.tmp / (name or source.name)
        shutil.copyfile(source, target)
        return target

    def test_geotiff_declares_its_crs_but_not_its_datum(self) -> None:
        """RF-006-04: un GeoTIFF que declara su CRS horizontal y no su datum vertical exige
        declarar el datum (no se toma el del proyecto); declarado, el CRS es el del fichero y
        el sin dato forzado queda en los ajustes de lectura."""
        path = self.copy("geotiff/f64_strip.tif")
        with self.assertRaises(messages.GisError) as caught:
            dtm.plan_import(path, name="MDT dron")
        self.assertEqual(caught.exception.code, "gis.vertical_undeclared")
        self.assertIn("«MDT dron» no declara su datum vertical", str(caught.exception))
        source = dtm.plan_import(path, name="MDT dron", vertical=V5782,
                                 settings=dtm.read_settings(content.GEOTIFF,
                                                            nodata_override="-9 999,5"))
        self.assertEqual((source.reader, source.crs, source.vertical),
                         (content.GEOTIFF, H25830, V5782))
        self.assertEqual(dict(source.files), {"main": path})
        self.assertEqual(dict(source.settings), {"nodata_override": -9999.5})
        typed = dtm.plan_import(path, name="MDT dron", crs=H23030, vertical=V5782)
        self.assertIs(typed.crs, H23030)  # lo tecleado manda

    def test_unsupported_geotiff_is_rejected_before_reading(self) -> None:
        """RF-006-09: un GeoTIFF con compresión JPEG se rechaza al leer su cabecera, con el
        fichero, la característica y qué hacer, antes de leer ninguna celda."""
        with self.assertRaises(messages.GisError) as caught:
            dtm.plan_import(self.copy("geotiff/u8_jpeg.tif"), name="Orto", vertical=V5782)
        self.assertEqual(caught.exception.code, "gis.tiff_compression_unsupported")
        self.assertIn("JPEG", str(caught.exception))

    def test_xyz_and_asc_declare_through_the_dialog_or_the_prj(self) -> None:
        """RF-006-04: un XYZ no declara nada (su separador y su decimal quedan en los ajustes
        de lectura); un ASC declara su CRS por su ``.prj`` si el servicio de CRS lo reconoce
        (con su ``.prj`` como fichero compañero), y si no, hay que declararlo."""
        xyz = self.copy("xyz/grid.xyz")
        settings = dtm.read_settings(content.XYZ_GRID, separator=" ", decimal=".")
        with self.assertRaises(messages.GisError) as caught:
            dtm.plan_import(xyz, name="Malla", vertical=V5782, settings=settings)
        self.assertEqual(caught.exception.code, "gis.crs_undeclared")
        source = dtm.plan_import(xyz, name="Malla", crs=H25830, vertical=V5782,
                                 settings=settings)
        self.assertEqual(dict(source.settings), {"separator": " ", "decimal": "."})
        self.assertEqual(dict(dtm.read_settings(content.XYZ_GRID, decimal=",")),
                         {"decimal": ","})  # sin separador: se detecta al leer
        asc = self.copy("asc/corner.asc")
        prj = self.copy("asc/corner.prj")
        identify = _Identify(H25830)
        source = dtm.plan_import(asc, name="MDT05", vertical=V5782, identify=identify)
        self.assertEqual((source.crs, dict(source.files)), (H25830, {"main": asc, "prj": prj}))
        self.assertEqual(identify.seen, [prj.read_text("utf-8").strip()])
        for found in (None, _Identify(None)):
            with self.subTest(servicio=found), self.assertRaises(messages.GisError) as caught:
                dtm.plan_import(asc, name="MDT05", vertical=V5782, identify=found)
            self.assertEqual(caught.exception.code, "gis.crs_undeclared")

    def test_prj_recognised_by_the_order_goes_to_the_job(self) -> None:
        """RF-006-04 (T52): el ``.prj`` de un ASC se identifica también con el CRS tecleado
        (que manda), y el trabajo recibe en ``prj_crs`` lo que reconoció el servicio de CRS
        de la orden (el trabajo no tiene pyproj), para que su informe no diga que no se
        reconoció; sin reconocerlo, sin servicio o sin ``.prj``, no lo recibe. Un GeoTIFF
        declara su CRS con sus claves: tampoco."""
        asc = self.copy("asc/corner.asc")
        prj = self.copy("asc/corner.prj")
        identify = _Identify(H25830)
        typed = dtm.plan_import(asc, name="MDT05", crs=H23030, vertical=V5782,
                                identify=identify)
        self.assertEqual((typed.crs, typed.prj_crs), (H23030, H25830))
        self.assertEqual(identify.seen, [prj.read_text("utf-8").strip()])
        self.assertEqual(dtm.job_params(typed, max_cells=10)["prj_crs"], {"epsg": 25830})
        self.assertEqual(dtm.identify_prj(asc, identify), H25830)
        for found in (None, _Identify(None)):
            with self.subTest(servicio=found):
                source = dtm.plan_import(asc, name="MDT05", crs=H25830, vertical=V5782,
                                         identify=found)
                self.assertIsNone(source.prj_crs)
                self.assertNotIn("prj_crs", dtm.job_params(source, max_cells=10))
        prj.unlink()
        identify = _Identify(H25830)
        bare = dtm.plan_import(asc, name="MDT05", crs=H25830, vertical=V5782, identify=identify)
        self.assertIsNone(bare.prj_crs)
        self.assertIsNone(dtm.identify_prj(asc, identify))
        self.assertEqual(identify.seen, [])
        tif = dtm.plan_import(self.copy("geotiff/f64_strip.tif"), name="MDT dron",
                              vertical=V5782, identify=identify)
        self.assertIsNone(tif.prj_crs)
        self.assertNotIn("prj_crs", dtm.job_params(tif, max_cells=10))
        self.assertEqual(identify.seen, [])

    def test_nodata_override_text(self) -> None:
        """RF-006-08: el sin dato forzado se teclea con coma o punto decimal; vacío, ninguno;
        lo que no es un número se rechaza con el campo."""
        self.assertEqual(dict(dtm.read_settings(content.ASC, nodata_override="")), {})
        self.assertEqual(dict(dtm.read_settings(content.ASC, nodata_override="0.5")),
                         {"nodata_override": 0.5})
        with self.assertRaises(errors.GeoblenderError) as caught:
            dtm.read_settings(content.GEOTIFF, nodata_override="sin dato")
        self.assertEqual(caught.exception.code, "core.number_invalid")

    def test_job_params_carry_no_path(self) -> None:
        """RF-006-08 (ARQ-11): el trabajo de la importación recibe el lector, el nombre, los
        ajustes, los CRS declarados, el límite de celdas y el tamaño, sin ninguna ruta; las
        rutas de la fuente van aparte, por papel."""
        asc = self.copy("asc/corner.asc")
        prj = self.copy("asc/corner.prj")
        source = dtm.plan_import(asc, name="MDT05", vertical=V5782, identify=_Identify(H25830),
                                 settings=dtm.read_settings(content.ASC, nodata_override="-1"))
        params = dtm.job_params(source, max_cells=1000)
        self.assertEqual(params, {"reader": "gis.asc@1", "name": "MDT05",
                                  "settings": {"nodata_override": -1.0},
                                  "crs": {"epsg": 25830}, "vertical": {"epsg": 5782},
                                  "prj_crs": {"epsg": 25830},
                                  "max_cells": 1000, "size": asc.stat().st_size})
        self.assertNotIn(str(self.tmp), json.dumps(params))
        self.assertEqual(dtm.job_paths(source), {"source_main": asc, "source_prj": prj})

    def test_origin_only_for_a_source_in_the_project_crs(self) -> None:
        """RF-002-26 (T51; spec §8): el trabajo recibe el GeoOrigin del proyecto (``origin``)
        para decir cuántos centros de sus celdas con dato pasan de 8 km solo si la fuente
        está en el CRS horizontal del proyecto (lo que llegaría así a la escena); en otro
        (ED50), no, y sin él, el trabajo no lo recibe."""
        origin = georef.GeoOrigin(700_000, 4_400_000, 0)
        tif = dtm.plan_import(self.copy("geotiff/f64_strip.tif"), name="MDT dron",
                              vertical=V5782)
        ed50 = dtm.plan_import(self.copy("geotiff/f64_strip.tif", name="plano.tif"),
                               name="Plano", crs=H23030, vertical=V5782)
        self.assertIs(dtm.scene_origin(tif, H25830, origin), origin)
        self.assertIsNone(dtm.scene_origin(ed50, H25830, origin))
        params = dtm.job_params(tif, max_cells=10, origin=origin)
        self.assertEqual(params["origin"], {"x0": 700_000, "y0": 4_400_000, "z0": 0})
        self.assertNotIn("origin", dtm.job_params(tif, max_cells=10))


class SamplesTest(unittest.TestCase):
    def test_samples_are_centres_with_data(self) -> None:
        """RF-006-06: las posiciones de la comparación son los centros (float64, los de
        ``Grid.centers``, sin redondear) de las celdas con dato, todas si caben y, si no,
        repartidas por toda la rejilla, como mucho ``limit``."""
        grid = grid_mod.Grid(700_123.25, 4_400_321.5, 0.5, 0.5, 40, 30)
        rows, cols = np.mgrid[0:30, 0:40]
        values = 800.0 + rows * 0.1 + cols * 0.01
        values[5:9, 10:14] = np.nan
        raster = raster_mod.Raster(grid, values, H25830, V5782)
        xyz = dtm.vertical_samples(raster)
        x, y = grid.centers()
        valid = np.isfinite(values)
        self.assertEqual(xyz.dtype, np.float64)
        self.assertTrue(np.array_equal(xyz, np.column_stack([x[valid], y[valid],
                                                             values[valid]])))
        few = dtm.vertical_samples(raster, limit=100)
        self.assertLessEqual(len(few), 100)
        self.assertGreater(len(few), 50)
        self.assertTrue(np.isfinite(few).all())
        self.assertLess(few[:, 0].min(), grid.west + 2.0)  # de un borde al otro
        self.assertGreater(few[:, 0].max(), grid.west + grid.ncols * grid.dx - 2.0)
        self.assertEqual(dtm.MAX_SAMPLES, vertical.MAX_SAMPLES)


class LibraryTest(unittest.TestCase):
    def test_crs_library_without_pyproj(self) -> None:
        """RF-006-26: la biblioteca de las transformaciones y su versión fijada, sin importar
        pyproj (la procedencia la anota en cada remuestreo)."""
        loaded = "pyproj" in sys.modules
        self.assertEqual(crs_mod.crs_library(), ("pyproj", pyproj_crs.PYPROJ_VERSION))
        self.assertEqual("pyproj" in sys.modules, loaded)


if __name__ == "__main__":
    unittest.main()
