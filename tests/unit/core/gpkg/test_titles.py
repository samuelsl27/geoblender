# SPDX-License-Identifier: GPL-3.0-or-later
"""Títulos (alias) en español e índices de las tablas de un módulo con ``core.gpkg`` (spec 005,
T36; RF-005-01; plan 005 §5.2.1 y §5.6.1).

- ``set_column_titles`` escribe el título de cada columna en ``gpkg_data_columns`` (extensión
  ``gpkg_schema`` de GeoPackage 1.4) en ``name`` y en ``title``: el GDAL de QGIS 4.2 (3.13.1)
  toma el alias de un campo de ``name`` y no lee ``title`` (comprobado en esta tarea con
  PyQGIS sin interfaz: con solo ``title``, ningún alias). Si faltan, crea
  ``gpkg_data_columns`` y ``gpkg_data_column_constraints`` como las crea ese GDAL y sus dos
  filas ``gpkg_schema`` en ``gpkg_extensions`` (``read-write``: lo exige ``validate_gpkg.py``).
- ``create_index`` crea un índice, único o no, con las columnas de ``nocase`` sin distinguir
  mayúsculas (``COLLATE NOCASE``).
- Un proyecto nuevo o migrado no tiene ``gpkg_data_columns`` hasta que un módulo pone títulos,
  y la 008 no cuenta las tablas de la extensión como capas sin registrar.
- Con QGIS (``GEOBLENDER_QGIS_DIR``): PyQGIS sin interfaz muestra el alias de cada campo de una
  capa y de una tabla del proyecto, ``ogrinfo`` no avisa y ``validate_gpkg.py`` lo da por
  bueno.
"""

import json
import re
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

import numpy as np

from tests.support import qgis
from tests.support.core_fixtures import (
    FakeClock,
    FakePids,
    make_schema_1,
    make_session,
    make_settings,
    project_tmp,
)
from tests.support.package import import_geoblender
from tests.support.resources import requires

gpkg = import_geoblender("core.gpkg")
base = import_geoblender("core.gpkg.base")
georef = import_geoblender("core.georef")
errors = import_geoblender("core.errors")
create = import_geoblender("core.project.create")
migrations = import_geoblender("core.project.migrations")
datasets = import_geoblender("core.datasets")
userdata_mod = import_geoblender("core.userdata")

CRS = georef.load_catalog().horizontal(25830)
SESSION = make_session()
LAYER = "capa_bocas"
TABLE = "tabla_tramos"
LAYER_COLUMNS = (
    base.ColumnDef("name", "TEXT", not_null=True),
    base.ColumnDef("depth", "DOUBLE"),
    base.ColumnDef("inclination", "DOUBLE"),
)
TABLE_COLUMNS = (
    base.ColumnDef("hole", "TEXT", not_null=True),
    base.ColumnDef("from_m", "DOUBLE"),
    base.ColumnDef("to_m", "DOUBLE"),
    base.ColumnDef("code", "TEXT"),
)
LAYER_TITLES = {"name": "Sondeo", "depth": "Profundidad (m)", "inclination": "Inclinación (°)"}
TABLE_TITLES = {"hole": "Sondeo", "from_m": "Desde (m)", "to_m": "Hasta (m)"}
SCHEMA_TABLES = ("gpkg_data_columns", "gpkg_data_column_constraints")
SCHEMA_DEFINITION = "http://www.geopackage.org/spec121/#extension_schema"
# PRAGMA table_info (cid, nombre, tipo, notnull, defecto, pk): lo que crea el GDAL de QGIS 4.2
# al poner un alias y lo que espera su validate_gpkg.py (GeoPackage 1.4).
DATA_COLUMNS_INFO = [
    (0, "table_name", "TEXT", 1, None, 1),
    (1, "column_name", "TEXT", 1, None, 2),
    (2, "name", "TEXT", 0, None, 0),
    (3, "title", "TEXT", 0, None, 0),
    (4, "description", "TEXT", 0, None, 0),
    (5, "mime_type", "TEXT", 0, None, 0),
    (6, "constraint_name", "TEXT", 0, None, 0),
]
CONSTRAINTS_INFO = [
    (0, "constraint_name", "TEXT", 1, None, 0),
    (1, "constraint_type", "TEXT", 1, None, 0),
    (2, "value", "TEXT", 0, None, 0),
    (3, "min", "NUMERIC", 0, None, 0),
    (4, "min_is_inclusive", "BOOLEAN", 0, None, 0),
    (5, "max", "NUMERIC", 0, None, 0),
    (6, "max_is_inclusive", "BOOLEAN", 0, None, 0),
    (7, "description", "TEXT", 0, None, 0),
]


def _tables(conn: sqlite3.Connection) -> None:
    """La capa de puntos con Z y la tabla de atributos de las pruebas."""
    base.create_feature_table(conn, LAYER, "POINT", CRS.epsg, True, LAYER_COLUMNS,
                              identifier="Bocas de prueba")
    base.create_attribute_table(conn, TABLE, TABLE_COLUMNS, identifier="Tramos de prueba")


def _new(path: Path) -> object:
    """Un GeoPackage con la estructura del proyecto y las dos tablas de las pruebas."""
    db = gpkg.GpkgConnection.open_write(path, create=True)
    with db.transaction() as conn:
        base.create_base(conn, CRS)
        _tables(conn)
    return db


def _titles(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute(
        "SELECT table_name, column_name, name, title, description, mime_type, constraint_name "
        "FROM gpkg_data_columns ORDER BY table_name, column_name"
    ).fetchall()


def _schema_rows(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute(
        "SELECT table_name, column_name, extension_name, definition, scope FROM gpkg_extensions "
        "WHERE extension_name = 'gpkg_schema' ORDER BY table_name"
    ).fetchall()


def _objects(conn: sqlite3.Connection, kind: str) -> list[str]:
    """Las tablas o los índices de la base, sin los automáticos de SQLite (sin SQL)."""
    return [row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = ? AND sql IS NOT NULL ORDER BY name",
        (kind,))]


def _expected(table: str, titles: dict[str, str]) -> list[tuple]:
    return [(table, column, title, title, None, None, None) for column, title in titles.items()]


class TitlesTest(unittest.TestCase):
    def test_titles_go_to_name_and_title_with_the_schema_extension(self) -> None:
        """RF-005-01 (plan 005 §5.2.1): los títulos de una capa y de una tabla quedan en
        ``gpkg_data_columns``, en ``name`` (el alias que lee el GDAL de QGIS 4.2) y en ``title``;
        se crean ``gpkg_data_columns`` y ``gpkg_data_column_constraints`` con la estructura de
        GeoPackage 1.4 y las dos filas ``gpkg_schema`` (``read-write``, sin columna) en
        ``gpkg_extensions``; la base sigue íntegra."""
        with project_tmp() as tmp, _new(tmp / "p.gpkg") as db:
            with db.transaction() as conn:
                base.set_column_titles(conn, LAYER, LAYER_TITLES)
                base.set_column_titles(conn, TABLE, TABLE_TITLES)
            conn = db.connection
            self.assertEqual(_titles(conn), sorted(_expected(LAYER, LAYER_TITLES)
                                                   + _expected(TABLE, TABLE_TITLES)))
            self.assertEqual(_schema_rows(conn), [
                (table, None, "gpkg_schema", SCHEMA_DEFINITION, "read-write")
                for table in sorted(SCHEMA_TABLES)])
            self.assertEqual(base.SCHEMA_EXTENSION_DEFINITION, SCHEMA_DEFINITION)
            self.assertEqual(conn.execute("PRAGMA table_info(gpkg_data_columns)").fetchall(),
                             DATA_COLUMNS_INFO)
            self.assertEqual(
                conn.execute("PRAGMA table_info(gpkg_data_column_constraints)").fetchall(),
                CONSTRAINTS_INFO)
            contents = [row[0] for row in conn.execute("SELECT table_name FROM gpkg_contents")]
            self.assertEqual(sorted(contents), sorted([LAYER, TABLE]))
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_setting_again_changes_only_those_columns(self) -> None:
        """RF-005-01: volver a poner títulos en una tabla cambia los de esas columnas (también
        intercambiando dos), deja los demás y lo que escribió otro programa en la fila
        (``description``), y no repite tablas ni filas de ``gpkg_extensions``."""
        with project_tmp() as tmp, _new(tmp / "p.gpkg") as db:
            with db.transaction() as conn:
                base.set_column_titles(conn, TABLE, TABLE_TITLES)
                conn.execute("UPDATE gpkg_data_columns SET description = 'Nota de QGIS' "
                             "WHERE column_name = 'from_m'")
            with db.transaction() as conn:
                base.set_column_titles(conn, TABLE, {"from_m": "Hasta (m)", "to_m": "Desde (m)"})
                base.set_column_titles(conn, TABLE, {"code": "Código"})
            conn = db.connection
            self.assertEqual(_titles(conn), [
                (TABLE, "code", "Código", "Código", None, None, None),
                (TABLE, "from_m", "Hasta (m)", "Hasta (m)", "Nota de QGIS", None, None),
                (TABLE, "hole", "Sondeo", "Sondeo", None, None, None),
                (TABLE, "to_m", "Desde (m)", "Desde (m)", None, None, None),
            ])
            self.assertEqual(len(_schema_rows(conn)), 2)
            for table in SCHEMA_TABLES:
                self.assertIn(table, _objects(conn, "table"))

    def test_without_titles_nothing_is_created(self) -> None:
        """RF-005-01: sin ningún título no se crea nada: ni las tablas de la extensión ni sus
        filas en ``gpkg_extensions``."""
        with project_tmp() as tmp, _new(tmp / "p.gpkg") as db:
            with db.transaction() as conn:
                base.set_column_titles(conn, LAYER, {})
            conn = db.connection
            self.assertEqual([t for t in SCHEMA_TABLES if t in _objects(conn, "table")], [])
            self.assertEqual(_schema_rows(conn), [])

    def test_invalid_titles_write_nothing(self) -> None:
        """RF-005-01: una tabla que no existe o que no es una capa ni una tabla registrada en
        ``gpkg_contents`` (una interna), un nombre que no es un identificador, una columna que
        no tiene, un título vacío o que no es un texto y dos columnas con el mismo título (sin
        distinguir mayúsculas, también frente a uno que ya tenía la tabla) se rechazan con
        ``ValidationError`` sin escribir nada; lo que no es un diccionario, ``TypeError``."""
        cases = {
            "tabla que no existe": ("no_existe", {"name": "Sondeo"}, "table_unknown"),
            "tabla interna": ("gb_interna", {"v": "Valor"}, "table_unregistered"),
            "nombre": ("Capa X", {"name": "Sondeo"}, "name_invalid"),
            "columna": (LAYER, {"nada": "Nada"}, "column_unknown"),
            "título vacío": (LAYER, {"name": "  "}, "title_invalid"),
            "título que no es un texto": (LAYER, {"depth": 3}, "title_invalid"),
            "títulos repetidos": (TABLE, {"from_m": "Profundidad", "to_m": "profundidad"},
                                  "title_repeated"),
        }
        with project_tmp() as tmp, _new(tmp / "p.gpkg") as db:
            with db.transaction() as conn:
                conn.execute("CREATE TABLE gb_interna (fid INTEGER PRIMARY KEY, v TEXT)")
                base.register_internal_table(conn, "gb_interna")
            for label, (table, titles, code) in cases.items():
                with self.subTest(label):
                    with self.assertRaises(errors.ValidationError) as caught:
                        with db.transaction() as conn:
                            base.set_column_titles(conn, table, titles)
                    self.assertEqual(caught.exception.code, f"core.gpkg_{code}")
            with self.assertRaises(TypeError), db.transaction() as conn:
                base.set_column_titles(conn, LAYER, [("name", "Sondeo")])
            conn = db.connection
            self.assertEqual([t for t in SCHEMA_TABLES if t in _objects(conn, "table")], [])
            self.assertEqual(_schema_rows(conn), [])
            with db.transaction() as conn:
                base.set_column_titles(conn, TABLE, {"hole": "Sondeo"})
            with self.assertRaises(errors.ValidationError) as caught:
                with db.transaction() as conn:
                    base.set_column_titles(conn, TABLE, {"code": "SONDEO"})
            self.assertEqual(caught.exception.code, "core.gpkg_title_repeated")
            self.assertEqual(_titles(db.connection), _expected(TABLE, {"hole": "Sondeo"}))


class IndexTest(unittest.TestCase):
    def test_unique_index_without_case_rejects_s12_next_to_S12(self) -> None:
        """RF-005-01 (plan 005 §5.6.1, nombres únicos sin mayúsculas): un índice único con la
        columna sin distinguir mayúsculas rechaza «s-12» junto a «S-12» y admite «S-13»; es
        único y su columna, ``NOCASE``."""
        with project_tmp() as tmp, _new(tmp / "p.gpkg") as db:
            with db.transaction() as conn:
                name = base.create_index(conn, LAYER, ["name"], unique=True, nocase=["name"])
                conn.execute(f"INSERT INTO {LAYER} (name) VALUES ('S-12')")
            self.assertEqual(name, base.index_name(LAYER, ["name"]))
            with self.assertRaises(sqlite3.IntegrityError), db.transaction() as conn:
                conn.execute(f"INSERT INTO {LAYER} (name) VALUES ('s-12')")
            with db.transaction() as conn:
                conn.execute(f"INSERT INTO {LAYER} (name) VALUES ('S-13')")
            conn = db.connection
            self.assertEqual([row[0] for row in conn.execute(f"SELECT name FROM {LAYER}")],
                             ["S-12", "S-13"])
            listed = {row[1]: row[2] for row in conn.execute(f"PRAGMA index_list({LAYER})")}
            self.assertEqual(listed, {name: 1})
            keys = [row[2:5] for row in conn.execute(f'PRAGMA index_xinfo("{name}")') if row[5]]
            self.assertEqual(keys, [("name", 0, "NOCASE")])

    def test_index_on_several_columns(self) -> None:
        """RF-005-01: un índice no único de dos columnas (la primera sin mayúsculas) admite
        filas repetidas, tiene sus columnas en orden con su comparación y sirve a la consulta
        por sondeo (sin mayúsculas) y profundidad."""
        with project_tmp() as tmp, _new(tmp / "p.gpkg") as db:
            with db.transaction() as conn:
                name = base.create_index(conn, TABLE, ("hole", "from_m"), nocase=("hole",))
                conn.executemany(f"INSERT INTO {TABLE} (hole, from_m) VALUES (?, ?)",
                                 [("S-12", 0.0), ("s-12", 0.0)])
            conn = db.connection
            self.assertEqual(name, base.index_name(TABLE, ("hole", "from_m")))
            self.assertEqual(conn.execute("SELECT tbl_name FROM sqlite_master WHERE type = "
                                          "'index' AND name = ?", (name,)).fetchone(), (TABLE,))
            listed = {row[1]: row[2] for row in conn.execute(f"PRAGMA index_list({TABLE})")}
            self.assertEqual(listed, {name: 0})
            keys = [row[2:5] for row in conn.execute(f'PRAGMA index_xinfo("{name}")') if row[5]]
            self.assertEqual(keys, [("hole", 0, "NOCASE"), ("from_m", 0, "BINARY")])
            plan = " ".join(str(row[3]) for row in conn.execute(
                f"EXPLAIN QUERY PLAN SELECT fid FROM {TABLE} WHERE hole = ? COLLATE NOCASE "
                "AND from_m = ?", ("S-12", 0.0)))
            self.assertIn(f"INDEX {name} (hole=? AND from_m=?)", plan)

    def test_invalid_indexes_create_nothing(self) -> None:
        """RF-005-01: una tabla que no existe o con un nombre que no es un identificador, sin
        columnas, una columna que no tiene o repetida, una columna sin mayúsculas que no está
        en el índice y un índice que ya existe se rechazan con ``ValidationError`` sin crear
        nada; un texto en lugar de la lista de columnas, ``TypeError``."""
        cases = {
            "tabla que no existe": ("no_existe", ["name"], (), "table_unknown"),
            "nombre": ("Capa X", ["name"], (), "name_invalid"),
            "sin columnas": (LAYER, [], (), "index_columns"),
            "columna": (LAYER, ["nada"], (), "column_unknown"),
            "columna repetida": (LAYER, ["name", "name"], (), "index_columns"),
            "sin mayúsculas fuera": (LAYER, ["depth"], ["name"], "index_columns"),
            "ya existe": (LAYER, ["name"], (), "index_exists"),
        }
        with project_tmp() as tmp, _new(tmp / "p.gpkg") as db:
            with db.transaction() as conn:
                first = base.create_index(conn, LAYER, ["name"])
            for label, (table, columns, nocase, code) in cases.items():
                with self.subTest(label):
                    with self.assertRaises(errors.ValidationError) as caught:
                        with db.transaction() as conn:
                            base.create_index(conn, table, columns, nocase=nocase)
                    self.assertEqual(caught.exception.code, f"core.gpkg_{code}")
            with self.assertRaises(TypeError), db.transaction() as conn:
                base.create_index(conn, LAYER, "name")
            self.assertEqual(_objects(db.connection, "index"), [first])


class _Project:
    """Un proyecto real (``create_project``) cerrado, con la capa y la tabla de las pruebas,
    sus títulos, sus índices y unas filas, escritas con la conexión de Geoblender."""

    def __init__(self, folder: Path) -> None:
        (folder / "proyectos").mkdir()
        created = create.create_project(folder / "proyectos", make_settings(name="Títulos"),
                                        SESSION, userdata_mod.UserData(folder / "datos"),
                                        clock=FakeClock())
        with created.project.write_transaction() as conn:
            _tables(conn)
            base.set_column_titles(conn, LAYER, LAYER_TITLES)
            base.set_column_titles(conn, TABLE, TABLE_TITLES)
            base.create_index(conn, LAYER, ["name"], unique=True, nocase=["name"])
            base.create_index(conn, TABLE, ["hole", "from_m"], nocase=["hole"])
            for name, xyz in (("S-12", (700_010.5, 4_400_020.25, 812.125)),
                              ("S-13", (700_110.5, 4_400_120.25, 815.5))):
                geom = gpkg.encode_geometry("POINT", np.array(xyz), CRS.epsg, True)
                conn.execute(f"INSERT INTO {LAYER} (geom, name, depth, inclination) "
                             "VALUES (?, ?, 150.0, -60.0)", (geom, name))
            conn.executemany(f"INSERT INTO {TABLE} (hole, from_m, to_m, code) VALUES "
                             "(?, ?, ?, ?)", [("S-12", 0.0, 7.5, "CAL"), ("S-12", 7.5, 12.0, None)])
        created.project.close()
        self.root = created.root
        self.database = created.root / "project.gpkg"


_PYQGIS_ALIASES = r"""
import json
import sys

from qgis.core import QgsVectorLayer

found = {}
for name in sys.argv[2:]:
    layer = QgsVectorLayer(f"{sys.argv[1]}|layername={name}", name, "ogr")
    found[name] = [layer.isValid(), layer.featureCount(),
                   [[field.name(), field.alias(), layer.attributeDisplayName(index)]
                    for index, field in enumerate(layer.fields())]]
print(json.dumps(found))
"""


class ProjectTitlesTest(unittest.TestCase):
    """Los títulos y los índices en un proyecto de la 008 (esquema 2), y lo que dice de él el
    GDAL de QGIS 4.2 (``GEOBLENDER_QGIS_DIR``; sin él, esas pruebas se omiten con
    «[ENTORNO] qgis»)."""

    @classmethod
    def setUpClass(cls) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="geoblender-005-", ignore_cleanup_errors=True)
        cls.addClassCleanup(tmp.cleanup)
        cls.folder = Path(tmp.name)
        cls.project = _Project(cls.folder)

    def test_new_and_migrated_projects_have_no_titles(self) -> None:
        """RF-005-01, RF-002-20: crear un proyecto y migrar uno del esquema 1 dan lo mismo que
        antes: ninguno tiene ``gpkg_data_columns`` ni ``gpkg_data_column_constraints`` ni
        filas ``gpkg_schema`` (las crea el primer módulo que pone títulos), y los dos tienen
        las mismas tablas e índices."""
        with project_tmp() as tmp:
            userdata = userdata_mod.UserData(tmp / "datos")
            roots = []
            for name in ("Nuevo", "Migrado"):
                (tmp / name).mkdir()
                created = create.create_project(tmp / name, make_settings(name=name), SESSION,
                                                userdata, clock=FakeClock())
                created.project.close()
                roots.append(created.root)
            make_schema_1(roots[1])
            list(migrations.migrate_steps(roots[1], SESSION, userdata, clock=FakeClock(),
                                          pid_alive=FakePids({SESSION.pid})))
            found = []
            for root in roots:
                with gpkg.GpkgConnection.open_read(root / "project.gpkg") as db:
                    conn = db.connection
                    tables = _objects(conn, "table")
                    self.assertEqual([t for t in SCHEMA_TABLES if t in tables], [], root.name)
                    self.assertEqual(_schema_rows(conn), [], root.name)
                    found.append((tables, _objects(conn, "index")))
            self.assertEqual(found[0], found[1])

    def test_the_008_does_not_list_the_extension_tables(self) -> None:
        """RF-005-01, RF-008-62: las capas y tablas sin registrar que ve la 008 en el proyecto
        son solo la capa y la tabla de la prueba (no se registraron como dato): ni
        ``gpkg_data_columns`` ni ``gpkg_data_column_constraints`` (tablas del estándar; los
        restos son ficheros de ``rasters/``, ``meshes/`` y ``originals/``)."""
        with gpkg.GpkgConnection.open_read(self.project.database) as db:
            found = datasets.unregistered_tables(db.connection)
            self.assertEqual(_titles(db.connection), sorted(_expected(LAYER, LAYER_TITLES)
                                                            + _expected(TABLE, TABLE_TITLES)))
        self.assertEqual([(item.name, item.registrable) for item in found],
                         [(LAYER, True), (TABLE, True)])

    @requires(qgis.QGIS, qgis.QGIS_HINT)
    def test_qgis_shows_the_titles_as_aliases(self) -> None:
        """RF-005-01: PyQGIS 4.2 sin interfaz abre la capa y la tabla del proyecto (en una
        copia: QGIS puede pasar a WAL lo que abre) y muestra como alias de cada campo su título
        (con tildes y «°»); los campos sin título, sin alias."""
        copy = Path(tempfile.mkdtemp(prefix="gb-t36-qgis-", dir=self.folder)) / "p.gpkg"
        shutil.copyfile(self.project.database, copy)
        result = qgis.run_pyqgis(_PYQGIS_ALIASES, str(copy), LAYER, TABLE)
        output = qgis.output_of(result)
        self.assertEqual(result.returncode, 0, output)
        found = json.loads(result.stdout.strip().splitlines()[-1])
        for table, titles, columns, count in ((LAYER, LAYER_TITLES, LAYER_COLUMNS, 2),
                                              (TABLE, TABLE_TITLES, TABLE_COLUMNS, 2)):
            with self.subTest(tabla=table):
                names = ["fid", *(column.name for column in columns)]
                aliases = [titles.get(name, "") for name in names]
                shown = [titles.get(name, name) for name in names]
                self.assertEqual(found[table], [True, count, [list(field) for field in zip(
                    names, aliases, shown, strict=True)]])

    @requires(qgis.QGIS, qgis.QGIS_HINT)
    def test_ogrinfo_and_validate_gpkg_without_warnings(self) -> None:
        """RF-005-01, RF-002-14: ``ogrinfo -ro -so -al`` del GDAL de QGIS termina con 0, sin
        ninguna línea con «Warning» ni «ERROR», y da el nombre alternativo de cada campo con
        título; ``validate_gpkg.py`` da por bueno el proyecto con títulos e índices (código 0,
        sin salida)."""
        info = qgis.run_tool("ogrinfo", "-ro", "-so", "-al", str(self.project.database))
        output = qgis.output_of(info)
        self.assertEqual(info.returncode, 0, output)
        noisy = [line for line in output.splitlines()
                 if "warning" in line.lower() or "ERROR" in line]
        self.assertEqual(noisy, [], output[:4000])
        for titles in (LAYER_TITLES, TABLE_TITLES):
            for column, title in titles.items():
                self.assertRegex(output, rf'\n{column}: \w+ \(\d+\.\d+\)( NOT NULL)?, '
                                         rf'alternative name="{re.escape(title)}"\n')
        validate = qgis.run_python(qgis.validate_gpkg_script(), str(self.project.database))
        self.assertEqual((validate.returncode, qgis.output_of(validate)), (0, ""))


if __name__ == "__main__":
    unittest.main()
