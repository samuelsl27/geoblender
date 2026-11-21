# SPDX-License-Identifier: GPL-3.0-or-later
"""Exportar la pista (spec 017, T27; HU-017-1 y HU-017-4; RF-017-27, RF-013-34, RF-006-24 y RF-008-15; plan 017 §5.3.3 «Exportar pista…»; decisión T27-a): el GeoTIFF de la superficie de la pista
(``des_psf_``, que ya exportaba la 015) y de **lo alcanzable** de una accesibilidad (``des_acc_``: un código por celda, 1 alcanzable y 0 no, con su leyenda) y **la rasante a CSV** (abscisa, x, y, cota del
terreno, cota de la rasante y pendiente, en m y en %) con la convención del CSV de la cubicación (UTF-8 con BOM, «;» y CRLF, para una hoja de cálculo en español), **sin modificar nada del proyecto** (RF-017-27).
Con el proyecto (el GeoTIFF y el CSV de una pista y una accesibilidad calculadas, los rechazos, el destino y que nada se escribe en el proyecto) es de ``milestone_road_export``.

- **El GeoTIFF** (:class:`RoadGridsTest`): lo alcanzable es una rejilla exportable de **códigos** con su leyenda en los metadatos; la superficie de una pista, una de las de la 015.
- **El CSV** (:class:`RoadCsvTest`): sus columnas con su unidad, los números **con coma decimal y sin pérdida** (el decimal más corto que vuelve al mismo float64, ≤ 10⁻⁹ de diferencia), el BOM, el «;» y el
  CRLF, y que la primera celda no es «ID»; el destino, con la extensión de un CSV.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any

import numpy as np

from tests.support.package import import_geoblender

export = import_geoblender("design.export")
gis_messages = import_geoblender("gis.messages")
paths = import_geoblender("core.paths")
provenance = import_geoblender("design.provenance")

ACCESS = provenance.ACCESS_GRID
STATIONS = np.array([
    [0.0, 725_000.123456789, 4_400_000.456, 104.0, 104.0, 4.0],
    [1.0, 725_001.0, 4_400_000.456, 104.04, 104.04, 4.0],
    [2.5, 725_002.5, 4_400_000.4560000001, 104.1, 104.1000000001, -0.0],
    [10.0, 725_010.0, 4_400_000.456, 104.4, 104.4, 12.345678901234],
], dtype=np.float64)


def parse(data: bytes) -> list[list[str]]:
    """Las filas del CSV tal como las lee una hoja de cálculo en español: UTF-8 con BOM, «;» y CRLF."""
    text = data.decode("utf-8-sig")
    return [line.split(";") for line in text.split("\r\n") if line]


class RoadGridsTest(unittest.TestCase):
    """RF-017-27, RF-013-34, RF-006-24: lo alcanzable se exporta como una rejilla de códigos."""

    def test_a_the_reachable_grid_is_exportable_with_its_legend(self) -> None:
        """RF-017-27: ``des_acc_`` (lo alcanzable de una accesibilidad) es una rejilla de ``export.GRIDS``, de **códigos** con su leyenda (0 «no alcanzable», 1 «alcanzable»): los metadatos del GeoTIFF dicen
        ``UNIDAD`` «código», qué es, el dato y la versión, y un ``CODIGO_<n>`` por clase; la superficie de una pista (``des_psf_``) es una de las de la 015."""
        self.assertIn(ACCESS, export.GRIDS)
        self.assertIn(provenance.ENTITY_SURFACE_GRID, export.GRIDS)
        self.assertEqual(export.LEGENDS[ACCESS], ((0, "no alcanzable"), (1, "alcanzable")))
        items = export.metadata_items(ACCESS, "Accesibilidad de la cantera", "V01")
        self.assertEqual(items, {"UNIDAD": "código", "TIPO": "Lo alcanzable por las pistas", "DATO": "des_acc_accesibilidad_de_la_cantera", "VERSION": "V01", "CODIGO_0": "no alcanzable",
                                 "CODIGO_1": "alcanzable"})
        road = export.metadata_items(provenance.ENTITY_SURFACE_GRID, "Pista a P1", "V01")
        self.assertEqual((road["UNIDAD"], road["DATO"]), ("m", "des_psf_pista_a_p1"))

    def test_b_the_other_exportable_grids_do_not_change(self) -> None:
        """RF-013-34, RF-014-32, RF-016-24: las rejillas que ya se exportaban siguen siendo las mismas (y con las mismas leyendas): solo se añade lo alcanzable."""
        before = (provenance.ENVELOPE_GRID, provenance.DESIGN_GRID, provenance.BERMS_GRID, *export.QUARRY_GRIDS, *export.ENTITY_GRIDS, *export.SUPPORTED_GRIDS)
        self.assertEqual(export.GRIDS, (*before, *export.ROAD_GRIDS))
        self.assertEqual(export.ROAD_GRIDS, (ACCESS,))
        self.assertEqual(set(export.LEGENDS), {provenance.CLASSIFICATION_GRID, provenance.EXCAVATION_AREA_GRID, ACCESS})


class RoadCsvTest(unittest.TestCase):
    """RF-017-27, T27-a: la rasante a CSV."""

    def test_a_the_columns_are_the_ones_of_the_spec_with_their_unit_and_the_csv_follows_the_convention_of_the_cubication(self) -> None:
        """RF-017-27, T27-a: abscisa, x, y, cota del terreno, cota de la rasante y pendiente, **en m y en %** (la unidad en el título); UTF-8 **con BOM**, «;» de separador y filas acabadas en CRLF
        (como el CSV de la cubicación, para una hoja de cálculo en español); la primera celda no es «ID» (Excel tomaría el fichero por SYLK)."""
        data = export.road_csv_bytes(STATIONS)
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\n", data.replace(b"\r\n", b""))
        rows = parse(data)
        self.assertEqual(rows[0], ["Abscisa (m)", "X (m)", "Y (m)", "Cota del terreno (m)", "Cota de la rasante (m)", "Pendiente (%)"])
        self.assertNotEqual(rows[0][0], "ID")
        self.assertEqual(len(rows), 1 + len(STATIONS))
        self.assertEqual(export.CSV_COLUMNS, tuple(rows[0]))

    def test_b_the_numbers_come_back_to_the_same_float64_with_a_decimal_comma(self) -> None:
        """RF-017-27: cada número es el decimal más corto que vuelve al **mismo float64** (el valor exacto: la diferencia es 0, dentro de ≤ 10⁻⁹), con **coma decimal**, sin separador de miles ni
        exponente; −0 es «0»; las coordenadas absolutas (4,4 Mm) no pierden ningún dígito."""
        rows = parse(export.road_csv_bytes(STATIONS))[1:]
        found = np.array([[float(cell.replace(",", ".")) for cell in row] for row in rows])
        self.assertTrue(np.array_equal(found, np.where(STATIONS == 0.0, 0.0, STATIONS)))
        self.assertLessEqual(float(np.abs(found - STATIONS).max()), 1e-9)
        self.assertEqual(rows[0][1], "725000,123456789")
        self.assertEqual(rows[2][5], "0")
        self.assertTrue(all("e" not in cell.lower() and "." not in cell for row in rows for cell in row))

    def test_c_what_is_not_a_table_of_stations_is_a_programme_error(self) -> None:
        """RF-017-27 (errores del programa): una tabla que no son seis columnas finitas, o ninguna estación, no se escribe."""
        for bad in (np.zeros((3, 5)), np.zeros((0, 6)), np.array([[0.0, 1.0, 2.0, 3.0, 4.0, np.nan]]), np.zeros(6)):
            with self.subTest(shape=bad.shape), self.assertRaises(ValueError):
                export.road_csv_bytes(bad)

    def test_d_the_target_of_a_csv_has_the_extension_of_a_csv(self) -> None:
        """RF-017-27, RF-008-15: el destino de un CSV se comprueba con la extensión de un CSV (``gis.export_extension_invalid``, que dice «CSV» y «.csv»); el de un GeoTIFF sigue pidiendo la suya: con un
        ``.csv``, el mismo rechazo."""
        project = SimpleNamespace(root="C:/no/existe", name="p", writable=True)
        for path, kwargs, label in (("pista.tif", {"suffixes": export.CSV_SUFFIXES, "label": "CSV"}, "CSV"), ("rejilla.csv", {}, "GeoTIFF")):
            with self.subTest(path), self.assertRaises(gis_messages.GisError) as caught:
                export.check_target(path, project=project, read_only=paths.ReadOnlyDirs.from_sources(None, []), overwrite=False, **kwargs)
            self.assertEqual(caught.exception.code, "gis.export_extension_invalid")
            self.assertEqual(caught.exception.values["format"], label)


def stations_of(rows: Any) -> np.ndarray:
    """Las estaciones de ``rows`` como la tabla ``(n, 6)`` que escribe el CSV."""
    return np.asarray(rows, dtype=np.float64)


if __name__ == "__main__":
    unittest.main()
