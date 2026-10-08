# SPDX-License-Identifier: GPL-3.0-or-later
"""Un GeoPackage de proyecto con tablas de datos para las pruebas del seguimiento y de lo
importado (spec 008, T10; RF-008-21, RF-008-52; ADR-0025 §4 y §6; plan 008 §5.2.1).

- :func:`build_template`: el esquema 2 del proyecto (``create_base`` y ``create_schema``)
  con cuatro tablas registradas en ``gpkg_contents`` y una que no lo está:

  * :data:`LAYER` (``core_limites``): capa de polígonos con ``codigo`` y ``tipo``;
  * :data:`SHARED` (``core_ensayos``): tabla común de varias entradas (``input_uid``) con
    ``codigo`` único (índice :data:`SHARED_UNIQUE_INDEX`), ``ley`` y ``nota``, y las filas
    de :data:`INPUT_A`, :data:`INPUT_B` y :data:`INPUT_C`;
  * :data:`OTHER` (``core_otra``): una tabla que ninguna prueba sigue;
  * :data:`ODD` (``Capa d'IMGA "rara"``): una tabla con espacios, comillas y mayúsculas,
    como las que crea una persona en QGIS;
  * :data:`UNREGISTERED` (``ajena``): una tabla creada con SQL, fuera de ``gpkg_contents``.

  Todas con :data:`OLD_CHANGE` en ``last_change``.
- :func:`foreign_connection`: una conexión como la de QGIS o GDAL, sin ``gb_writer()`` y en
  modo autocompromiso.
- :func:`rebuild_like_gdal`: rehace una tabla como GDAL al cambiar sus campos (tabla
  temporal, copia, ``DROP TABLE`` y ``ALTER TABLE … RENAME``), con las mismas columnas y
  sin volver a poner sus disparadores.
- :func:`last_change`, :func:`set_last_change`, :func:`rows`, :func:`dump` y :func:`quote`.
- :class:`DatasetTablesCase`: cada prueba trabaja en una copia de la plantilla (que se crea
  una vez por clase), abierta como Geoblender (``self.db``, ``self.conn``) y como QGIS
  (``self.qgis``).

Datos solo sintéticos (constitución, principio 7): ni rutas ni datos de un expediente.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any, ClassVar

from tests.support.package import import_geoblender

LAYER = "core_limites"
SHARED = "core_ensayos"
SHARED_UNIQUE_INDEX = "core_ensayos_codigo"
OTHER = "core_otra"
ODD = 'Capa d\'IMGA "rara"'
UNREGISTERED = "ajena"
REGISTERED: tuple[str, ...] = (LAYER, SHARED, OTHER, ODD)
INPUT_A = "00000000-0000-4000-8000-0000000000e1"
INPUT_B = "00000000-0000-4000-8000-0000000000e2"
INPUT_C = "00000000-0000-4000-8000-0000000000e3"
OLD_CHANGE = "2000-01-01T00:00:00.000Z"
# Filas de la tabla común: (fid, input_uid, codigo, ley, nota).
SHARED_ROWS: tuple[tuple[int, str, str, float, str], ...] = (
    (1, INPUT_A, "S-01", 1.25, "a"),
    (2, INPUT_A, "S-02", 0.80, "a"),
    (3, INPUT_B, "S-03", 2.10, "b"),
    (4, INPUT_C, "S-04", 0.35, "c"),
)


def quote(name: str) -> str:
    """``name`` como identificador de SQL entre comillas dobles."""
    return '"' + name.replace('"', '""') + '"'


def build_template(path: Path) -> None:
    """Crea en ``path`` el GeoPackage de las pruebas (véase el docstring del módulo)."""
    gpkg = import_geoblender("core.gpkg")
    base = import_geoblender("core.gpkg.base")
    project_schema = import_geoblender("core.project.schema")
    georef = import_geoblender("core.georef")
    crs = georef.load_catalog().horizontal(25830)
    text = base.ColumnDef
    with gpkg.GpkgConnection.open_write(path, create=True) as db:
        with db.transaction() as conn:
            base.create_base(conn, crs)
            project_schema.create_schema(conn)
            base.create_feature_table(
                conn,
                LAYER,
                "POLYGON",
                crs.epsg,
                False,
                [text("codigo", "TEXT"), text("tipo", "TEXT")],
                "Límites",
            )
            base.create_attribute_table(
                conn,
                SHARED,
                [
                    text("input_uid", "TEXT", not_null=True),
                    text("codigo", "TEXT"),
                    text("ley", "DOUBLE"),
                    text("nota", "TEXT"),
                ],
                "Ensayos",
            )
            conn.execute(
                f"CREATE UNIQUE INDEX {SHARED_UNIQUE_INDEX} ON {SHARED} (codigo)"
            )
            base.create_attribute_table(conn, OTHER, [text("valor", "DOUBLE")], "Otra")
            conn.execute(
                f"CREATE TABLE {quote(ODD)} (fid INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "
                "nombre TEXT)"
            )
            conn.execute(
                "INSERT INTO gpkg_contents (table_name, data_type, identifier) "
                "VALUES (?, 'attributes', ?)",
                (ODD, ODD),
            )
            conn.execute(
                f"CREATE TABLE {UNREGISTERED} (fid INTEGER PRIMARY KEY AUTOINCREMENT, x TEXT)"
            )
            conn.executemany(
                f"INSERT INTO {LAYER} (fid, geom, codigo, tipo) VALUES (?, NULL, ?, ?)",
                [(1, "P-01", "concesion"), (2, "P-02", "concesion"), (3, "P-03", "exclusion")],
            )
            conn.executemany(
                f"INSERT INTO {SHARED} (fid, input_uid, codigo, ley, nota) "
                "VALUES (?, ?, ?, ?, ?)",
                SHARED_ROWS,
            )
            conn.execute(f"INSERT INTO {OTHER} (valor) VALUES (1.5)")
            conn.execute(f"INSERT INTO {quote(ODD)} (nombre) VALUES ('uno')")
            conn.execute("UPDATE gpkg_contents SET last_change = ?", (OLD_CHANGE,))


def foreign_connection(path: Path) -> sqlite3.Connection:
    """Una conexión ajena a Geoblender (QGIS, GDAL): sin ``gb_writer()``, sin claves
    foráneas y en modo autocompromiso."""
    return sqlite3.connect(str(path), timeout=2.0, isolation_level=None)


def last_change(conn: sqlite3.Connection, table: str) -> Any:
    """``gpkg_contents.last_change`` de ``table``."""
    row = conn.execute(
        "SELECT last_change FROM gpkg_contents WHERE table_name = ?", (table,)
    ).fetchone()
    if row is None:
        raise AssertionError(f"«{table}» no está en gpkg_contents")
    return row[0]


def set_last_change(conn: sqlite3.Connection, table: str, value: str = OLD_CHANGE) -> None:
    """Pone ``value`` en ``gpkg_contents.last_change`` de ``table`` (fuera de una
    transacción, se confirma sola)."""
    conn.execute(
        "UPDATE gpkg_contents SET last_change = ? WHERE table_name = ?", (value, table)
    )


def rows(conn: sqlite3.Connection, table: str) -> list[tuple[Any, ...]]:
    """Todas las filas de ``table`` por ``fid``."""
    return conn.execute(f"SELECT * FROM {quote(table)} ORDER BY fid").fetchall()


def dump(conn: sqlite3.Connection) -> list[Any]:
    """``sqlite_master`` entero, ``gpkg_contents`` y las filas de las tablas de datos (en
    lugar de ``Connection.iterdump``, que falla con las comillas del nombre de :data:`ODD`)."""
    master = "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY 1, 2"
    found: list[Any] = [
        conn.execute(master).fetchall(),
        conn.execute("SELECT * FROM gpkg_contents ORDER BY 1").fetchall(),
    ]
    present = {
        row[0].lower()
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    found += [rows(conn, table) for table in REGISTERED if table.lower() in present]
    return found


def rebuild_like_gdal(conn: sqlite3.Connection, table: str) -> None:
    """Rehace ``table`` como GDAL al cambiar un campo (``RecreateTable``): crea
    ``<tabla>_ogr_tmp`` con las mismas columnas, copia las filas, borra la tabla (y con ella
    sus disparadores e índices) y renombra la temporal. En una transacción de ``conn``
    (autocompromiso); no vuelve a poner disparadores ni índices."""
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()[0]
    columns = sql[sql.index("(") :]
    temporary = f"{table}_ogr_tmp"
    conn.execute("BEGIN")
    try:
        conn.execute(f"CREATE TABLE {quote(temporary)} {columns}")
        conn.execute(f"INSERT INTO {quote(temporary)} SELECT * FROM {quote(table)}")
        conn.execute(f"DROP TABLE {quote(table)}")
        conn.execute(f"ALTER TABLE {quote(temporary)} RENAME TO {quote(table)}")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


class DatasetTablesCase(unittest.TestCase):
    """Una copia de la plantilla por prueba: ``self.db`` (``GpkgConnection`` de escritura
    de Geoblender), ``self.conn`` (su conexión de ``sqlite3``) y ``self.qgis`` (una conexión
    ajena, :func:`foreign_connection`), que se cierran al acabar."""

    template: ClassVar[Path]

    @classmethod
    def setUpClass(cls) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="gb-t10-", ignore_cleanup_errors=True)
        cls.addClassCleanup(tmp.cleanup)
        cls.template = Path(tmp.name) / "plantilla.gpkg"
        build_template(cls.template)

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="gb-t10-", ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "project.gpkg"
        shutil.copyfile(self.template, self.path)
        gpkg = import_geoblender("core.gpkg")
        self.db = gpkg.GpkgConnection.open_write(self.path)
        self.addCleanup(self.db.close)
        self.conn = self.db.connection
        self.qgis = foreign_connection(self.path)
        self.addCleanup(self.qgis.close)
