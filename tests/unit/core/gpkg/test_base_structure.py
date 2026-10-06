# SPDX-License-Identifier: GPL-3.0-or-later
"""Estructura GeoPackage 1.4 del proyecto (spec 002, T07; RF-002-14; ADR-0006;
formato-proyecto §3.1; plan 002 §5.2 y §6).

- ``application_id`` = 1196444487 («GPKG») y ``user_version`` = 10400 (1.4.0);
- ``gpkg_spatial_ref_sys`` con las filas −1, 0 y 4326 del estándar y la del CRS
  horizontal del proyecto con su WKT1 del catálogo;
- ``gpkg_contents``, ``gpkg_geometry_columns`` y ``gpkg_extensions``; las tablas internas,
  declaradas con la extensión ``imga_geoblender`` en alcance ``write-only`` (con
  ``read-write`` GDAL avisa al leer) y sin registrar en ``gpkg_contents``;
- capas con geometría y tablas de atributos registradas.
"""

import sqlite3
import unittest

import numpy as np

from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender

gpkg = import_geoblender("core.gpkg")
base = import_geoblender("core.gpkg.base")
georef = import_geoblender("core.georef")
errors = import_geoblender("core.errors")

CRS = georef.load_catalog().horizontal(25830)
RING = np.array(
    [
        (700_000.125, 4_400_000.250),
        (700_100.375, 4_400_000.250),
        (700_100.375, 4_400_100.001),
        (700_000.125, 4_400_000.250),
    ]
)
HOLE = np.array(
    [
        (700_010.0, 4_400_010.0),
        (700_020.0, 4_400_010.0),
        (700_020.0, 4_400_020.0),
        (700_010.0, 4_400_010.0),
    ]
)
MULTIPOLYGON = [[RING], [RING + 500.0, HOLE + 500.0]]


def _new(path: object) -> object:
    db = gpkg.GpkgConnection.open_write(path, create=True)
    with db.transaction() as conn:
        base.create_base(conn, CRS)
    return db


class BaseStructureTest(unittest.TestCase):
    def test_header_pragmas(self) -> None:
        """RF-002-14: ``application_id`` = 1196444487, ``user_version`` = 10400 y diario
        clásico."""
        with project_tmp() as tmp:
            path = tmp / "project.gpkg"
            with _new(path) as db:
                conn = db.connection
                self.assertEqual(conn.execute("PRAGMA application_id").fetchone()[0], 1196444487)
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 10400)
            self.assertEqual(gpkg.read_header(path).journal, "classic")
            self.assertEqual(path.read_bytes()[68:72], b"GPKG")

    def test_spatial_ref_sys(self) -> None:
        """RF-002-14: filas −1, 0, 4326 y la del proyecto (EPSG:25830 con el WKT1 del
        catálogo), con su organización y código."""
        with project_tmp() as tmp, _new(tmp / "p.gpkg") as db:
            rows = db.connection.execute(
                "SELECT srs_id, srs_name, organization, organization_coordsys_id, "
                "definition FROM gpkg_spatial_ref_sys ORDER BY srs_id"
            ).fetchall()
        self.assertEqual([row[0] for row in rows], [-1, 0, 4326, 25830])
        self.assertEqual(rows[0][2:4], ("NONE", -1))
        self.assertEqual(rows[1][2:4], ("NONE", 0))
        self.assertEqual(rows[2][2:4], ("EPSG", 4326))
        self.assertTrue(rows[2][4].startswith('GEOGCS["WGS 84"'))
        self.assertEqual(rows[3][1:], (CRS.name, "EPSG", 25830, CRS.wkt1))

    def test_mandatory_tables_and_columns(self) -> None:
        """RF-002-14: existen las tablas del estándar con sus columnas."""
        expected = {
            "gpkg_spatial_ref_sys": [
                "srs_name", "srs_id", "organization", "organization_coordsys_id",
                "definition", "description",
            ],
            "gpkg_contents": [
                "table_name", "data_type", "identifier", "description", "last_change",
                "min_x", "min_y", "max_x", "max_y", "srs_id",
            ],
            "gpkg_geometry_columns": [
                "table_name", "column_name", "geometry_type_name", "srs_id", "z", "m",
            ],
            "gpkg_extensions": [
                "table_name", "column_name", "extension_name", "definition", "scope",
            ],
        }
        with project_tmp() as tmp, _new(tmp / "p.gpkg") as db:
            for table, columns in expected.items():
                with self.subTest(tabla=table):
                    info = db.connection.execute(f"PRAGMA table_info({table})").fetchall()
                    self.assertEqual([row[1] for row in info], columns)
            problems = db.connection.execute("PRAGMA foreign_key_check").fetchall()
            self.assertEqual(problems, [])
            self.assertEqual(db.connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_internal_table_extension(self) -> None:
        """RF-002-14, RF-002-15 (D-5): una tabla interna se declara en ``gpkg_extensions``
        con ``imga_geoblender`` en alcance ``write-only`` y no se registra en
        ``gpkg_contents``."""
        with project_tmp() as tmp, _new(tmp / "p.gpkg") as db:
            with db.transaction() as conn:
                conn.execute("CREATE TABLE gb_prueba (fid INTEGER PRIMARY KEY AUTOINCREMENT)")
                base.register_internal_table(conn, "gb_prueba")
            row = db.connection.execute(
                "SELECT table_name, column_name, extension_name, definition, scope "
                "FROM gpkg_extensions"
            ).fetchone()
            listed = db.connection.execute(
                "SELECT count(*) FROM gpkg_contents WHERE table_name = 'gb_prueba'"
            ).fetchone()[0]
        self.assertEqual(row[:3], ("gb_prueba", None, "imga_geoblender"))
        self.assertIn("formato-proyecto.md", row[3])
        self.assertEqual(row[4], "write-only")
        self.assertEqual(listed, 0)

    def test_multipolygon_layer_round_trip(self) -> None:
        """RF-002-14: una capa ``MULTIPOLYGON`` creada con ``core.gpkg`` se registra en
        ``gpkg_contents`` y ``gpkg_geometry_columns`` y su geometría y atributos se releen
        sin pérdida, también tras cerrar y abrir."""
        columns = [
            base.ColumnDef("name", "TEXT", not_null=True, default="''"),
            base.ColumnDef("buffer_m", "DOUBLE", not_null=True, default="0"),
        ]
        with project_tmp() as tmp:
            path = tmp / "p.gpkg"
            with _new(path) as db:
                with db.transaction() as conn:
                    base.create_feature_table(
                        conn,
                        "gb_limites",
                        "MULTIPOLYGON",
                        CRS.epsg,
                        False,
                        columns,
                        identifier="Límites",
                        description="Capa de prueba",
                    )
                    blob = gpkg.encode_geometry("MULTIPOLYGON", MULTIPOLYGON, CRS.epsg, False)
                    conn.execute(
                        "INSERT INTO gb_limites (geom, name, buffer_m) VALUES (?, ?, ?)",
                        (blob, "Límite norte", 2.5),
                    )
            with gpkg.GpkgConnection.open_read(path) as db:
                conn = db.connection
                contents = conn.execute(
                    "SELECT data_type, identifier, description, srs_id, last_change "
                    "FROM gpkg_contents WHERE table_name = 'gb_limites'"
                ).fetchone()
                geometry_column = conn.execute(
                    "SELECT column_name, geometry_type_name, srs_id, z, m "
                    "FROM gpkg_geometry_columns WHERE table_name = 'gb_limites'"
                ).fetchone()
                geom, name, buffer_m = conn.execute(
                    "SELECT geom, name, buffer_m FROM gb_limites"
                ).fetchone()
        self.assertEqual(contents[:4], ("features", "Límites", "Capa de prueba", 25830))
        self.assertRegex(contents[4], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
        self.assertEqual(geometry_column, ("geom", "MULTIPOLYGON", 25830, 0, 0))
        decoded = gpkg.decode_geometry(geom)
        self.assertEqual(decoded.geometry_type, "MULTIPOLYGON")
        self.assertEqual(decoded.srs_id, 25830)
        for got, want in zip(decoded.coords, MULTIPOLYGON, strict=True):
            for ring_got, ring_want in zip(got, want, strict=True):
                self.assertEqual(ring_got.tobytes(), ring_want.tobytes())
        self.assertEqual((name, buffer_m), ("Límite norte", 2.5))

    def test_attribute_table_and_z(self) -> None:
        """RF-002-14: una tabla de atributos se registra con ``data_type`` = ``attributes``
        y sin SRS; una capa con Z declara ``z`` = 1."""
        with project_tmp() as tmp, _new(tmp / "p.gpkg") as db:
            with db.transaction() as conn:
                base.create_attribute_table(
                    conn, "gb_tabla", [base.ColumnDef("v", "INTEGER")], identifier="Tabla"
                )
                base.create_feature_table(
                    conn, "gb_puntos", "POINT", CRS.epsg, True, [], identifier="Puntos"
                )
            rows = dict(
                db.connection.execute(
                    "SELECT table_name, data_type FROM gpkg_contents"
                ).fetchall()
            )
            srs = db.connection.execute(
                "SELECT srs_id FROM gpkg_contents WHERE table_name = 'gb_tabla'"
            ).fetchone()[0]
            z = db.connection.execute(
                "SELECT z FROM gpkg_geometry_columns WHERE table_name = 'gb_puntos'"
            ).fetchone()[0]
        self.assertEqual(rows, {"gb_tabla": "attributes", "gb_puntos": "features"})
        self.assertIsNone(srs)
        self.assertEqual(z, 1)

    def test_invalid_definitions(self) -> None:
        """RF-002-14: nombres que no son identificadores simples, tipos de columna fuera
        del estándar, un tipo de geometría desconocido o un SRS que no está en
        ``gpkg_spatial_ref_sys`` se rechazan sin crear nada."""
        with project_tmp() as tmp, _new(tmp / "p.gpkg") as db:
            cases = {
                "nombre con espacio": ("gb x", "POINT", CRS.epsg, []),
                "nombre con comilla": ('gb"x', "POINT", CRS.epsg, []),
                "tipo de columna": ("gb_a", "POINT", CRS.epsg, [base.ColumnDef("v", "JSON")]),
                "columna fid": ("gb_b", "POINT", CRS.epsg, [base.ColumnDef("fid", "INTEGER")]),
                "geometría": ("gb_c", "CIRCULARSTRING", CRS.epsg, []),
                "SRS": ("gb_d", "POINT", 4258, []),
            }
            for label, (name, geometry_type, srs_id, columns) in cases.items():
                with self.subTest(label):
                    with self.assertRaises(errors.ValidationError):
                        with db.transaction() as conn:
                            base.create_feature_table(
                                conn, name, geometry_type, srs_id, False, columns,
                                identifier=label,
                            )
            count = db.connection.execute("SELECT count(*) FROM gpkg_contents").fetchone()[0]
            self.assertEqual(count, 0)
            tables = db.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'gb_%'"
            ).fetchall()
            self.assertEqual(tables, [])

    def test_create_base_twice_fails(self) -> None:
        """RF-002-14: crear la estructura sobre una base que ya la tiene es un error (no se
        mezclan dos proyectos)."""
        with project_tmp() as tmp, _new(tmp / "p.gpkg") as db:
            with self.assertRaises(sqlite3.Error):
                with db.transaction() as conn:
                    base.create_base(conn, CRS)


if __name__ == "__main__":
    unittest.main()
