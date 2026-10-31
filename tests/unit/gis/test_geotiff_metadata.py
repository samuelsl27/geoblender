# SPDX-License-Identifier: GPL-3.0-or-later
"""Metadatos de texto en el GeoTIFF propio (spec 012, T20; RF-012-20; plan 012 D-32).

La leyenda de la rejilla de clases va en el propio GeoTIFF (``GDAL_METADATA``, el XML de GDAL,
etiqueta 42112) además de en su ``.qml``: ``write_steps`` y ``write_geotiff`` admiten
``metadata`` (nombre → texto) y ``gis.geotiff.geokeys`` lo escribe y lo lee.

- Sin ``metadata`` (o vacío) el fichero es **el mismo, bit a bit**, que antes de la T20: ninguna
  etiqueta nueva (los GeoTIFF de la 006 y la 011 no cambian).
- Con ``metadata``, la etiqueta es texto ASCII (el tipo ``ASCII`` de TIFF es de 7 bits): los
  acentos y la «ñ» van como referencias numéricas de XML (``&#225;``) y vuelven iguales; los
  caracteres de XML, escapados; el orden de los elementos, el de la entrada.
- El resto del fichero no cambia: el lector lo lee igual (rejilla, CRS, valores) y la escala, el
  offset y la unidad siguen siendo los de la 006 (1, 0, sin unidad).
- Un nombre que no es un identificador (``[A-Za-z_][A-Za-z0-9_.]*``), un valor que no es texto o
  que lleva un «&» (GDAL 3.13 desescapa dos veces y corta el texto: lo comprobó el experimento de
  la T20) se rechazan antes de escribir nada.
- Con el GDAL de QGIS (si hay ``GEOBLENDER_QGIS_DIR``), ``gdalinfo -json`` lee los mismos
  metadatos, con sus acentos; si no, omisión ``[ENTORNO] qgis``.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from tests.support import qgis
from tests.support.package import import_geoblender
from tests.support.resources import requires

writer = import_geoblender("gis.geotiff.writer")
reader = import_geoblender("gis.geotiff.reader")
geokeys = import_geoblender("gis.geotiff.geokeys")
tiff = import_geoblender("gis.geotiff.tiff")
grid_mod = import_geoblender("gis.grid")
raster_mod = import_geoblender("gis.raster")
georef = import_geoblender("core.georef")

CATALOG = georef.load_catalog()
CRS = CATALOG.horizontal(25830)
VERTICAL = CATALOG.vertical(5782)
GRID = grid_mod.Grid(700000.0, 4400100.0, 2.0, 2.0, 40, 30)
ITEMS = {
    "LEYENDA": "Cada valor suma los bits de las clases de la celda",
    "CLASE_3": "Corte admitido + Relleno admitido",
    "CLASE_11": "Límite + «perímetro» <ñandú> \"comillas\" 'simples'",
}


def _values() -> np.ndarray:
    values = np.arange(30 * 40, dtype=np.float64).reshape(30, 40) % 2048
    values[3, 4] = np.nan
    return values


def _raster() -> object:
    return raster_mod.Raster(GRID, _values(), CRS, VERTICAL)


def _ifd(path: Path) -> object:
    with path.open("rb") as stream:
        return tiff.read_first_ifd(stream, path.stat().st_size)


class MetadataTest(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory(prefix="gb-gm-")
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def write(self, name: str, profile: str, **options: object) -> Path:
        return writer.write_geotiff(_raster(), self.folder / name, profile=profile, **options)

    def test_without_metadata_the_file_is_unchanged(self) -> None:
        """RF-012-20: sin ``metadata`` (omitido, ``None`` o vacío) no hay etiqueta
        ``GDAL_METADATA`` y los bytes son los de siempre, en los dos perfiles."""
        for profile in ("project", "deliverable"):
            with self.subTest(profile):
                plain = self.write(f"{profile}.tif", profile).read_bytes()
                for given in (None, {}):
                    again = self.write(f"{profile}-{given}.tif", profile, metadata=given)
                    self.assertEqual(again.read_bytes(), plain)
                self.assertNotIn(tiff.GDAL_METADATA, _ifd(self.folder / f"{profile}.tif").tags)

    def test_text_in_the_tag_round_trips(self) -> None:
        """RF-012-20: la etiqueta 42112 es ASCII puro (acentos como referencias numéricas),
        vuelve igual con ``parse_gdal_items`` y sigue el orden de la entrada; escala, offset y
        unidad no cambian."""
        path = self.write("meta.tif", "deliverable", metadata=ITEMS)
        text = _ifd(path).text(tiff.GDAL_METADATA)
        assert text is not None
        text.encode("ascii")  # no lanza: es ASCII
        self.assertTrue(text.startswith("<GDALMetadata>"))
        self.assertIn("&#237;", text)  # la «í» de «Límite», como referencia numérica
        self.assertIn("&#241;", text)  # la «ñ»
        self.assertIn("&lt;", text)
        self.assertIn("&gt;", text)
        self.assertEqual(geokeys.parse_gdal_items(text), ITEMS)
        self.assertEqual(list(geokeys.parse_gdal_items(text)), list(ITEMS))
        self.assertEqual(geokeys.parse_gdal_metadata(text), geokeys.GdalMetadata(1.0, 0.0, ""))

    def test_the_rest_of_the_file_is_read_the_same(self) -> None:
        """RF-012-20: con metadatos, el lector da la misma rejilla, el mismo CRS y los mismos
        valores (con el sin dato −9999 del entregable) que sin ellos."""
        plain = reader.read_geotiff(self.write("a.tif", "deliverable"))
        with_meta = reader.read_geotiff(self.write("b.tif", "deliverable", metadata=ITEMS))
        self.assertEqual(with_meta.grid, plain.grid)
        self.assertEqual(with_meta.declared_crs, plain.declared_crs)
        np.testing.assert_array_equal(with_meta.values, plain.values)
        self.assertTrue(np.isnan(with_meta.values[3, 4]))

    def test_steps_and_project_profile_take_it_too(self) -> None:
        """RF-012-20: ``write_steps`` da los mismos bytes que ``write_geotiff``, y el perfil
        ``project`` también lleva la etiqueta."""
        target = self.folder / "steps.tif"
        steps = writer.write_steps(_raster(), target, profile="project", metadata=ITEMS)
        try:
            while True:
                next(steps)
        except StopIteration as stop:
            self.assertEqual(stop.value, target)
        whole = self.write("whole.tif", "project", metadata=ITEMS)
        self.assertEqual(target.read_bytes(), whole.read_bytes())
        self.assertIn(tiff.GDAL_METADATA, _ifd(target).tags)

    def test_bad_metadata_is_refused_before_writing(self) -> None:
        """RF-012-20: un nombre que no es un identificador o un valor que no es texto son
        errores del programa (``ValueError``/``TypeError``), sin crear ni el temporal."""
        for bad, error in (({"": "x"}, ValueError), ({"con espacio": "x"}, ValueError),
                           ({"1CLASE": "x"}, ValueError), ({"A": 3}, TypeError),
                           ({"A": None}, TypeError), ({"A": "Corte & relleno"}, ValueError)):
            with self.subTest(bad):
                with self.assertRaises(error):
                    writer.write_geotiff(_raster(), self.folder / "bad.tif", profile="deliverable",
                                         metadata=bad)  # type: ignore[arg-type]
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_format_and_parse_are_inverse(self) -> None:
        """RF-012-20: ``format_gdal_metadata`` / ``parse_gdal_items``: los caracteres de
        control no admitidos en XML se rechazan; un texto vacío es un valor válido."""
        text = geokeys.format_gdal_metadata({"A": "", "B": "x\ny"})
        self.assertEqual(geokeys.parse_gdal_items(text), {"A": "", "B": "x\ny"})
        with self.assertRaises(ValueError):
            geokeys.format_gdal_metadata({"A": "mal\x00dato"})

    @requires(qgis.QGIS, qgis.QGIS_HINT)
    def test_gdal_of_qgis_reads_it(self) -> None:
        """RF-012-20: ``gdalinfo -json`` del GDAL de QGIS lee los metadatos con sus acentos,
        la misma georreferencia y ningún aviso."""
        path = self.write("gdal.tif", "deliverable", metadata=ITEMS)
        result = qgis.run_tool("gdalinfo", "-json", str(path))
        self.assertEqual(result.returncode, 0, qgis.output_of(result))
        info = json.loads(result.stdout)
        shown = dict(info["metadata"][""])
        self.assertEqual(shown.pop("AREA_OR_POINT"), "Area")  # lo añade GDAL por *PixelIsArea*
        self.assertEqual(shown, ITEMS)
        self.assertEqual(info["size"], [40, 30])
        self.assertIn("25830", json.dumps(info["coordinateSystem"]))


if __name__ == "__main__":
    unittest.main()
