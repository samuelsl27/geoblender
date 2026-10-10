# SPDX-License-Identifier: GPL-3.0-or-later
"""Capas de un GeoPackage, TIN desde curvas y MDT → TIN en Blender (spec 006, T29; HU-006-2,
HU-006-5; plan 006 §5.3.5, §5.6.1 a §5.6.4 y §5.6.8).

Con el proyecto y las fuentes de ``test_ops_dtm`` (``DtmOperatorsCase``) y la cadena de
``test_ops_tin``: las órdenes ``geoblender.gis_import_vector``,
``geoblender.gis_create_tin_from_contours`` y ``geoblender.gis_convert_dtm_tin``.

- RF-006-27, RF-008-26, RF-008-11: las cinco órdenes de la T29 sustituyen a las provisionales
  de la 003 y están disponibles; habilitar registra los ``OperationDef`` de las importaciones
  y de los TIN (los de los TIN, con su recálculo) y los importadores de texto de puntos y de
  capas.
- RF-006-12, RF-008-07: las curvas de ``capas.gpkg`` (su CRS, el de la capa; su cota, la del
  campo) y su contorno (con un hueco y una isla) se importan con su entrada ``vector``.
- RF-006-16, RF-006-15, RF-006-26, D18: el TIN desde esas curvas con el contorno es el de
  ``tin_from_contours`` con ``PureTriangulator`` (en su trabajo), con el % de planos antes y
  después en el informe; la densificación tecleada es un ajuste y no se consume; las
  tolerancias, las pasadas y el umbral de planos del proyecto, sí.
- RF-006-17: el MDT importado → TIN es el de ``raster_to_tin``.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import json
import unittest

import numpy as np

from tests.blender.gis.test_ops_dtm import IMPORT, RESAMPLE, _module
from tests.blender.gis.test_ops_tin import CONVERT, IMPORT_POINTS, TIN_POINTS, TinOperatorsCase

IMPORT_VECTOR = "geoblender.gis_import_vector"
TIN_CONTOURS = "geoblender.gis_create_tin_from_contours"
T29_COMMANDS = (IMPORT_POINTS, IMPORT_VECTOR, TIN_POINTS, TIN_CONTOURS, CONVERT)
OPERATIONS = ["gis.contours", "gis.export_gpkg", "gis.export_raster", "gis.grid_to_tin",
              "gis.import_dtm", "gis.import_points", "gis.import_vector", "gis.resample",
              "gis.tin_from_contours", "gis.tin_from_points",
              "gis.tin_to_grid"]  # con las curvas de nivel de la T30 y las exportaciones de la T31
IMPORTERS = ["gis.asc", "gis.geotiff", "gis.gpkg_layer", "gis.points_text", "gis.xyz_grid"]
CONSUMED = ["gis.points.dup_xy_tol_m", "gis.points.dup_z_tol_m", "gis.tin.flat_max_passes",
            "gis.tin.max_flat_pct"]


class LayerTinTest(TinOperatorsCase):
    def test_commands_and_declarations(self) -> None:
        """RF-006-27, RF-008-26, RF-008-11 (plan §5.6.3 y §5.6.8): las cinco órdenes son las
        reales y están disponibles; habilitar registra los ``OperationDef`` de la 006 que ya
        tienen orden (las importaciones sin recálculo; los TIN y las conversiones, con él) y
        los importadores de sus cinco lectores."""
        commands = _module("bl.ui.commands")
        contract = _module("core.provenance.contract")
        for idname in (*T29_COMMANDS, IMPORT, RESAMPLE):
            with self.subTest(orden=idname):
                cls = commands.registered_class(idname)
                self.assertIsNotNone(cls)
                self.assertFalse(commands.is_provisional(cls))
                self.assertTrue(commands.is_available(idname))
        self.assertEqual(sorted(key for key in contract.OPERATIONS if key.startswith("gis.")),
                         OPERATIONS)
        self.assertEqual(sorted(key for key in contract.IMPORTERS if key.startswith("gis.")),
                         IMPORTERS)
        for op_type in OPERATIONS:
            definition = contract.OPERATIONS[op_type]
            self.assertEqual(callable(definition.recompute), definition.repeatable, op_type)

    def test_contour_layer_to_tin_with_its_boundary(self) -> None:
        """RF-006-12, RF-006-15, RF-006-16, RF-006-26, D18: las curvas ``curvas_zm`` (cota del
        campo ``cota``, CRS de la capa) y el ``contorno`` del GeoPackage quedan con su entrada;
        el TIN desde las curvas con ese contorno y la densificación tecleada (2,5 m, un ajuste)
        es el de ``tin_from_contours`` con ``PureTriangulator``, con el % de planos en el
        informe y los parámetros de resultado del proyecto consumidos."""
        project = self.open()
        store = _module("gis.store")
        gis = _module("gis")
        path = self.source("gpkg/capas.gpkg", "cartografia/capas.gpkg")
        curves = self.launch(IMPORT_VECTOR, filepath=str(path), layer="curvas_zm",
                             role="CONTOURS", elevation_field="cota", vertical="PROJECT",
                             name="Curvas")
        self.assertEqual(self.operation(curves)[:2], ("gis.import_vector", "done"))
        self.assertIn("2 curvas de nivel", self.operation(curves)[3])
        bounds = self.launch(IMPORT_VECTOR, filepath=str(path), layer="contorno",
                             role="BOUNDARY", vertical="PROJECT", name="Contorno")
        self.assertEqual(self.operation(bounds)[1], "done")
        entries = self.rows("SELECT name, kind, reader, layer, crs_h, original FROM gb_input "
                            "ORDER BY name")
        self.assertEqual(entries, [
            ("Contorno", "vector", "gis.gpkg_layer@1", "contorno", '{"epsg":25830}',
             "not_applicable"),
            ("Curvas", "vector", "gis.gpkg_layer@1", "curvas_zm", '{"epsg":25830}',
             "not_applicable")])
        uid = self.chain(TIN_CONTOURS, contours="gis_cnt_curvas", boundary="gis_bnd_contorno",
                         densify="2,5", name="Ladera")
        _type, status, _reason, message, settings, software, *_ = self.operation(uid)
        self.assertEqual((status, json.loads(software)), ("done", {"triangulator": "pure@1"}))
        self.assertEqual(json.loads(settings)["densify_m"], 2.5)
        self.assertEqual(sorted(key for (key,) in self.rows(
            "SELECT key FROM gb_operation_param WHERE operation_uid = ?", uid)), CONSUMED)
        lines = store.load_lines(project, "gis_cnt_curvas")
        polygons, holes = store.load_regions(project, "gis_bnd_contorno")
        rings = [ring for polygon in polygons for ring in polygon]
        expected, report = gis.tin_from_contours(lines, triangulator=gis.PureTriangulator(),
                                                 origin=project.origin, boundary=rings,
                                                 densify_m=2.5, name="Ladera")
        tin = self.tin_file("gis_tin_ladera")
        for array in ("vertices", "faces", "vertex_source"):
            self.assertTrue(np.array_equal(getattr(tin, array), getattr(expected, array)),
                            array)
        self.assertIn("planos", message)
        self.assertIn("pure@1", message)
        del report

    def test_ed50_contours_give_a_tin_in_the_project_crs(self) -> None:
        """HU-006-5, RF-006-05, RF-006-16: las curvas declaradas en ED50 (EPSG:23030) se
        importan en su CRS y el TIN desde ellas queda en el del proyecto, transformadas con una
        de precisión conocida (ED50 → ETRS89 con la rejilla del IGN, 0,2 m), que dice el
        informe."""
        project = self.open()
        store = _module("gis.store")
        gis = _module("gis")
        path = self.source("gpkg/capas.gpkg", "plano_antiguo/capas.gpkg")
        self.launch(IMPORT_VECTOR, filepath=str(path), layer="curvas_zm", role="CONTOURS",
                    elevation_field="cota", crs="EPSG:23030", vertical="PROJECT",
                    name="Curvas ED50")
        self.assertEqual(self.rows("SELECT crs_h FROM gb_input"), [('{"epsg":23030}',)])
        uid = self.chain(TIN_CONTOURS, contours="gis_cnt_curvas_ed50", name="ED50")
        message = self.operation(uid)[3]
        self.assertIn("«gis_cnt_curvas_ed50» transformado de EPSG:23030", message)
        self.assertIn("ED50 to ETRS89 (12)", message)
        shifted = [gis.Breakline(line.line_id, line.xyz + np.array([-110.0, -207.0, 0.0]))
                   for line in store.load_lines(project, "gis_cnt_curvas_ed50")]
        expected, _report = gis.tin_from_contours(shifted, triangulator=gis.PureTriangulator(),
                                                  origin=project.origin, name="ED50")
        self.assertTrue(np.array_equal(self.tin_file("gis_tin_ed50").vertices,
                                       expected.vertices))

    def test_dtm_to_tin(self) -> None:
        """RF-006-17, RF-006-26: el MDT importado (en las referencias del proyecto) → TIN es
        el de ``raster_to_tin`` (dos triángulos por cuadro de centros con dato), sin
        bibliotecas en ``software``."""
        project = self.open()
        self.import_dtm(self.source("geotiff/f64_strip.tif"), "MDT dron")
        uid = self.launch(CONVERT, direction="DTM_TO_TIN", source="gis_src_mdt_dron",
                          name="MDT dron")
        _type, status, _reason, message, _settings, software, *_ = self.operation(uid)
        self.assertEqual((_type, status, software), ("gis.grid_to_tin", "done", "{}"))
        expected = _module("gis.tin").raster_to_tin(self.stored("gis_src_mdt_dron"),
                                                    name="MDT dron")
        tin = self.tin_file("gis_tin_mdt_dron")
        self.assertTrue(np.array_equal(tin.vertices, expected.vertices))
        self.assertTrue(np.array_equal(tin.faces, expected.faces))
        self.assertIn("TIN «MDT dron»", message)
        del project


if __name__ == "__main__":
    unittest.main()
