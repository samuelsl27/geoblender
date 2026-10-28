# SPDX-License-Identifier: GPL-3.0-or-later
"""La lista de valores de una columna (spec 012, T06; RF-012-03; plan 012 §5.3.2 y D-35).

``core.gpkg.base.set_column_enum`` escribe la lista de valores admitidos de una columna de una capa
o tabla registrada en ``gpkg_data_column_constraints`` (extensión ``gpkg_schema`` de GeoPackage
1.4, ``constraint_type = 'enum'``: el valor en ``value`` y su texto en español en
``description``) y la enlaza desde ``gpkg_data_columns.constraint_name``. El GDAL la lee como
dominio de campo (código → texto) y QGIS la ofrece como lista; lo prueba la T20 con su GDAL.

- Sin el nombre de la lista, ``<tabla>_<columna>``; con ``name``, varias columnas comparten una.
- Volver a llamarla cambia la lista entera de ese nombre; el título de la columna (``name`` y
  ``title`` de ``gpkg_data_columns``) no cambia.
- Lo que no vale se rechaza sin escribir nada.
"""

from __future__ import annotations

import sqlite3
import unittest

from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender

gpkg = import_geoblender("core.gpkg")
base = import_geoblender("core.gpkg.base")
georef = import_geoblender("core.georef")
errors = import_geoblender("core.errors")

CRS = georef.load_catalog().horizontal(25830)
LAYER = "capa_zonas"
OTHER = "capa_lineas"
TABLE = "tabla_notas"
VALUES = (("open", "Abierta"), ("closed", "Cerrada"), ("pending", "Pendiente de revisar"))


def _new(path):
    """Un GeoPackage con dos capas (con columna ``state``) y una tabla de atributos."""
    db = gpkg.GpkgConnection.open_write(path, create=True)
    with db.transaction() as conn:
        base.create_base(conn, CRS)
        columns = (base.ColumnDef("state", "TEXT"), base.ColumnDef("note", "TEXT"))
        base.create_feature_table(conn, LAYER, "MULTIPOLYGON", CRS.epsg, False, columns,
                                  identifier="Zonas")
        base.create_feature_table(conn, OTHER, "MULTILINESTRING", CRS.epsg, False, columns,
                                  identifier="Líneas")
        base.create_attribute_table(conn, TABLE, columns, identifier="Notas")
    return db


def _enum(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute(
        "SELECT constraint_name, constraint_type, value, min, min_is_inclusive, max, "
        "max_is_inclusive, description FROM gpkg_data_column_constraints "
        "ORDER BY constraint_name, rowid").fetchall()


def _links(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute(
        "SELECT table_name, column_name, name, title, constraint_name FROM gpkg_data_columns "
        "ORDER BY table_name, column_name").fetchall()


def _expected(name: str, values=VALUES) -> list[tuple]:
    return [(name, "enum", code, None, None, None, None, text) for code, text in values]


class ColumnEnumTest(unittest.TestCase):
    def test_enum_rows_and_link(self) -> None:
        """RF-012-03, D-35: la lista va a ``gpkg_data_column_constraints`` (``enum``, el código
        en ``value`` y el español en ``description``, en su orden) y la columna la nombra en
        ``gpkg_data_columns.constraint_name``; se crean las tablas de la extensión «schema» y
        sus filas en ``gpkg_extensions``; devuelve el nombre de la lista; la base sigue
        íntegra."""
        with project_tmp() as tmp, _new(tmp / "p.gpkg") as db:
            with db.transaction() as conn:
                name = base.set_column_enum(conn, LAYER, "state", VALUES)
            conn = db.connection
            self.assertEqual(name, f"{LAYER}_state")
            self.assertEqual(_enum(conn), _expected(name))
            self.assertEqual(_links(conn), [(LAYER, "state", None, None, name)])
            schema = conn.execute("SELECT table_name FROM gpkg_extensions WHERE "
                                  "extension_name = 'gpkg_schema' ORDER BY table_name")
            self.assertEqual([row[0] for row in schema],
                             ["gpkg_data_column_constraints", "gpkg_data_columns"])
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_shared_name_title_kept_and_list_replaced(self) -> None:
        """D-35: con ``name`` dos capas y una tabla comparten la lista; el título que ya tenía
        la columna se conserva (y ponerlo después también); volver a llamarla con otros valores
        cambia la lista entera de ese nombre, sin filas repetidas."""
        shared = "zone_state"
        with project_tmp() as tmp, _new(tmp / "p.gpkg") as db:
            with db.transaction() as conn:
                base.set_column_titles(conn, LAYER, {"state": "Estado"})
                for table in (LAYER, OTHER, TABLE):
                    self.assertEqual(base.set_column_enum(conn, table, "state", VALUES,
                                                          name=shared), shared)
                base.set_column_titles(conn, OTHER, {"state": "Estado de la línea"})
            self.assertEqual(_enum(db.connection), _expected(shared))
            self.assertEqual(_links(db.connection), [
                (OTHER, "state", "Estado de la línea", "Estado de la línea", shared),
                (LAYER, "state", "Estado", "Estado", shared),
                (TABLE, "state", None, None, shared),
            ])
            fewer = (("open", "Abierta"), ("closed", "Cerrada definitivamente"))
            with db.transaction() as conn:
                base.set_column_enum(conn, LAYER, "state", fewer, name=shared)
            self.assertEqual(_enum(db.connection), _expected(shared, fewer))
            self.assertEqual(len(_links(db.connection)), 3)

    def test_invalid_lists_write_nothing(self) -> None:
        """RF-012-03: una tabla que no existe o que no está registrada, una columna que no
        tiene, un nombre de lista que no es un identificador, una lista vacía, un código o un
        texto vacíos o que no son textos, y un código repetido se rechazan con
        ``ValidationError`` sin escribir nada; un texto o un diccionario en lugar de la lista
        de pares, ``TypeError``."""
        cases = {
            "tabla que no existe": ("no_existe", "state", VALUES, None, "table_unknown"),
            "tabla interna": ("gb_interna", "v", VALUES, None, "table_unregistered"),
            "columna": (LAYER, "nada", VALUES, None, "column_unknown"),
            "nombre": (LAYER, "state", VALUES, "Lista X", "name_invalid"),
            "vacía": (LAYER, "state", (), None, "enum_invalid"),
            "código vacío": (LAYER, "state", (("", "Nada"),), None, "enum_invalid"),
            "texto vacío": (LAYER, "state", (("open", "  "),), None, "enum_invalid"),
            "código no texto": (LAYER, "state", ((1, "Uno"),), None, "enum_invalid"),
            "par mal formado": (LAYER, "state", (("open",),), None, "enum_invalid"),
            "repetido": (LAYER, "state", (("open", "A"), ("open", "B")), None,
                         "enum_invalid"),
        }
        with project_tmp() as tmp, _new(tmp / "p.gpkg") as db:
            with db.transaction() as conn:
                conn.execute("CREATE TABLE gb_interna (fid INTEGER PRIMARY KEY, v TEXT)")
                base.register_internal_table(conn, "gb_interna")
            for label, (table, column, values, name, code) in cases.items():
                with self.subTest(label):
                    with self.assertRaises(errors.ValidationError) as caught:
                        with db.transaction() as conn:
                            base.set_column_enum(conn, table, column, values, name=name)
                    self.assertEqual(caught.exception.code, f"core.gpkg_{code}")
            for wrong in ("open", dict(VALUES)):
                with self.subTest(wrong=type(wrong).__name__):
                    with self.assertRaises(TypeError), db.transaction() as conn:
                        base.set_column_enum(conn, LAYER, "state", wrong)
            tables = {row[0] for row in db.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
            self.assertNotIn("gpkg_data_column_constraints", tables)
            self.assertNotIn("gpkg_data_columns", tables)


if __name__ == "__main__":
    unittest.main()
