# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo guardado de la topografía para la vista (spec 006, T27; RF-006-19, RF-006-29; plan 006
§5.3.2 y §5.6.7; principio 6).

``gis.store`` lee, sin escribir nada en el proyecto, lo que la vista de Blender
(``bl/scene/gis_views.py``) muestra de una tabla de la topografía (``load_features``: sus
geometrías absolutas en float64, tal como están guardadas, en el orden de sus entidades, y sus
atributos) y comprueba que un dato está en el CRS horizontal y la referencia vertical del
proyecto (``require_project_references``): lo importado está en los que declaró su entrada, sin
transformar (RF-006-12), y la vista no lo muestra en otro sin decirlo (principio 6: un CRS que
no coincide es un error con mensaje claro, nunca un supuesto). Sobre el proyecto sintético de
``test_store`` (``ImportCase``), con los puntos y las líneas de rotura de ``taludes.csv``.
"""

from __future__ import annotations

import struct
from typing import Any

import numpy as np

from tests.support.package import import_geoblender
from tests.unit.gis.test_store import (
    CRS,
    ED50,
    POINT_SETTINGS,
    VERTICAL,
    ImportCase,
    _lines,
)

store = import_geoblender("gis.store")
provenance = import_geoblender("gis.provenance")
gis_content = import_geoblender("gis.content")
points_mod = import_geoblender("gis.points")
messages = import_geoblender("gis.messages")
csv_tables = import_geoblender("interop.csv_tables")
wkb = import_geoblender("core.gpkg.wkb")

POINT_MAPPING = points_mod.ColumnMapping(x=1, y=2, z=3, point_id=0, code=4, line=5)


class StoredFeaturesTest(ImportCase):
    def import_points(self, name: str = "Taludes", *, crs: Any = CRS) -> tuple[Any, Any]:
        """``gis.import_points`` de ``fuentes/taludes.csv`` declarado en ``crs`` (y la
        referencia vertical del proyecto): sus puntos y sus líneas de rotura."""
        source = self.sources / "taludes.csv"
        spec = self.source_spec(gis_content.POINTS_TEXT, name, "taludes.csv", crs=crs,
                                settings=POINT_SETTINGS)
        table = csv_tables.read_table(source, encoding="utf-8", separator=";")
        points, lines, _report = points_mod.points_from_rows(
            table.columns, table.rows, POINT_MAPPING, ",", row_numbers=table.lines)
        handle = self.begin(provenance.IMPORT_POINTS, settings={"nombre": name})
        with store.ResultWriter(self.project, handle) as out:
            out.declare_input(spec)
            out.points(name, points)
            out.breaklines(name, lines)
            out.commit(message=f"{len(points)} puntos y {len(lines)} líneas de rotura")
        return points, lines

    def test_points_and_breaklines_as_stored(self) -> None:
        """RF-006-19, RF-006-12: los puntos importados vuelven con sus coordenadas absolutas
        bit a bit (float64), en el orden de sus entidades, con su identificador, su código y
        su fila; las líneas de rotura, cada una con sus vértices bit a bit, su identificador y
        si es dura. Leerlas no cambia el proyecto."""
        points, lines = self.import_points()
        before = self.state()
        found = store.load_features(self.project, "gis_pts_taludes")
        self.assertEqual(found.name, "gis_pts_taludes")
        self.assertEqual(len(found.geometries), len(points))
        stacked = np.vstack(found.geometries)
        self.assertEqual(stacked.dtype, np.float64)
        self.assertTrue(np.array_equal(stacked.view(np.uint64), points.xyz.view(np.uint64)))
        self.assertEqual(found.attributes["point_id"], tuple(points.point_ids))
        self.assertEqual(found.attributes["code"], tuple(points.codes))
        self.assertEqual(found.attributes["source_row"], tuple(points.source_rows))
        breaks = store.load_features(self.project, "gis_brk_taludes")
        self.assertEqual(len(breaks.geometries), len(lines))
        for got, line in zip(breaks.geometries, lines, strict=True):
            with self.subTest(linea=line.line_id):
                self.assertEqual(got.shape, line.xyz.shape)
                self.assertTrue(np.array_equal(got.view(np.uint64), line.xyz.view(np.uint64)))
        self.assertEqual(breaks.attributes["line_id"], tuple(line.line_id for line in lines))
        self.assertEqual(breaks.attributes["hard"], (1,) * len(lines))
        # T35 (RNF-006-09): para un TIN, los puntos se leen de una vez, bit a bit; un blob
        # que no es el POINT Z de Geoblender (otro SRS, con envolvente, un NaN) se lee uno a
        # uno.
        loaded = store.load_points(self.project, "gis_pts_taludes")
        self.assertTrue(np.array_equal(loaded.xyz.view(np.uint64), points.xyz.view(np.uint64)))
        self.assertEqual((loaded.point_ids, loaded.codes, loaded.source_rows),
                         (tuple(points.point_ids), tuple(points.codes),
                          tuple(points.source_rows)))
        blobs = [wkb.encode_geometry("POINT", xyz, 25830, True) for xyz in points.xyz]
        self.assertTrue(np.array_equal(store._point_coords(blobs), points.xyz))
        self.assertEqual(store._point_coords([]).shape, (0, 3))
        nan = wkb.encode_geometry("POINT", points.xyz[0], 25830, True)[:-8] + struct.pack(
            "<d", float("nan"))
        for odd in (wkb.encode_geometry("POINT", points.xyz[0], 4258, True),
                    wkb.encode_geometry("POINT", points.xyz[0, :2], 25830, False),
                    wkb.encode_geometry("LINESTRING", points.xyz[:1].repeat(2, 0), 25830,
                                        True)[:len(blobs[0])], nan):
            self.assertIsNone(store._point_coords([*blobs, odd]))
        self.assertEqual(self.state(), before)

    def test_contours_as_stored_and_rejections(self) -> None:
        """RF-006-19: las curvas vuelven tal como están guardadas, la cerrada con su primer
        vértice repetido al final, con su cota, si es maestra y si es cerrada; un dato que el
        proyecto no tiene es ``gis.dataset_unknown``, y una rejilla o un TIN no son tablas."""
        lines = _lines()
        self.contour("Curvas 1 m", lines)
        found = store.load_features(self.project, "gis_cnt_curvas_1_m")
        open_line, ring = found.geometries
        self.assertTrue(np.array_equal(open_line, lines[0].xyz))
        self.assertTrue(np.array_equal(ring, np.vstack([lines[1].xyz, lines[1].xyz[:1]])))
        self.assertEqual(found.attributes["elevation"], (801.0, 805.0))
        self.assertEqual(found.attributes["is_index"], (0, 1))
        self.assertEqual(found.attributes["closed"], (0, 1))
        with self.assertRaises(messages.GisError) as caught:
            store.load_features(self.project, "gis_cnt_nada")
        self.assertEqual(caught.exception.code, "gis.dataset_unknown")
        self.resample("MDT Norte")
        with self.assertRaises(ValueError):
            store.load_features(self.project, "gis_dtm_mdt_norte")

    def test_project_references_of_computed_and_imported(self) -> None:
        """Principio 6, RF-006-19: lo calculado y lo importado declarado en el CRS y la
        referencia vertical del proyecto están en las del proyecto; lo importado en ED50
        (EPSG:23030, sin transformar, RF-006-12) no, y la vista lo rechaza con
        ``gis.view_references_mismatch``, que dice las dos."""
        self.contour("Curvas 1 m")
        self.import_points("Taludes", crs=ED50)
        self.assertEqual(store.dataset_references(self.project, "gis_cnt_curvas_1_m"),
                         (CRS, VERTICAL))
        self.assertIsNone(store.require_project_references(self.project, "gis_cnt_curvas_1_m"))
        self.assertEqual(store.dataset_references(self.project, "gis_pts_taludes"),
                         (ED50, VERTICAL))
        with self.assertRaises(messages.GisError) as caught:
            store.require_project_references(self.project, "gis_pts_taludes")
        error = caught.exception
        self.assertEqual((error.code, error.field), ("gis.view_references_mismatch", "CRS"))
        self.assertIn("«gis_pts_taludes»: está en EPSG:23030 + EPSG:5782 y el proyecto en "
                      "EPSG:25830 + EPSG:5782", str(error))
