# SPDX-License-Identifier: GPL-3.0-or-later
"""Crear la base de un proyecto con su imagen (tarea 009/T34; RNF-001-01; RF-002-05,
RF-002-14, RF-009-02; plan 009 §5.2.3).

Un proyecto nuevo se crea escribiendo la imagen de su base sin sus filas propias
(``core.project.schema.base_image``: la estructura GeoPackage con las filas del estándar y el
esquema de esta versión, hechas una vez por proceso) y añadiendo, en una transacción, el CRS
del proyecto, su fila de ``gb_project`` y su evento de creación. Da lo mismo que hacerlo todo
en la base, como hasta la 009/T33 (``core.gpkg.base.create_base``,
``core.project.schema.create_schema``, la fila y el evento): el mismo ``sqlite_master`` (tipo,
nombre, tabla y SQL, en su orden), las mismas filas de cada tabla, la misma cabecera de
GeoPackage y el diario clásico. Solo cambian las páginas en que SQLite guarda cada tabla.
"""

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from tests.support.core_fixtures import FakeClock, make_session, make_settings, project_tmp
from tests.support.package import import_geoblender

create = import_geoblender("core.project.create")
schema = import_geoblender("core.project.schema")
events = import_geoblender("core.project.events")
gpkg_base = import_geoblender("core.gpkg.base")
gpkg = import_geoblender("core.gpkg")
crs_mod = import_geoblender("core.georef.crs")
userdata_mod = import_geoblender("core.userdata")

SESSION = make_session()
# Las dos variantes de la fila del proyecto: un datum vertical del catálogo y uno local.
VARIANTS: dict[str, dict[str, Any]] = {
    "EPSG:5782": {},
    "local": {"name": "Cantera Local", "vcrs_epsg": None,
              "vcrs_note": "cotas del plano de la concesión"},
}


def _contents(database: Path) -> dict[str, Any]:
    """Lo que se compara de una base: ``sqlite_master`` sin las páginas raíz (en su orden),
    las filas de cada tabla (por ``rowid``), la cabecera de GeoPackage y el diario."""
    conn = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    try:
        master = conn.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY rowid").fetchall()
        rows = {}
        for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"):
            cursor = conn.execute(f'SELECT * FROM "{name}" ORDER BY rowid')
            rows[name] = ([column[0] for column in cursor.description], cursor.fetchall())
        pragmas = {pragma: conn.execute(f"PRAGMA {pragma}").fetchone()[0]
                   for pragma in ("application_id", "user_version", "page_size", "encoding",
                                  "auto_vacuum", "journal_mode")}
    finally:
        conn.close()
    header = database.read_bytes()[:100]
    return {"master": master, "rows": rows, "pragmas": pragmas,
            "format": (header[18], header[19])}


def _all_in_the_base(database: Path, created: Any) -> None:
    """La base de ``created`` hecha toda en ella, como hasta la 009/T33 (``create_base``,
    ``create_schema``, la fila del proyecto y su evento, en una transacción)."""
    record = created.record
    crs = crs_mod.load_catalog().horizontal(record.crs_epsg)
    message, data = create._create_event(record, created.network)
    with gpkg.GpkgConnection.open_write(database, create=True) as db:
        with db.transaction() as conn:
            gpkg_base.create_base(conn, crs)
            schema.create_schema(conn)
            schema.insert_project(conn, record)
            events.record_event(conn, events.EventKind.CREATE, message, session=SESSION,
                                at=record.created_at, data=data)


class BaseImageTest(unittest.TestCase):
    def test_same_database_as_building_it_all(self) -> None:
        """RF-002-05, RF-002-14, RF-009-02 (009/T34): la base de un proyecto nuevo, con un
        datum vertical del catálogo o con uno local, tiene el mismo ``sqlite_master`` (tipo,
        nombre, tabla y SQL de cada objeto, en su orden), las mismas filas en cada tabla (con
        el CRS del proyecto en ``gpkg_spatial_ref_sys``), la misma cabecera de GeoPackage
        (``application_id``, ``user_version``) y el mismo diario clásico (formato 1, no WAL)
        que haciéndola toda en la base."""
        with project_tmp("gb-t34-") as tmp:
            for label, overrides in VARIANTS.items():
                with self.subTest(vertical=label):
                    parent = tmp / label.replace(":", "")
                    parent.mkdir()
                    created = create.create_project(
                        parent, make_settings(**overrides), SESSION,
                        userdata_mod.UserData(tmp / "u"), clock=FakeClock())
                    fresh = parent / "nuevo.gpkg"  # tal como queda al crearlo, sin cerrarlo
                    shutil.copyfile(created.root / create.PROJECT_STORE, fresh)
                    created.project.close()
                    reference = parent / "referencia.gpkg"
                    _all_in_the_base(reference, created)
                    new = _contents(fresh)
                    built = _contents(reference)
                    self.assertEqual(new["master"], built["master"])
                    self.assertEqual(new["rows"], built["rows"])
                    self.assertEqual(new["pragmas"], built["pragmas"])
                    self.assertEqual(new["format"], (1, 1))
                    self.assertEqual(new["pragmas"]["journal_mode"], "delete")
                    srs = new["rows"]["gpkg_spatial_ref_sys"][1]
                    self.assertEqual([row[1] for row in srs],
                                     [-1, 0, 4326, created.record.crs_epsg])
                    self.assertGreater(len(new["master"]), 150)

    def test_the_schema_is_built_once_per_process(self) -> None:
        """RNF-001-01 (009/T34): la imagen se hace una vez por proceso, con
        ``create_schema`` en una base en memoria; los proyectos siguientes la escriben sin
        volver a crear el esquema. Es inmutable (``bytes``) y es una base SQLite del esquema
        de esta versión, sin fila de proyecto ni CRS del proyecto."""
        schema.base_image.cache_clear()
        self.addCleanup(schema.base_image.cache_clear)
        with (
            mock.patch.object(schema, "create_schema", wraps=schema.create_schema) as built,
            project_tmp("gb-t34u-") as tmp,
        ):
            for number in range(3):
                parent = tmp / str(number)
                parent.mkdir()
                created = create.create_project(
                    parent, make_settings(), SESSION, userdata_mod.UserData(tmp / "u"),
                    clock=FakeClock())
                created.project.close()
        self.assertEqual(built.call_count, 1)
        image = schema.base_image()
        self.assertIsInstance(image, bytes)
        self.assertTrue(image.startswith(b"SQLite format 3\x00"))
        folder = Path(tempfile.mkdtemp(prefix="gb-t34i-"))
        self.addCleanup(shutil.rmtree, folder, True)
        path = folder / "imagen.gpkg"
        path.write_bytes(image)
        conn = sqlite3.connect(path)
        try:
            self.assertEqual(conn.execute("SELECT count(*) FROM gb_project").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT count(*) FROM gb_event").fetchone()[0], 0)
            self.assertEqual(
                [row[0] for row in conn.execute(
                    "SELECT srs_id FROM gpkg_spatial_ref_sys ORDER BY srs_id")], [-1, 0, 4326])
            versions = import_geoblender("core.versions.schema")
            self.assertEqual(versions.missing_objects(conn), [])
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
