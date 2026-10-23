# SPDX-License-Identifier: GPL-3.0-or-later
"""Protección de las tablas internas del esquema 1 (spec 002, T08; RF-002-15; D-5;
plan 002 §5.2).

QGIS 4.2 lista todas las tablas del GeoPackage: las internas (``gb_project``, ``gb_event``
y ``gb_schema_migration``) no se pueden ocultar, así que las protegen disparadores que
solo deja pasar la conexión de Geoblender (la función SQL ``gb_writer()``). En una
conexión ajena la función no existe y la sentencia ni se prepara. Además, ``gb_event`` y
``gb_schema_migration`` son de solo inserción, ``gb_project`` tiene una sola fila y su
identidad y su CRS no cambian nunca. Lo demás del GeoPackage (las capas de dominio) sigue
admitiendo ``ALTER TABLE`` desde cualquier programa.
"""

import sqlite3
import unittest
from pathlib import Path

from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender

gpkg = import_geoblender("core.gpkg")
base = import_geoblender("core.gpkg.base")
schema = import_geoblender("core.project.schema")
georef = import_geoblender("core.georef")

CATALOG = georef.load_catalog()
CRS = CATALOG.horizontal(25830)
VCRS = CATALOG.vertical(5782)
NOW = "2026-10-05T08:12:44.000Z"
INTERNAL = ("gb_project", "gb_event", "gb_schema_migration")

PROJECT_ROW = {
    "uid": "00000000-0000-4000-8000-0000000000aa",
    "name": "Cantera Prueba",
    "schema_version": 1,
    "min_reader_schema": 1,
    "created_with": "0.1.0",
    "last_written_with": "0.1.0",
    "crs_epsg": CRS.epsg,
    "crs_name": CRS.name,
    "crs_wkt": CRS.wkt2,
    "vcrs_epsg": VCRS.epsg,
    "vcrs_name": VCRS.name,
    "vcrs_wkt": VCRS.wkt2,
    "origin_x": 700_000,
    "origin_y": 4_400_000,
    "origin_z": 0,
    "grid_step_m": 1.0,
    "window_xmin": 699_500.0,
    "window_ymin": 4_399_500.0,
    "window_xmax": 700_501.0,
    "window_ymax": 4_400_501.0,
    "created_at": NOW,
    "modified_at": NOW,
}


def _insert_project(conn: sqlite3.Connection, **changes: object) -> None:
    row = {**PROJECT_ROW, **changes}
    names = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    conn.execute(f"INSERT INTO gb_project ({names}) VALUES ({marks})", tuple(row.values()))


def _new_project_db(path: Path) -> None:
    """Un GeoPackage con el esquema 1 y una fila en cada tabla interna."""
    with gpkg.GpkgConnection.open_write(path, create=True) as db:
        with db.transaction() as conn:
            base.create_base(conn, CRS)
            schema.create_schema(conn)
            _insert_project(conn)
            conn.execute(
                "INSERT INTO gb_event (at, user_host, kind, message) VALUES (?, ?, ?, ?)",
                (NOW, "prueba@PC-PRUEBA-A", "create", "Proyecto creado"),
            )
            conn.execute(
                "INSERT INTO gb_schema_migration (from_version, to_version, applied_at, "
                "applied_with, backup_dir, user_host) VALUES (0, 1, ?, '0.1.0', "
                "'p.gbproj.respaldo-esquema-0', 'prueba@PC-PRUEBA-A')",
                (NOW,),
            )


def _dump(path: Path) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        return list(conn.iterdump())
    finally:
        conn.close()


FOREIGN_WRITES = {
    "gb_project": (
        "INSERT INTO gb_project (uid, name) VALUES ('x', 'y')",
        "UPDATE gb_project SET name = 'Otro'",
        "DELETE FROM gb_project",
    ),
    "gb_event": (
        "INSERT INTO gb_event (at, user_host, kind, message) VALUES ('t', 'u', 'k', 'm')",
        "UPDATE gb_event SET message = 'cambiado'",
        "DELETE FROM gb_event",
    ),
    "gb_schema_migration": (
        "INSERT INTO gb_schema_migration (from_version, to_version, applied_at, "
        "applied_with, backup_dir, user_host) VALUES (1, 2, 't', 'v', 'b', 'u')",
        "UPDATE gb_schema_migration SET to_version = 9",
        "DELETE FROM gb_schema_migration",
    ),
}


class ForeignConnectionTest(unittest.TestCase):
    def test_foreign_writes_fail(self) -> None:
        """RF-002-15: desde una conexión sin ``gb_writer()`` (QGIS, GDAL), INSERT, UPDATE
        y DELETE en las tres tablas internas fallan y el volcado SQL no cambia."""
        with project_tmp() as tmp:
            path = tmp / "project.gpkg"
            _new_project_db(path)
            before = _dump(path)
            foreign = sqlite3.connect(path, isolation_level=None)
            try:
                for table, statements in FOREIGN_WRITES.items():
                    for sql in statements:
                        with self.subTest(tabla=table, orden=sql.split()[0]):
                            with self.assertRaises(sqlite3.Error):
                                foreign.execute(sql)
            finally:
                foreign.close()
            self.assertEqual(_dump(path), before)

    def test_foreign_reads_and_other_tables_work(self) -> None:
        """RF-002-15: desde una conexión ajena las tablas internas se leen, y una capa de
        dominio admite filas nuevas y ``ALTER TABLE`` (añadir, renombrar y quitar
        columnas, renombrar y borrar la tabla)."""
        with project_tmp() as tmp:
            path = tmp / "project.gpkg"
            _new_project_db(path)
            foreign = sqlite3.connect(path, isolation_level=None)
            try:
                self.assertEqual(
                    foreign.execute("SELECT name FROM gb_project").fetchone()[0],
                    "Cantera Prueba",
                )
                self.assertEqual(foreign.execute("SELECT count(*) FROM gb_event").fetchone()[0], 1)
                foreign.execute("CREATE TABLE capa (fid INTEGER PRIMARY KEY, a TEXT)")
                for sql in (
                    "INSERT INTO capa (a) VALUES ('x')",
                    "ALTER TABLE capa ADD COLUMN b TEXT",
                    "ALTER TABLE capa RENAME COLUMN a TO a2",
                    "ALTER TABLE capa DROP COLUMN b",
                    "ALTER TABLE capa RENAME TO capa2",
                    "DROP TABLE capa2",
                ):
                    with self.subTest(sql):
                        foreign.execute(sql)
            finally:
                foreign.close()


class GeoblenderConnectionTest(unittest.TestCase):
    def test_append_only_tables(self) -> None:
        """RF-002-15: también desde Geoblender, ``gb_event`` y ``gb_schema_migration`` son
        de solo inserción: UPDATE y DELETE fallan; INSERT, no."""
        with project_tmp() as tmp:
            path = tmp / "project.gpkg"
            _new_project_db(path)
            with gpkg.GpkgConnection.open_write(path) as db:
                for sql in (
                    "UPDATE gb_event SET message = 'otro'",
                    "DELETE FROM gb_event",
                    "UPDATE gb_schema_migration SET to_version = 9",
                    "DELETE FROM gb_schema_migration",
                ):
                    with self.subTest(sql):
                        with self.assertRaises(sqlite3.IntegrityError) as caught:
                            with db.transaction() as conn:
                                conn.execute(sql)
                        self.assertIn("solo", str(caught.exception))
                with db.transaction() as conn:
                    conn.execute(
                        "INSERT INTO gb_event (at, user_host, kind, message) "
                        "VALUES (?, 'u@h', 'open', 'Abierto')",
                        (NOW,),
                    )
                count = db.connection.execute("SELECT count(*) FROM gb_event").fetchone()[0]
            self.assertEqual(count, 2)

    def test_project_identity_and_single_row(self) -> None:
        """RF-002-15: desde Geoblender, cambiar ``uid``, ``created_with`` o el CRS
        (horizontal o vertical) de ``gb_project`` falla, una segunda fila falla y se
        pueden cambiar el nombre, la ventana y el origen."""
        with project_tmp() as tmp:
            path = tmp / "project.gpkg"
            _new_project_db(path)
            with gpkg.GpkgConnection.open_write(path) as db:
                for sql in (
                    "UPDATE gb_project SET uid = 'otro'",
                    "UPDATE gb_project SET created_with = '9.9.9'",
                    "UPDATE gb_project SET crs_epsg = 25829",
                    "UPDATE gb_project SET crs_wkt = 'PROJCRS[]'",
                    "UPDATE gb_project SET vcrs_epsg = 9392",
                    "UPDATE gb_project SET vcrs_wkt = 'VERTCRS[]'",
                ):
                    with self.subTest(sql):
                        with self.assertRaises(sqlite3.IntegrityError) as caught:
                            with db.transaction() as conn:
                                conn.execute(sql)
                        self.assertIn("no cambian", str(caught.exception))
                with self.assertRaises(sqlite3.IntegrityError) as caught:
                    with db.transaction() as conn:
                        _insert_project(conn, uid="00000000-0000-4000-8000-0000000000bb")
                self.assertIn("una", str(caught.exception))
                with db.transaction() as conn:
                    conn.execute(
                        "UPDATE gb_project SET name = 'Nuevo', origin_x = 700100, "
                        "window_xmax = 700601.0, crs_epsg = crs_epsg"
                    )
                row = db.connection.execute(
                    "SELECT name, origin_x, crs_epsg, count(*) FROM gb_project"
                ).fetchone()
            self.assertEqual(row, ("Nuevo", 700_100, 25830, 1))

    def test_check_constraints(self) -> None:
        """RF-002-03, RF-002-24: el esquema rechaza un origen que no es múltiplo de 100, un
        Z0 fuera de rango, un paso no válido, una ventana invertida y un CRS vertical local
        sin descripción."""
        bad_rows = {
            "X0": {"origin_x": 700_250},
            "Z0": {"origin_z": 20_000},
            "paso": {"grid_step_m": 0.3},
            "ventana": {"window_xmin": 701_000.0},
            "vertical local sin nota": {"vcrs_epsg": None, "vcrs_wkt": None},
            "vertical con nota": {"vcrs_note": "algo"},
        }
        with project_tmp() as tmp:
            for label, changes in bad_rows.items():
                with self.subTest(label):
                    path = tmp / f"{len(list(tmp.iterdir()))}.gpkg"
                    with gpkg.GpkgConnection.open_write(path, create=True) as db:
                        with db.transaction() as conn:
                            base.create_base(conn, CRS)
                            schema.create_schema(conn)
                        with self.assertRaises(sqlite3.IntegrityError):
                            with db.transaction() as conn:
                                _insert_project(conn, **changes)


class StructureTest(unittest.TestCase):
    def test_schema_constants_and_registration(self) -> None:
        """RF-002-14, RF-002-15: ``min_reader_schema`` 1 (el esquema es el 2 desde la spec
        008, que añade las tablas de la procedencia: sus pruebas, en
        ``tests/unit/core/provenance/test_schema.py``; y el 3 desde la 009, que añade las de
        las versiones: ``tests/unit/core/project/test_migration_0003.py``); las tres tablas
        internas, entre las declaradas ``write-only`` y fuera de ``gpkg_contents``; la
        comprobación de estructura no echa nada en falta y nombra lo que falte."""
        self.assertEqual((schema.SCHEMA_VERSION, schema.MIN_READER_SCHEMA), (3, 1))
        self.assertEqual(schema.INTERNAL_TABLES[: len(INTERNAL)], INTERNAL)
        with project_tmp() as tmp:
            path = tmp / "project.gpkg"
            _new_project_db(path)
            with gpkg.GpkgConnection.open_read(path) as db:
                conn = db.connection
                declared = [
                    row[0]
                    for row in conn.execute(
                        "SELECT table_name FROM gpkg_extensions WHERE "
                        "extension_name = 'imga_geoblender' AND scope = 'write-only' "
                        "ORDER BY table_name"
                    )
                ]
                registered = conn.execute(
                    "SELECT count(*) FROM gpkg_contents WHERE table_name LIKE 'gb_%'"
                ).fetchone()[0]
                self.assertEqual(schema.missing_objects(conn, schema.SCHEMA_VERSION), [])
            self.assertEqual(declared, sorted(schema.INTERNAL_TABLES))
            self.assertEqual(registered, 0)
            raw = sqlite3.connect(path, isolation_level=None)
            try:
                raw.execute("DROP TRIGGER gb_event_no_upd")
                missing = schema.missing_objects(raw, schema.SCHEMA_VERSION)
            finally:
                raw.close()
            self.assertEqual(missing, ["trigger gb_event_no_upd"])


if __name__ == "__main__":
    unittest.main()
