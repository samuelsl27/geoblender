# SPDX-License-Identifier: GPL-3.0-or-later
"""Exportar capas a GeoPackage en Blender (spec 006, T31; HU-006-6; plan 006 §5.3.5, §5.6.4 y
§5.6.6; D21).

Con el proyecto, las fuentes y la cadena del TIN de ``test_ops_tin`` (``TinOperatorsCase``):
la orden ``geoblender.gis_export_gpkg`` (Topografía ▸ Exportar ▸ Capas a GeoPackage…), con sus
filas ``GEOBLENDER_PG_gis_export_item`` (el dato y si se exporta): la operación
``gis.export_gpkg``, que consume cada capa elegida, con su trabajo ``gis_export``.

- RF-006-25, RF-008-51: los puntos y las líneas de rotura de un CSV, el TIN que sale de ellos
  (como triángulos), sus curvas de nivel y un contorno de una capa quedan en un GeoPackage con
  el CRS del proyecto, ``z = 1`` en las capas con Z y diario clásico, cada coordenada igual
  bit a bit a la guardada en el proyecto; dentro de ``exports/`` es un dato ``exports``
  (documento, sin seguimiento) con su hash, y la operación consume cada capa elegida (no la
  que no se marcó); fuera, sin salida registrada (D21) y sin rutas en los ajustes.
- Sin ninguna capa elegida, no empieza nada.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import json
import unittest
from pathlib import Path

import numpy as np

from tests.blender.gis.test_ops_dtm import _module
from tests.blender.gis.test_ops_tin import TIN_POINTS, TinOperatorsCase

EXPORT_GPKG = "geoblender.gis_export_gpkg"
CONTOURS = "geoblender.gis_create_contours"
IMPORT_VECTOR = "geoblender.gis_import_vector"
LAYERS = ["gis_pts_taludes", "gis_brk_taludes", "gis_tin_taludes", "gis_cnt_taludes",
          "gis_bnd_contorno"]
TYPES = {"gis_pts_taludes": ("POINT", 1), "gis_brk_taludes": ("LINESTRING", 1),
         "gis_tin_taludes": ("POLYGON", 1), "gis_cnt_taludes": ("LINESTRING", 1),
         "gis_bnd_contorno": ("MULTIPOLYGON", 0)}


def _same(test: unittest.TestCase, got: object, expected: object) -> None:
    if isinstance(expected, list):
        test.assertEqual(len(got), len(expected))
        for inner, wanted in zip(got, expected, strict=True):
            _same(test, inner, wanted)
        return
    got, expected = np.asarray(got), np.asarray(expected)
    test.assertEqual((got.shape, got.dtype), (expected.shape, expected.dtype))
    test.assertTrue(np.array_equal(got.view(np.uint8), expected.view(np.uint8)))


class ExportGpkgTest(TinOperatorsCase):
    def items(self, *names: str, skipped: str = "") -> list[dict[str, object]]:
        rows = [{"name": name, "selected": True} for name in names]
        if skipped:
            rows.append({"name": skipped, "selected": False})
        return rows

    def test_layers_to_geopackage(self) -> None:
        """RF-006-25, RF-008-51, D21: los cinco datos (puntos, roturas, TIN, curvas y
        contorno) a ``exports/capas.gpkg``: cada capa con su tipo base, Z y EPSG:25830, sus
        coordenadas iguales bit a bit a las del proyecto (el TIN, un triángulo por entidad),
        diario clásico; dato ``exports`` con su hash y la operación consume las cinco. Fuera
        del proyecto, solo la capa marcada y sin salida registrada; sin capas, nada."""
        project = self.open()
        root = Path(project.root)
        vector = _module("gis.vector")
        store = _module("gis.store")
        gpkg = _module("core.gpkg")
        self.import_csv("points/taludes.csv", "Taludes")
        self.chain(TIN_POINTS, points="gis_pts_taludes", breaklines="gis_brk_taludes",
                   name="Taludes")
        self.launch(CONTOURS, source="gis_tin_taludes", interval="1", name="Taludes")
        path = self.source("gpkg/capas.gpkg", "cartografia/capas.gpkg")
        self.launch(IMPORT_VECTOR, filepath=str(path), layer="contorno", role="BOUNDARY",
                    vertical="PROJECT", name="Contorno")
        self.ps.take_notices()

        target = root / "exports" / "capas.gpkg"
        uid = self.launch(EXPORT_GPKG, filepath=str(target),
                          items=self.items(*LAYERS))
        op_type, status, _reason, message, settings, *_ = self.operation(uid)
        self.assertEqual((op_type, status), ("gis.export_gpkg", "done"))
        self.assertEqual(json.loads(settings), {"layers": LAYERS, "file": "capas.gpkg",
                                                "in_exports": True})
        consumed = {name for (name,) in self.rows(
            "SELECT d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid"
            " WHERE io.operation_uid = ? AND io.direction = 'in' AND io.role = 'exported'", uid)}
        self.assertEqual(consumed, set(LAYERS))
        self.assertEqual(self.rows("SELECT name, kind, locator, reader, tracked, operation_uid "
                                   "FROM gb_dataset WHERE store = 'exports'"),
                         [("gis_exp_capas_gpkg", "document", "exports/capas.gpkg",
                           "core.document@1", 0, uid)])
        self.assertIn("GeoPackage «capas.gpkg» exportado con 5 capas", message)
        self.assertEqual(gpkg.read_header(target).journal, "classic")

        copy = vector.copy_source(target, self.tmp / "lectura")
        listed = {info.name: (info.geometry_type, info.z, info.declared_crs.epsg, info.features)
                  for info in vector.list_layers(copy)}
        tin = store.load_tin(project, "gis_tin_taludes")
        expected = {name: store.export_layer(project, name).decoded(25830)
                    for name in LAYERS if name != "gis_tin_taludes"}
        expected["gis_tin_taludes"] = vector.tin_layer(tin, "gis_tin_taludes")
        self.assertEqual(listed, {name: (*TYPES[name], 25830, len(expected[name].geometries))
                                  for name in LAYERS})
        for name in LAYERS:
            with self.subTest(capa=name):
                features = vector.read_layer(copy, name)
                for geometry, wanted in zip(features.geometries, expected[name].geometries,
                                            strict=True):
                    _same(self, geometry.coords, wanted if not isinstance(wanted, tuple)
                          else list(wanted))

        outside = self.tmp / "cliente" / "capas.gpkg"
        outside.parent.mkdir()
        uid = self.launch(EXPORT_GPKG, filepath=str(outside),
                          items=self.items("gis_cnt_taludes", skipped="gis_pts_taludes"))
        _type, status, _reason, _message, settings, *_ = self.operation(uid)
        self.assertEqual((status, json.loads(settings)),
                         ("done", {"layers": ["gis_cnt_taludes"], "file": "capas.gpkg",
                                   "in_exports": False}))
        self.assertEqual(self.rows("SELECT role FROM gb_operation_io WHERE operation_uid = ? "
                                   "AND direction = 'in'", uid), [("exported",)])
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation_io WHERE "
                                   "operation_uid = ? AND direction = 'out'", uid), [(0,)])
        self.assertEqual(sorted(path.name for path in outside.parent.iterdir()), ["capas.gpkg"])

        before = self.counts()
        with self.assertRaises(RuntimeError) as caught:
            self.run_op(EXPORT_GPKG, filepath=str(self.tmp / "cliente" / "nada.gpkg"),
                        items=self.items(skipped="gis_cnt_taludes"))
        self.assertIn("Elija al menos una capa", str(caught.exception))
        self.assertEqual(self.counts(), before)


if __name__ == "__main__":
    unittest.main()
