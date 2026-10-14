# SPDX-License-Identifier: GPL-3.0-or-later
"""Capas de la topografía a un GeoPackage entregable (spec 006, T31; HU-006-6; RF-006-25,
RF-006-24; plan 006 §5.3.2, §5.3.4 y A18; D15).

``gis.vector.write_layers`` escribe en un GeoPackage nuevo (temporal, diario clásico
``DELETE``, una tabla por capa, inserción por lotes, índice R*Tree y renombrado) puntos,
líneas de rotura, curvas de nivel, contornos y un TIN como triángulos:

- **RF-006-25**: cada capa con el CRS del proyecto (``gpkg_spatial_ref_sys`` y
  ``gpkg_geometry_columns``), el nombre base del tipo de GeoPackage 1.4 (``POINT``,
  ``LINESTRING``, ``POLYGON``, ``MULTIPOLYGON``) con ``z = 1`` si lleva Z (D15; los contornos
  del proyecto no la llevan), la referencia vertical citada en su descripción, su extensión y
  cada coordenada **igual bit a bit** a la escrita; el TIN, un ``POLYGON`` con Z por
  triángulo (su anillo cerrado, con los vértices del TIN). Lo lee igual el lector de capas de
  la 006 (``gis.vector.read_layer``).
- Sin fichero a medias: un destino abierto por otro programa es ``gis.raster_target_locked``
  y una cancelación, ``JobCancelled``, con el destino anterior intacto y sin temporal; una
  capa mal declarada no escribe nada.
- El trabajo ``gis_export`` con ``format = "gpkg"`` (RF-006-28): las filas del proyecto tal
  como están guardadas (``StoredLayer``) y los TIN en su fichero, a ``out/export.gpkg`` con el
  hash de contenido del fichero (``core.document@1``).
- Con ``GEOBLENDER_QGIS_DIR`` (recurso ``qgis``), ``ogrinfo`` lo lista sin avisos y
  ``validate_gpkg.py`` lo da por bueno (también el R*Tree); si no, omisión ``[ENTORNO] qgis``.
- **Estilo de las curvas** (T55; RF-006-18, M4): una capa con estilo (``gis.styles``, el de
  las curvas de nivel) lo lleva en la tabla ``layer_styles`` con el esquema que escribe
  QGIS 4.2 y ``useAsDefault = 1``, y QGIS (PyQGIS sin interfaz, recurso ``qgis``) lo carga
  solo al abrir la capa y dibuja las maestras más gruesas que las intermedias.
"""

import dataclasses
import json
import os
import re
import shutil
import sqlite3
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np

from tests.support import qgis
from tests.support.package import import_geoblender
from tests.support.resources import requires

vector = import_geoblender("gis.vector")
styles = import_geoblender("gis.styles")
gis_jobs = import_geoblender("gis.jobs")
gis_tin = import_geoblender("gis.tin")
messages = import_geoblender("gis.messages")
core_gpkg = import_geoblender("core.gpkg")
gpkg_base = import_geoblender("core.gpkg.base")
georef = import_geoblender("core.georef")
builtin = import_geoblender("core.content.builtin")
readers = import_geoblender("core.content.readers")
gis_content = import_geoblender("gis.content")
encoder = import_geoblender("core.content.encoder")
protocol = import_geoblender("jobs.protocol")
job_paths = import_geoblender("jobs.paths")
worker_api = import_geoblender("jobs.worker_api")

CATALOG = georef.load_catalog()
CRS = CATALOG.horizontal(25830)
VERTICAL = CATALOG.vertical(5782)
SRS = 25830
Column = gpkg_base.ColumnDef
OPERATION_UID = "0f3c2a5e-7b1d-4c9e-8a6f-2d4b6c8e0a29"
TRIGGERS = ("insert", "update2", "update4", "update5", "update6", "update7", "delete")
# La tabla de estilos como la crea QGIS 4.2 al guardar un estilo en un GeoPackage (columnas y
# tipos, en su orden; comprobado con PyQGIS 4.2.0, T55).
QGIS_STYLE_COLUMNS = [
    ("id", "INTEGER"), ("f_table_catalog", "TEXT(256)"), ("f_table_schema", "TEXT(256)"),
    ("f_table_name", "TEXT(256)"), ("f_geometry_column", "TEXT(256)"),
    ("styleName", "TEXT(30)"), ("styleQML", "TEXT"), ("styleSLD", "TEXT"),
    ("useAsDefault", "BOOLEAN"), ("description", "TEXT"), ("owner", "TEXT(30)"),
    ("ui", "TEXT(30)"), ("update_time", "DATETIME")]
RGBA = re.compile(r"\d{1,3},\d{1,3},\d{1,3},\d{1,3}")  # «r,g,b,a» (docs/trampas.md §6)


def _same(test: unittest.TestCase, got: Any, expected: Any) -> None:
    """Las mismas coordenadas, bit a bit, con la misma estructura (arrays o listas)."""
    if isinstance(expected, list):
        test.assertIsInstance(got, list)
        test.assertEqual(len(got), len(expected))
        for inner, wanted in zip(got, expected, strict=True):
            _same(test, inner, wanted)
        return
    got = np.asarray(got)
    test.assertEqual((got.shape, got.dtype), (expected.shape, expected.dtype))
    test.assertTrue(np.array_equal(got.view(np.uint8), expected.view(np.uint8)))


def _xyz(rng: np.random.Generator, count: int) -> np.ndarray:
    """Coordenadas absolutas con todos sus decimales (float64 sin redondear)."""
    return np.column_stack([rng.uniform(700_000.0, 700_100.0, count),
                            rng.uniform(4_400_000.0, 4_400_100.0, count),
                            rng.uniform(780.0, 820.0, count)])


def _tin() -> Any:
    xy = np.array([[0.0, 0.0], [4.0, 0.0], [4.0, 4.0], [0.0, 4.0], [2.0, 2.0]])
    xy += (700_010.123456789, 4_400_020.987654321)
    z = np.array([800.123, 801.017, 802.509, 801.511, 803.253]) + 1e-9
    faces = np.array([[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]], dtype=np.int32)
    return gis_tin.Tin(np.column_stack([xy, z]), faces, np.empty((0, 2), np.int32),
                       np.zeros(5, np.uint8), triangulator="pure@1")


def _layers() -> tuple[list[Any], Any]:
    """Las cinco capas de la prueba (puntos, roturas, curvas, contornos y un TIN) y el TIN."""
    rng = np.random.default_rng(20261010)
    points = _xyz(rng, 5)
    lines = [_xyz(rng, 4), _xyz(rng, 3)]
    ring = _xyz(rng, 5)
    ring[:, 2] = 805.0
    ring = np.vstack([ring, ring[:1]])  # una curva cerrada, con su primer vértice al final
    contours = [np.column_stack([_xyz(rng, 6)[:, :2], np.full(6, 801.0)]), ring]
    outer = np.array([[700_000.5, 4_400_000.25], [700_090.125, 4_400_000.0625],
                      [700_090.0, 4_400_090.75], [700_000.0, 4_400_090.5],
                      [700_000.5, 4_400_000.25]])
    hole = np.array([[700_040.1, 4_400_040.2], [700_050.3, 4_400_040.4],
                     [700_050.5, 4_400_050.6], [700_040.1, 4_400_040.2]])
    island = np.array([[700_200.0, 4_400_200.0], [700_210.0, 4_400_200.0],
                       [700_210.0, 4_400_210.0], [700_200.0, 4_400_200.0]])
    tin = _tin()
    layers = [
        vector.LayerToWrite(
            "gis_pts_taludes", "POINT", True, list(points),
            (Column("point_id", "TEXT"), Column("code", "TEXT"), Column("source_row", "INTEGER")),
            {"point_id": ("P1", "P2", "P3", "P4", "P5"), "code": ("TN", "TN", "C1", "", "P1"),
             "source_row": (2, 3, None, 5, 6)},
            identifier="Puntos: gis_pts_taludes", description="Puntos de Geoblender"),
        vector.LayerToWrite(
            "gis_brk_taludes", "LINESTRING", True, lines,
            (Column("line_id", "TEXT"), Column("hard", "BOOLEAN"), Column("code", "TEXT")),
            {"line_id": ("C1", "P1"), "hard": (1, 0), "code": ("C1", "P1")}),
        vector.LayerToWrite(
            "gis_cnt_dron", "LINESTRING", True, contours,
            (Column("elevation", "DOUBLE"), Column("is_index", "BOOLEAN"),
             Column("closed", "BOOLEAN"), Column("length_m", "DOUBLE")),
            {"elevation": (801.0, 805.0), "is_index": (0, 1), "closed": (0, 1),
             "length_m": (12.5, 0.1 + 0.2)}, style=styles.CONTOUR_STYLE),
        vector.LayerToWrite(
            "gis_bnd_contorno", "MULTIPOLYGON", False, [[[outer, hole]], [[island]]],
            (Column("role", "TEXT"),), {"role": ("boundary", "hole")}),
        vector.tin_layer(tin, "gis_tin_dron", identifier="TIN: gis_tin_dron"),
    ]
    return layers, tin


def _rows(path: Path, sql: str, *args: Any) -> list[tuple[Any, ...]]:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


class _Folder(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="gb-vw-"))
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.target = self.folder / "capas.gpkg"

    def listing(self) -> list[str]:
        return sorted(path.name for path in self.folder.iterdir())


class WriteLayersTest(_Folder):
    def test_layers_with_z_srs_and_the_same_bits(self) -> None:
        """RF-006-25, D15: el GeoPackage entregable tiene, con el CRS del proyecto (EPSG:25830)
        y la referencia vertical en la descripción, una tabla por capa con el nombre base del
        tipo y ``z = 1`` si lleva Z (los contornos, sin ella), su extensión, sus atributos y
        cada coordenada igual bit a bit a la escrita; el TIN, un ``POLYGON`` con Z por
        triángulo con los vértices del TIN; diario clásico (``DELETE``), índice R*Tree de cada
        capa con sus disparadores, y ni temporal ni diario junto a él."""
        layers, tin = _layers()
        written = vector.write_layers(self.target, layers, CRS, VERTICAL)
        self.assertEqual(written, self.target)
        self.assertEqual(self.listing(), ["capas.gpkg"])
        self.assertEqual(core_gpkg.read_header(self.target).journal, "classic")
        self.assertEqual(_rows(self.target, "PRAGMA application_id"),
                         [(gpkg_base.APPLICATION_ID,)])
        self.assertEqual(_rows(self.target, "PRAGMA user_version"), [(gpkg_base.USER_VERSION,)])
        self.assertEqual(_rows(self.target, "SELECT organization, organization_coordsys_id FROM "
                                            "gpkg_spatial_ref_sys WHERE srs_id = ?", SRS),
                         [("EPSG", SRS)])
        columns = dict((row[0], row[1:]) for row in _rows(
            self.target, "SELECT table_name, column_name, geometry_type_name, srs_id, z, m "
                         "FROM gpkg_geometry_columns"))
        self.assertEqual(columns, {
            "gis_pts_taludes": ("geom", "POINT", SRS, 1, 0),
            "gis_brk_taludes": ("geom", "LINESTRING", SRS, 1, 0),
            "gis_cnt_dron": ("geom", "LINESTRING", SRS, 1, 0),
            "gis_bnd_contorno": ("geom", "MULTIPOLYGON", SRS, 0, 0),
            "gis_tin_dron": ("geom", "POLYGON", SRS, 1, 0),
        })
        contents = {row[0]: row[1:] for row in _rows(
            self.target, "SELECT table_name, data_type, identifier, description, srs_id, min_x, "
                         "min_y, max_x, max_y FROM gpkg_contents")}
        z_text = vector.z_description(VERTICAL)
        self.assertIn("EPSG:5782", z_text)
        self.assertEqual(contents["gis_pts_taludes"][:4],
                         ("features", "Puntos: gis_pts_taludes", f"Puntos de Geoblender; {z_text}",
                          SRS))
        self.assertEqual(contents["gis_brk_taludes"][1:3],
                         ("gis_brk_taludes", f"gis_brk_taludes; {z_text}"))
        self.assertEqual(contents["gis_bnd_contorno"][2], "gis_bnd_contorno")
        for layer in layers:
            with self.subTest(capa=layer.name):
                rows = _rows(self.target, f'SELECT fid, geom, * FROM "{layer.name}" ORDER BY fid')
                count = len(layer.geometries)
                self.assertEqual([row[0] for row in rows], list(range(1, count + 1)))
                flat = []
                for index, row in enumerate(rows):
                    geometry = core_gpkg.decode_geometry(row[1])
                    self.assertEqual((geometry.geometry_type, geometry.srs_id, geometry.has_z),
                                     (layer.geometry_type, SRS, layer.has_z))
                    _same(self, geometry.coords, _structure(layer.geometry_type,
                                                            layer.geometries[index]))
                    flat.append(np.asarray(_points(layer.geometry_type,
                                                   layer.geometries[index]))[:, :2])
                for position, column in enumerate(layer.columns):
                    self.assertEqual([row[4 + position] for row in rows],
                                     list(layer.values[column.name]), column.name)
                every = np.vstack(flat)
                self.assertEqual(contents[layer.name][4:],
                                 (*every.min(axis=0).tolist(), *every.max(axis=0).tolist()))
                rtree = f"rtree_{layer.name}_geom"
                boxes = _rows(self.target, f'SELECT id, minx, maxx, miny, maxy FROM "{rtree}" '
                                           "ORDER BY id")
                self.assertEqual([box[0] for box in boxes], [row[0] for row in rows])
                for box, points in zip(boxes, flat, strict=True):
                    self.assertTrue(box[1] <= points[:, 0].min() and points[:, 0].max() <= box[2])
                    self.assertTrue(box[3] <= points[:, 1].min() and points[:, 1].max() <= box[4])
                triggers = sorted(name.removeprefix(f"{rtree}_") for (name,) in _rows(
                    self.target, "SELECT name FROM sqlite_master WHERE type = 'trigger' AND "
                                 "tbl_name = ?", layer.name))
                self.assertEqual(triggers, sorted(TRIGGERS))
        self.assertEqual(sorted(_rows(self.target, "SELECT table_name, column_name, scope FROM "
                                                   "gpkg_extensions WHERE extension_name = ?",
                                      vector.RTREE_EXTENSION)),
                         sorted((layer.name, "geom", "write-only") for layer in layers))
        # El TIN: un triángulo por entidad, su anillo cerrado con los vértices del TIN.
        triangles = _rows(self.target, 'SELECT geom FROM "gis_tin_dron" ORDER BY fid')
        self.assertEqual(len(triangles), len(tin.faces))
        for (blob,), face in zip(triangles, tin.faces, strict=True):
            (ring,) = core_gpkg.decode_geometry(blob).coords
            _same(self, ring, tin.vertices[np.append(face, face[0])])

    def test_the_006_reader_reads_them_back(self) -> None:
        """RF-006-25, RF-006-12: el lector de capas de la 006 (sobre una copia) las lista
        importables, con su tipo, Z, el CRS EPSG:25830 del catálogo y su número de entidades,
        y lee cada coordenada bit a bit (QGIS las carga igual: ``ogrinfo`` abajo)."""
        layers, _tin_ = _layers()
        vector.write_layers(self.target, layers, CRS, VERTICAL)
        copy = vector.copy_source(self.target, self.folder / "copia")
        listed = {info.name: info for info in vector.list_layers(copy)}
        self.assertEqual(sorted(listed), sorted(layer.name for layer in layers))
        for layer in layers:
            with self.subTest(capa=layer.name):
                info = listed[layer.name]
                self.assertTrue(info.importable)
                self.assertEqual((info.geometry_type, info.z, info.m, info.declared_crs,
                                  info.features),
                                 (layer.geometry_type, int(layer.has_z), 0, CRS,
                                  len(layer.geometries)))
                features = vector.read_layer(copy, layer.name)
                for geometry, expected in zip(features.geometries, layer.geometries,
                                              strict=True):
                    _same(self, geometry.coords, _structure(layer.geometry_type, expected))

    def test_stored_rows_are_decoded_as_they_are(self) -> None:
        """RF-006-25: las filas de una tabla del proyecto tal como están guardadas
        (``StoredLayer``: cabecera GP + WKB) se escriben con las mismas coordenadas; una fila
        de otro SRS o de otro tipo es un error del programa."""
        layers, _tin_ = _layers()
        lines = layers[1]
        blobs = tuple(core_gpkg.encode_geometry("LINESTRING", xyz, SRS, True)
                      for xyz in lines.geometries)
        stored = vector.StoredLayer(lines.name, "LINESTRING", True, lines.columns, blobs,
                                    lines.values, identifier="Roturas")
        decoded = stored.decoded(SRS)
        self.assertEqual((decoded.name, decoded.identifier, decoded.columns),
                         (lines.name, "Roturas", lines.columns))
        for got, expected in zip(decoded.geometries, lines.geometries, strict=True):
            _same(self, got, expected)
        with self.assertRaises(ValueError):
            stored.decoded(23030)
        other = dataclasses.replace(stored, geometry_type="POINT")
        with self.assertRaises(ValueError):
            other.decoded(SRS)

    def test_contour_style_is_the_qgis_default(self) -> None:
        """RF-006-18, RF-006-25 (T55; M4): la capa de curvas lleva su estilo en ``layer_styles``,
        la tabla que QGIS lee por defecto, con el esquema que escribe QGIS 4.2, registrada en
        ``gpkg_contents`` como ``attributes``: una fila con la tabla y la columna de geometría
        de la capa, el catálogo y el esquema vacíos, ``useAsDefault = 1``, su nombre, su
        descripción y su QML; las capas sin estilo no tienen fila, y sin ninguna capa con
        estilo no hay tabla. El QML dibuja por reglas sobre ``is_index``: las maestras con un
        trazo más grueso que las intermedias, en milímetros, con los colores como «r,g,b,a»."""
        layers, _tin_ = _layers()
        vector.write_layers(self.target, layers, CRS, VERTICAL)
        (sql,) = _rows(self.target, "SELECT sql FROM sqlite_master WHERE name = 'layer_styles'")
        self.assertIn("PRIMARY KEY AUTOINCREMENT", sql[0])
        columns = [(row[1], row[2]) for row in _rows(self.target,
                                                     "PRAGMA table_info(layer_styles)")]
        self.assertEqual(columns, QGIS_STYLE_COLUMNS)
        self.assertEqual(_rows(self.target, "SELECT data_type, identifier FROM gpkg_contents "
                                            "WHERE table_name = 'layer_styles'"),
                         [("attributes", "layer_styles")])
        style = styles.CONTOUR_STYLE
        rows = _rows(self.target, "SELECT f_table_catalog, f_table_schema, f_table_name, "
                                  "f_geometry_column, styleName, styleQML, useAsDefault, "
                                  "description, owner FROM layer_styles")
        self.assertEqual(rows, [("", "", "gis_cnt_dron", "geom", style.name, style.qml, 1,
                                 style.description, "")])
        self.assertLessEqual(len(style.name), 30)  # styleName TEXT(30) de QGIS
        rules = _rules(style.qml)
        self.assertEqual([(rule[0], rule[1]) for rule in rules],
                         [('"is_index"', "Maestras"), ("ELSE", "Intermedias")])
        (index_width, index_color), (other_width, other_color) = (rule[2:] for rule in rules)
        self.assertGreaterEqual(index_width, 2 * other_width)
        for color in (index_color, other_color):
            self.assertRegex(color, RGBA)
        plain = [dataclasses.replace(layer, style=None) for layer in layers[:4]]
        other = self.folder / "sin_estilo.gpkg"
        vector.write_layers(other, plain, CRS, VERTICAL)
        self.assertEqual(_rows(other, "SELECT count(*) FROM sqlite_master WHERE name = "
                                      "'layer_styles'"), [(0,)])
        with self.assertRaises(TypeError):
            dataclasses.replace(layers[2], style="estilo")

    def test_badly_declared_layers_write_nothing(self) -> None:
        """RF-006-25: dos capas con el mismo nombre, valores que no son uno por entidad, un
        tipo que no es de GeoPackage o coordenadas absolutas en float32 son errores del
        programa, sin escribir nada: el destino anterior sigue igual y no queda temporal."""
        self.target.write_bytes(b"anterior")
        layers, _tin_ = _layers()
        points = layers[0]
        cases = {
            "repetida": lambda: [points, dataclasses.replace(layers[1], name=points.name)],
            "valores": lambda: [dataclasses.replace(points, values={**points.values,
                                                                   "code": ("TN",)})],
            "tipo": lambda: [dataclasses.replace(points, geometry_type="CIRCULARSTRING")],
            "float32": lambda: [dataclasses.replace(points, geometries=[
                np.asarray(xyz, np.float32) for xyz in points.geometries])],
        }
        for label, build in cases.items():
            with self.subTest(caso=label), self.assertRaises((ValueError, TypeError)):
                vector.write_layers(self.target, build(), CRS, VERTICAL)
            self.assertEqual(self.target.read_bytes(), b"anterior")
            self.assertEqual(self.listing(), ["capas.gpkg"])

    def test_locked_target_cancellation_and_temporary(self) -> None:
        """RF-006-25, RF-006-28 (spec §8): con el destino abierto por otro programa,
        ``gis.raster_target_locked`` y el anterior intacto; cancelar tras el primer lote,
        ``JobCancelled``; en los dos, sin temporal. Con ``replace=False`` queda escrito entero
        en el temporal y el destino no se toca. El avance llega hasta 1."""
        self.target.write_bytes(b"anterior")
        layers, _tin_ = _layers()
        with self.target.open("rb"), self.assertRaises(messages.GisError) as caught:
            vector.write_layers(self.target, layers, CRS, VERTICAL)
        self.assertEqual(caught.exception.code, "gis.raster_target_locked")
        self.assertEqual((self.target.read_bytes(), self.listing()), (b"anterior", ["capas.gpkg"]))
        calls = []
        with self.assertRaises(worker_api.JobCancelled):
            vector.write_layers(self.target, layers, CRS, VERTICAL,
                                cancelled=lambda: calls.append(1) or len(calls) > 1)
        self.assertEqual((self.target.read_bytes(), self.listing()), (b"anterior", ["capas.gpkg"]))
        seen: list[float] = []
        temporary = self.folder / "capas.gpkg.parcial"
        found = vector.write_layers(self.target, layers, CRS, VERTICAL, temporary=temporary,
                                    replace=False, progress=lambda done, _text: seen.append(done))
        self.assertEqual((found, self.target.read_bytes()), (temporary, b"anterior"))
        self.assertEqual(seen[-1], 1.0)
        self.assertEqual(seen, sorted(seen))
        self.assertEqual(len(_rows(temporary, 'SELECT fid FROM "gis_tin_dron"')), 4)


class ExportJobTest(_Folder):
    def test_gpkg_export_job(self) -> None:
        """RF-006-25, RF-006-28, RF-006-26: el trabajo ``gis_export`` con ``format = "gpkg"``
        recibe en ``in/layers.npz`` las filas guardadas de cada tabla y, de un TIN, su fichero
        (``in/tin_0.npz``), y deja ``out/export.gpkg`` con las mismas coordenadas y su hash de
        contenido (``core.document@1``); el resumen dice las entidades de cada capa."""
        layers, tin = _layers()
        stored = [vector.StoredLayer(
            layer.name, layer.geometry_type, layer.has_z, layer.columns,
            tuple(core_gpkg.encode_geometry(layer.geometry_type, coords, SRS, layer.has_z)
                  for coords in layer.geometries),
            layer.values, identifier=layer.identifier, style=layer.style)
            for layer in layers[:4]]
        exports = [*stored, gis_jobs.TinExport("gis_tin_dron", "tin_0", "TIN: gis_tin_dron")]
        sources = self.folder / "fuentes"
        sources.mkdir()
        gis_jobs.write_export_layers(sources / "layers.npz", exports)
        listed = gis_jobs.read_export_layers(sources / "layers.npz")
        self.assertEqual([type(item).__name__ for item in listed],
                         ["StoredLayer"] * 4 + ["TinExport"])
        self.assertEqual([getattr(item, "style", None) for item in listed],
                         [None, None, styles.CONTOUR_STYLE, None, None])
        gis_tin.save_tin(tin, sources / "tin.npz", {"crs_epsg": SRS, "vertical": "EPSG:5782",
                                                     "operation_uid": OPERATION_UID})
        params = {"format": "gpkg", "name": "capas", "crs": {"epsg": SRS},
                  "vertical": {"epsg": 5782}, "count": 30}
        request = protocol.new_request(gis_jobs.EXPORT, label="Prueba de la exportación",
                                       owner="gis", params=params, environment="blender",
                                       timeout_s=600.0, grace_s=gis_jobs.CANCEL_GRACE_S,
                                       operation_uid=OPERATION_UID)
        folder = job_paths.job_dir(self.folder / "jobs", request.job_uid).create()
        copied = {"layers": folder.copy_input(sources / "layers.npz", "layers"),
                  "tin_0": folder.copy_input(sources / "tin.npz", "tin_0")}
        protocol.write_request(folder, dataclasses.replace(request, inputs=copied))
        ctx = worker_api.WorkerContext(protocol.read_request(folder), folder,
                                       worker_api.QueueSink())
        # El envoltorio registra los lectores de su lista y da a los de gis el lector de
        # tablas (workers/_gis.py): en este proceso, sin rastro para los módulos que vienen
        # detrás (spec 006, T59: con la cola de check.py, cualquiera puede venir detrás).
        self.enterContext(mock.patch.dict(readers._REGISTRY))
        self.addCleanup(gis_content.use_table_reader, gis_content.use_table_reader(None))
        summary = import_geoblender("workers.gis_export").main(ctx)
        json.dumps(summary, allow_nan=False)
        (ref,) = ctx.outputs
        self.assertEqual((ref.path, ref.role), ("out/export.gpkg", gis_jobs.OUT_EXPORT_GPKG.role))
        written = folder.path / ref.path
        self.assertEqual(summary["layers"], [[layer.name, len(layer.geometries)]
                                             for layer in layers])
        request_text = (folder.path / job_paths.REQUEST_FILE).read_text("utf-8")
        self.assertNotIn(str(self.folder).replace("\\", "/"), request_text.replace("\\\\", "/"))
        document = builtin.DOCUMENT.request("document", {}, {"main": written},
                                            normalizer=encoder.NORMALIZER)
        for _step in readers.read_steps(builtin.DOCUMENT, document):
            pass
        self.assertEqual(gis_jobs.digest_of(summary["outputs"]["export"]["digest"]),
                         document.hasher.digest())
        for layer in layers:
            rows = _rows(written, f'SELECT geom FROM "{layer.name}" ORDER BY fid')
            for (blob,), expected in zip(rows, layer.geometries, strict=True):
                _same(self, core_gpkg.decode_geometry(blob).coords,
                      _structure(layer.geometry_type, expected))
        self.assertEqual(_rows(written, "SELECT f_table_name, styleQML, useAsDefault FROM "
                                        "layer_styles"),
                         [("gis_cnt_dron", styles.CONTOUR_STYLE.qml, 1)])


@requires(qgis.QGIS, qgis.QGIS_HINT)
class GdalOpensTheExportTest(unittest.TestCase):
    """RF-006-25: lo que dice el GDAL de QGIS del GeoPackage entregable."""

    @classmethod
    def setUpClass(cls) -> None:
        folder = Path(tempfile.mkdtemp(prefix="gb-vwq-"))
        cls.addClassCleanup(shutil.rmtree, folder, True)
        cls.layers, _tin_ = _layers()
        cls.path = folder / "capas.gpkg"
        vector.write_layers(cls.path, cls.layers, CRS, VERTICAL)
        cls.ogrinfo = qgis.run_tool("ogrinfo", "-ro", "-al", "-so", str(cls.path))
        cls.validate = qgis.run_python(qgis.validate_gpkg_script(), str(cls.path))
        cls.listing = sorted(path.name for path in folder.iterdir())

    def test_ogrinfo_without_warnings(self) -> None:
        """``ogrinfo -ro -al -so`` termina con 0, sin ninguna línea con «Warning» ni «ERROR»,
        y lista cada capa con su tipo con Z (los contornos, sin ella) y EPSG:25830; GDAL solo
        lee (sin ``-wal``, ``-shm`` ni ``.aux.xml``)."""
        output = qgis.output_of(self.ogrinfo)
        self.assertEqual(self.ogrinfo.returncode, 0, output)
        noisy = [line for line in output.splitlines()
                 if "warning" in line.lower() or "ERROR" in line]
        self.assertEqual(noisy, [], output[:4000])
        geometries = {"gis_pts_taludes": "3D Point", "gis_brk_taludes": "3D Line String",
                      "gis_cnt_dron": "3D Line String", "gis_bnd_contorno": "Multi Polygon",
                      "gis_tin_dron": "3D Polygon"}
        for name, kind in geometries.items():
            with self.subTest(capa=name):
                self.assertIn(f"Layer name: {name}\n", output.replace("\r", ""))
                self.assertIn(f"Geometry: {kind}\n", output.replace("\r", ""))
        self.assertEqual(output.count('ID["EPSG",25830]'), len(geometries))
        self.assertEqual(self.listing, ["capas.gpkg"])

    def test_validate_gpkg(self) -> None:
        """``validate_gpkg.py`` lo da por bueno (código 0, sin avisos): también el índice
        R*Tree, declarado ``write-only`` y con sus siete disparadores de GeoPackage 1.4, y la
        tabla de estilos ``layer_styles``."""
        output = qgis.output_of(self.validate)
        self.assertEqual(self.validate.returncode, 0, output)
        self.assertEqual(output, "", output)


# Con PyQGIS: la capa de curvas abierta como la abre QGIS («Añadir capa»: carga su estilo por
# defecto de la base de datos), y el trazo con que dibuja cada entidad: el símbolo de la regla
# que le toca, con la regla ELSE solo si no le toca ninguna otra (``legendKeysForFeature``, la
# lógica del dibujo; ``symbolsForFeature`` da también el de ELSE).
_PYQGIS_CODE = r"""
import json
import sys

from qgis.core import QgsExpressionContextUtils, QgsRenderContext, QgsVectorLayer

path, name = sys.argv[1], sys.argv[2]
layer = QgsVectorLayer(f"{path}|layername={name}", name, "ogr")
renderer = layer.renderer()
context = QgsRenderContext()
context.expressionContext().appendScopes(
    QgsExpressionContextUtils.globalProjectLayerScopes(layer))
children = renderer.rootRule().children()
renderer.startRender(context, layer.fields())
drawn = []
for feature in layer.getFeatures():
    context.expressionContext().setFeature(feature)
    keys = renderer.legendKeysForFeature(feature, context)
    drawn.append([feature["elevation"], bool(feature["is_index"]),
                  [[rule.symbol().width(), int(rule.symbol().outputUnit().value),
                    rule.symbol().color().name(), rule.symbol().color().alpha()]
                   for rule in children if rule.ruleKey() in keys]])
renderer.stopRender(context)
rules = [[rule.filterExpression(), rule.label()] for rule in children]
count, ids, names, descriptions, error = layer.listStylesInDatabase()
print(json.dumps({"valid": layer.isValid(), "renderer": renderer.type(), "rules": rules,
                  "drawn": drawn, "styles": names, "error": error}))
"""


@requires(qgis.QGIS, qgis.QGIS_HINT)
class QgisLoadsTheStyleTest(unittest.TestCase):
    """RF-006-18 (T55; M4): lo que hace QGIS 4.2 con el estilo de las curvas del entregable."""

    def test_qgis_draws_index_contours_thicker(self) -> None:
        """RF-006-18, RF-006-25 (T55; M4): PyQGIS sin interfaz abre la capa de curvas del
        GeoPackage entregable con su estilo por defecto (sin elegirlo): un renderizador por
        reglas, «Maestras» (``"is_index"``) e «Intermedias» (el resto), y dibuja la curva
        maestra (805 m) con un trazo más grueso que la intermedia (801 m), en milímetros y en
        el color del estilo; la base de datos solo tiene ese estilo."""
        folder = Path(tempfile.mkdtemp(prefix="gb-vws-"))
        self.addCleanup(shutil.rmtree, folder, True)
        layers, _tin_ = _layers()
        path = folder / "capas.gpkg"
        vector.write_layers(path, layers, CRS, VERTICAL)
        result = qgis.run_pyqgis(_PYQGIS_CODE, str(path), "gis_cnt_dron")
        output = qgis.output_of(result)
        self.assertEqual(result.returncode, 0, output)
        found = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertTrue(found["valid"], output)
        self.assertEqual((found["renderer"], found["rules"], found["styles"], found["error"]),
                         ("RuleRenderer", [['"is_index"', "Maestras"], ["ELSE", "Intermedias"]],
                          [styles.CONTOUR_STYLE.name], ""))
        widths = {}
        for elevation, is_index, symbols in found["drawn"]:
            ((width, unit, color, alpha),) = symbols
            self.assertEqual(unit, 0)  # Qgis.RenderUnit.Millimeters
            rule = _rules(styles.CONTOUR_STYLE.qml)[0 if is_index else 1]
            self.assertEqual(width, rule[2])
            red, green, blue, opacity = (int(value) for value in rule[3].split(","))
            self.assertEqual((color, alpha), (f"#{red:02x}{green:02x}{blue:02x}", opacity))
            widths[elevation] = width
        self.assertEqual(sorted(widths), [801.0, 805.0])
        self.assertGreater(widths[805.0], widths[801.0])
        self.assertEqual(sorted(path.name for path in folder.iterdir()), ["capas.gpkg"])


def _rules(qml: str) -> list[tuple[str, str, float, str]]:
    """Las reglas de un QML de QGIS con renderizador por reglas: su filtro, su etiqueta, el
    ancho de la línea de su símbolo (mm) y su color, en su orden."""
    root = ET.fromstring(qml)
    renderer = root.find("renderer-v2")
    assert renderer is not None and renderer.get("type") == "RuleRenderer", qml[:200]
    symbols = {}
    for symbol in renderer.iter("symbol"):
        options = {option.get("name"): option.get("value")
                   for option in symbol.iter("Option") if option.get("name")}
        assert options["line_width_unit"] == "MM", options
        symbols[symbol.get("name")] = (float(options["line_width"]), options["line_color"])
    return [(rule.get("filter"), rule.get("label"), *symbols[rule.get("symbol")])
            for rule in renderer.iter("rule")]


def _structure(geometry_type: str, coords: Any) -> Any:
    """Las coordenadas como las devuelve ``decode_geometry``: arrays y listas."""
    if geometry_type in ("POINT", "LINESTRING", "MULTIPOINT"):
        return np.asarray(coords, dtype=np.float64)
    if geometry_type == "POLYGON":
        return [np.asarray(ring, dtype=np.float64) for ring in coords]
    return [[np.asarray(ring, dtype=np.float64) for ring in polygon] for polygon in coords]


def _points(geometry_type: str, coords: Any) -> np.ndarray:
    """Todos los vértices de una geometría, en filas."""
    if geometry_type in ("POINT", "LINESTRING", "MULTIPOINT"):
        return np.asarray(coords, dtype=np.float64).reshape(-1, np.shape(coords)[-1])
    if geometry_type == "POLYGON":
        return np.vstack([np.asarray(ring) for ring in coords])
    return np.vstack([np.asarray(ring) for polygon in coords for ring in polygon])


if __name__ == "__main__":
    unittest.main()
