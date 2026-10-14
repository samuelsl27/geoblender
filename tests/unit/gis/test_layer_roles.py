# SPDX-License-Identifier: GPL-3.0-or-later
"""El papel de una capa importada y lo importado, leído para un TIN (spec 006, T29;
RF-006-12, RF-006-15, RF-006-16; plan 006 §5.2.3 y §5.6.3).

- ``gis.contours.contours_from_features``: las curvas de nivel de una capa (cada LineString o
  cada parte de un MultiLineString), con sus coordenadas tal como llegan (la M, descartada);
  la cota, la del campo de cota o la del primer vértice; una curva cerrada (el primer vértice
  repetido al final), cerrada y sin repetirlo (``gis.store`` lo vuelve a escribir); una línea
  sin Z toma la cota del campo y, sin él, se rechaza: una curva sin cota no se acepta.
- ``gis.points.polygons_from_features``: los polígonos de un contorno (cada Polygon o
  MultiPolygon, sus anillos en planta tal como llegan); otra geometría se rechaza.
- ``gis.store.load_points``, ``load_lines`` y ``load_regions``: lo importado al proyecto
  (puntos, líneas de rotura, curvas y contornos), leído como lo usa un TIN, con las
  coordenadas bit a bit.
"""

from __future__ import annotations

import shutil
import unittest
from typing import Any

import numpy as np

from tests.support.package import import_geoblender
from tests.unit.gis.test_store import CRS, ImportCase

contours_mod = import_geoblender("gis.contours")
points_mod = import_geoblender("gis.points")
vector_mod = import_geoblender("gis.vector")
store = import_geoblender("gis.store")
provenance = import_geoblender("gis.provenance")
gis_content = import_geoblender("gis.content")
wkb = import_geoblender("core.gpkg.wkb")
reports = import_geoblender("gis.reports")

LAYER = vector_mod.LayerInfo(
    file="capas.gpkg", name="curvas", identifier="curvas", geometry_type="GEOMETRY",
    geometry_column="geom", fid_column="fid", z=2, m=0, srs_id=25830, srs="EPSG:25830",
    declared_crs=CRS, features=0, fields=(("cota", "REAL"),))


def _features(*items: tuple[str, bool, Any, Any]) -> Any:
    """Un ``FeatureSet`` con las entidades ``(tipo, con Z, coordenadas, cota)``."""
    geometries = tuple(wkb.Geometry(kind, 25830, has_z, coords, None)
                       for kind, has_z, coords, _ in items)
    count = len(items)
    report = reports.TopoReport(source="capas.gpkg ▸ curvas", read=count)
    return vector_mod.FeatureSet(LAYER, tuple(range(1, count + 1)), geometries,
                                 {"cota": tuple(item[3] for item in items)}, report)


class ContoursFromFeaturesTest(unittest.TestCase):
    def test_contour_layer_keeps_its_coordinates(self) -> None:
        """RF-006-12: las curvas ``curvas_zm`` de ``capas.gpkg`` (LineString ZM de 806 y
        816 m) llegan con sus coordenadas bit a bit (la M descartada), su cota del campo
        ``cota`` y abiertas; sin campo, la del primer vértice."""
        tmp = self.enterContext(_Temp())
        copy = vector_mod.copy_source(_Temp.DATA / "gpkg" / "capas.gpkg", tmp.path)
        features = vector_mod.read_layer(copy, "curvas_zm")
        lines, report = contours_mod.contours_from_features(features, elevation_field="cota")
        self.assertEqual([(line.elevation, line.is_index, line.closed) for line in lines],
                         [(806.0, False, False), (816.0, False, False)])
        for line, geometry in zip(lines, features.geometries, strict=True):
            self.assertTrue(np.array_equal(line.xyz, geometry.coords))
        self.assertEqual((report.read, report.lines, report.rejected), (2, 2, ()))
        again, _report = contours_mod.contours_from_features(features)
        self.assertEqual([line.elevation for line in again], [806.0, 816.0])

    def test_closed_lines_and_lines_without_elevation(self) -> None:
        """RF-006-12: una curva cerrada queda cerrada sin el vértice repetido; una LineString
        2D toma la cota del campo; sin campo, o con un campo vacío, se rechaza con su número
        («sin cota»), y un punto, por no ser una línea."""
        ring = np.array([[700000.0, 4400000.0, 810.0], [700010.0, 4400000.0, 810.0],
                         [700010.0, 4400010.0, 810.0], [700000.0, 4400000.0, 810.0]])
        flat = np.array([[700000.5, 4400020.25], [700030.75, 4400020.5]])
        multi = [np.array([[700040.0, 4400000.0, 820.0], [700050.0, 4400000.0, 820.0]]),
                 np.array([[700040.0, 4400005.0, 820.0], [700050.0, 4400005.0, 820.0]])]
        features = _features(("LINESTRING", True, ring, 810.0),
                             ("LINESTRING", False, flat, 815.5),
                             ("MULTILINESTRING", True, multi, None),
                             ("LINESTRING", False, flat, None),
                             ("POINT", True, np.array([700000.0, 4400000.0, 800.0]), 800.0))
        lines, report = contours_mod.contours_from_features(features, elevation_field="cota")
        self.assertEqual([(line.closed, line.elevation, len(line.xyz)) for line in lines],
                         [(True, 810.0, 3), (False, 815.5, 2), (False, 820.0, 2),
                          (False, 820.0, 2)])
        self.assertTrue(np.array_equal(lines[0].xyz, ring[:-1]))
        self.assertTrue(np.array_equal(lines[1].xyz[:, :2], flat))
        self.assertTrue((lines[1].xyz[:, 2] == 815.5).all())
        self.assertTrue(np.array_equal(lines[2].xyz, multi[0]))
        self.assertEqual([(item.row, item.code) for item in report.rejected],
                         [(4, "gis.feature_without_z"), (5, "gis.feature_role_mismatch")])
        self.assertIn("sin cota", report.rejected[0].reason)
        _lines, report = contours_mod.contours_from_features(features)
        self.assertEqual([item.row for item in report.rejected], [2, 4, 5])


class PolygonsFromFeaturesTest(unittest.TestCase):
    def test_boundary_layer_keeps_its_rings(self) -> None:
        """RF-006-12, RF-006-15: el contorno ``contorno`` de ``capas.gpkg`` (un MultiPolygon
        2D con un hueco y una isla) llega con sus anillos bit a bit; un punto se rechaza."""
        tmp = self.enterContext(_Temp())
        copy = vector_mod.copy_source(_Temp.DATA / "gpkg" / "capas.gpkg", tmp.path)
        features = vector_mod.read_layer(copy, "contorno")
        polygons, report = points_mod.polygons_from_features(features)
        self.assertEqual(len(polygons), 1)
        (feature,) = polygons
        self.assertEqual([len(polygon) for polygon in feature], [2, 1])
        expected = features.geometries[0].coords
        for polygon, rings in zip(feature, expected, strict=True):
            for got, ring in zip(polygon, rings, strict=True):
                self.assertTrue(np.array_equal(got, ring))
        self.assertEqual(report.rejected, ())
        mixed = _features(("POINT", True, np.array([700000.0, 4400000.0, 1.0]), None))
        polygons, report = points_mod.polygons_from_features(mixed)
        self.assertEqual((polygons, [item.code for item in report.rejected]),
                         ([], ["gis.feature_role_mismatch"]))


class LoadImportedTest(ImportCase):
    def test_imported_points_lines_and_boundaries_load_for_a_tin(self) -> None:
        """RF-006-12, RF-006-13, RF-006-15: lo importado (puntos y líneas de rotura de un
        texto, curvas y un contorno de un GeoPackage) se lee del proyecto como lo usa un TIN:
        un ``PointSet`` con su identificador, su código y su fila; líneas duras (las curvas,
        cerradas con su primer vértice repetido) y el contorno con su hueco, todo bit a
        bit."""
        points, lines, _report = _taludes(self.sources / "taludes.csv")
        spec = self.source_spec(gis_content.POINTS_TEXT, "Taludes", "taludes.csv",
                                settings=_POINT_SETTINGS)
        with store.ResultWriter(self.project, self.begin(provenance.IMPORT_POINTS)) as out:
            out.declare_input(spec)
            out.points("Taludes", points)
            out.breaklines("Taludes", lines)
            out.commit(message="Taludes")
        copy = vector_mod.copy_source(self.sources / "capas.gpkg", self.tmp / "copia")
        boundary = vector_mod.read_layer(copy, "contorno")
        ring = np.array([[700000.0, 4400000.0, 810.0], [700010.0, 4400000.0, 810.0],
                         [700010.0, 4400010.0, 810.0]])
        closed = contours_mod.ContourLine(ring, 810.0, False, True)
        for name, layer, role, write in (
                ("Contorno", "contorno", "boundary",
                 lambda out: out.boundary("Contorno", boundary.geometries)),
                ("Curvas", "curvas_zm", "contours",
                 lambda out: out.contours("Curvas", [closed]))):
            spec = self.source_spec(gis_content.GPKG_LAYER, name, "capas.gpkg",
                                    settings={"layer": layer, "role": role})
            with store.ResultWriter(self.project,
                                    self.begin(provenance.IMPORT_VECTOR)) as out:
                out.declare_input(spec)
                write(out)
                out.commit(message=name)
        got = store.load_points(self.project, "gis_pts_taludes")
        self.assertTrue(np.array_equal(got.xyz, points.xyz))
        self.assertEqual((got.point_ids, got.codes, got.source_rows),
                         (points.point_ids, points.codes, points.source_rows))
        found = store.load_lines(self.project, "gis_brk_taludes")
        self.assertEqual([(line.line_id, line.hard, line.code) for line in found],
                         [(line.line_id, True, line.code) for line in lines])
        for got_line, line in zip(found, lines, strict=True):
            self.assertTrue(np.array_equal(got_line.xyz, line.xyz))
        (curve,) = store.load_lines(self.project, "gis_cnt_curvas")
        self.assertTrue(curve.hard)
        self.assertTrue(np.array_equal(curve.xyz, np.vstack([ring, ring[:1]])))
        polygons, holes = store.load_regions(self.project, "gis_bnd_contorno")
        self.assertEqual(holes, [])
        expected = boundary.geometries[0].coords
        self.assertEqual([len(polygon) for polygon in polygons], [2, 1])
        for polygon, rings in zip(polygons, expected, strict=True):
            for got_ring, source_ring in zip(polygon, rings, strict=True):
                self.assertTrue(np.array_equal(got_ring, source_ring))
        with self.assertRaises(ValueError):
            store.load_points(self.project, "gis_brk_taludes")


_POINT_SETTINGS = {"encoding": "utf-8", "separator": ";", "decimal": ",", "header_row": 0,
                   "columns": {"point_id": 0, "x": 1, "y": 2, "z": 3, "code": 4, "line": 5},
                   "line_kind": "hard"}


def _taludes(path: Any) -> tuple[Any, Any, Any]:
    csv_tables = import_geoblender("interop.csv_tables")
    table = csv_tables.read_table(path, encoding="utf-8", separator=";", header_row=0)
    mapping = points_mod.ColumnMapping(x=1, y=2, z=3, point_id=0, code=4, line=5)
    return points_mod.points_from_rows(table.columns, table.rows, mapping, ",",
                                       source="Taludes", row_numbers=table.lines)


class _Temp:
    """Una carpeta temporal de ruta corta (se borra al salir)."""

    from tests.support.repo import ROOT as _ROOT

    DATA = _ROOT / "tests" / "data" / "gis"

    def __enter__(self) -> _Temp:
        import tempfile
        from pathlib import Path

        self.path = Path(tempfile.mkdtemp(prefix="gb29-"))
        return self

    def __exit__(self, *_exc: object) -> None:
        shutil.rmtree(self.path, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
