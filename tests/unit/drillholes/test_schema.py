# SPDX-License-Identifier: GPL-3.0-or-later
"""Diseño de las tablas de los sondeos y su hash (spec 005, T37; HU-005-1, HU-005-2; RF-005-01,
RF-005-02; plan 005 §5.2, §5.2.1 y §5.6.1, D17).

``drillholes.schema`` declara cada tabla de los sondeos con su ``TableLayout``: las once de la
base (``dh_collar``, capa de puntos con Z en el CRS del proyecto, y diez tablas), las tres de lo
calculado (``dh_trace``, capa de líneas 3D; ``dh_validation_issue`` y ``dh_import_log``) y las
siete de lo importado (``dh_src_<rol>_<nombre>_<entrada8>``, tablas en el CRS y los convenios
declarados, sin transformar). Cada columna tiene su título en español (``ALIASES``, que QGIS
muestra como alias). ``create_table`` crea una tabla en la transacción que la escribe (ninguna
se crea al abrir ni al migrar un proyecto) con ``core.gpkg`` (títulos e índices de la T36), y
``table_digest`` da su hash (``core.gpkg_layer@1``) sin escribirla en el proyecto: sus filas en
un GeoPackage en memoria con la misma estructura, como ``gis.store.table_digest``.

Las pruebas escriben todas las tablas en un proyecto de esquema 2 (``create_project``) y
comparan ``table_digest`` con el hash que calcula el registro de la 008 al leer cada tabla
escrita (``core.datasets.registry``) y con el que da leerla después. Con QGIS
(``GEOBLENDER_QGIS_DIR``), ``ogrinfo`` lista las capas sin avisos; sin él, esa prueba se omite
con «[ENTORNO] qgis».
"""

from __future__ import annotations

import re
import sqlite3
import tempfile
import unittest
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

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

schema = import_geoblender("drillholes.schema")
values = import_geoblender("drillholes.values")
gpkg = import_geoblender("core.gpkg")
base = import_geoblender("core.gpkg.base")
wkb = import_geoblender("core.gpkg.wkb")
georef = import_geoblender("core.georef")
errors = import_geoblender("core.errors")
create = import_geoblender("core.project.create")
open_mod = import_geoblender("core.project.open")
migrations = import_geoblender("core.project.migrations")
project_schema = import_geoblender("core.project.schema")
userdata_mod = import_geoblender("core.userdata")
builtin = import_geoblender("core.content.builtin")
readers = import_geoblender("core.content.readers")
encoder = import_geoblender("core.content.encoder")
dataset_model = import_geoblender("core.datasets.model")
dataset_registry = import_geoblender("core.datasets.registry")
worker_api = import_geoblender("jobs.worker_api")

CATALOG = georef.load_catalog()
CRS = CATALOG.horizontal(25830)
ED50 = CATALOG.horizontal(23030)
SESSION = make_session()
INPUT_UID = "3f2b9c1d-8e7a-4b6c-9d0e-1a2b3c4d5e6f"
PROJECT_UID = "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"
ORDER_NAME = "Campaña Norte 2026 de diamantina — fase «B»"
ORDER_SLUG = "campana_norte_2026_de_diamanti"  # 30 caracteres
BASE = ("dh_collar", "dh_survey", "dh_lithology", "dh_assay", "dh_zone_interval",
        "dh_structure", "dh_lithology_code", "dh_element", "dh_sector", "dh_group", "dh_zone")
COMPUTED = ("dh_trace", "dh_validation_issue", "dh_import_log")
ROLES = ("collar", "survey", "lithology", "assay", "catalog", "zone_interval", "structure")
GEOMETRIES = {"dh_collar": "POINT", "dh_trace": "LINESTRING"}
SINGLE = values.from_single(np.float32(0.1))  # el Single 0,1 de RecMin por su decimal más corto
DOUBLES = (SINGLE, 700_010.5, -60.25)
TEXTS = ("S-12 «Ñandú»", "Pizarra árida (°)", "Calcita")
DATES = ("2026-10-14", "2025-02-28", "2024-12-31")
ROWS = 3


def _value(column: Any, k: int) -> Any:
    """El valor de la fila ``k`` de una columna según su tipo: la segunda fila deja vacías
    (``NULL``) las columnas que lo admiten; los textos, con tildes, «ñ», «°» y comillas."""
    if k == 1 and not column.not_null:
        return None
    if column.name == "extra":
        return ('{"OBSERVACIONES":"señal «ñ»"}', "{}", '{"COTA_ORIGEN":"812,125"}')[k]
    kind = column.sql_type
    if kind == "DOUBLE":
        return DOUBLES[k]
    if kind == "INTEGER":
        return k + 1
    if kind == "BOOLEAN":
        return k % 2
    if kind == "DATE":
        return DATES[k]
    return f"{TEXTS[k]} {column.name}"


def _geometry(layout: Any, k: int, srs: int) -> bytes | None:
    """La geometría de la fila ``k`` de una capa (la segunda boca, sin coordenadas)."""
    if layout.geometry_type == "POINT":
        if k == 1:
            return None
        return wkb.encode_geometry("POINT", np.array([700_010.5 + k, 4_400_020.25, 812.125]),
                                   srs, True)
    xyz = np.array([[700_010.5, 4_400_020.25, 812.125],
                    [700_030.0, 4_400_040.5, 740.0 - k],
                    [700_060.25, 4_400_070.0, 690.5]])
    return wkb.encode_geometry("LINESTRING", xyz, srs, True)


def _rows(layout: Any, srs: int = 25830) -> list[tuple[Any, ...]]:
    """Unas filas sintéticas de la tabla, en el orden de ``layout.insert_columns``; el ``uid``
    de una boca, el determinista de su nombre (``hole_uid``)."""
    rows = []
    for k in range(ROWS):
        row = [_value(column, k) for column in layout.columns]
        if layout.name == "dh_collar":
            names = layout.column_names
            row[names.index("uid")] = schema.hole_uid(PROJECT_UID, row[names.index("name")])
        if layout.geometry_type is not None:
            row.insert(0, _geometry(layout, k, srs))
        rows.append(tuple(row))
    return rows


def _table_name(layout: Any) -> str:
    """El nombre de la tabla de ``layout`` en el proyecto de las pruebas."""
    if layout.source:
        return schema.source_table(layout.role, ORDER_NAME, INPUT_UID)
    return layout.name


def _spec(layout: Any, table: str) -> Any:
    """La declaración del dato de la tabla con que el registro de la 008 la hashea."""
    return dataset_model.DatasetSpec(
        table if not layout.source else schema.source_name(layout.role, ORDER_NAME),
        "dh", layout.kind, dataset_model.Store.GPKG, table,
        reader=builtin.GPKG_LAYER.id, role="data")


def _objects(conn: sqlite3.Connection, pattern: str) -> list[str]:
    """Las tablas cuyo nombre cumple ``pattern`` (``GLOB``: «_» es un «_»)."""
    return [row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name GLOB ? ORDER BY name",
        (pattern,))]


class _Project:
    """Un proyecto real de esquema 2 con todas las tablas de los sondeos escritas por
    ``create_table`` y sus filas sintéticas, y el hash de cada una calculado por el registro
    de la 008 en la transacción que las escribe."""

    def __init__(self, folder: Path) -> None:
        (folder / "proyectos").mkdir()
        created = create.create_project(folder / "proyectos", make_settings(name="Sondeos"),
                                        SESSION, userdata_mod.UserData(folder / "datos"),
                                        clock=FakeClock())
        self.root = created.root
        self.database = created.root / "project.gpkg"
        self.uid = created.project.record.uid
        project = created.project
        with project.read() as conn:
            self.before = _objects(conn, "dh_*")
        self.tables: dict[str, str] = {}
        self.rows: dict[str, list[tuple[Any, ...]]] = {}
        self.registry: dict[str, str] = {}
        with project.write_transaction() as conn:
            for name, layout in schema.LAYOUTS.items():
                table = _table_name(layout)
                rows = _rows(layout)
                schema.create_table(conn, layout, table, CRS.epsg,
                                    description="Z: EPSG:5782" if layout.geometry_type else "")
                schema.insert_rows(conn, layout, table, rows)
                self.tables[name] = table
                self.rows[name] = rows
            for name, layout in schema.LAYOUTS.items():
                self.registry[name] = dataset_registry._computed(
                    conn, project, _spec(layout, self.tables[name]), builtin.GPKG_LAYER.id,
                    encoder.NORMALIZER).content_sha256
        project.close()


class LayoutTest(unittest.TestCase):
    def test_tables_with_their_kind_and_spanish_titles(self) -> None:
        """RF-005-01 (plan §5.2, §5.2.1 y §5.6.1): hay un ``TableLayout`` por cada una de las
        once tablas de la base, las tres de lo calculado y las siete de lo importado (una por
        papel); ``dh_collar`` es una capa ``POINT`` y ``dh_trace`` una ``LINESTRING``, las dos
        con Z, y las demás, tablas; cada columna (salvo ``fid`` y ``geom``) tiene un título en
        español, distinto en su tabla sin distinguir mayúsculas, y ``ALIASES`` los reúne todos;
        ``dh_trace`` y ``dh_validation_issue`` no llevan ``operation_uid`` ni ``stale`` (los da
        la 008) y ``dh_collar`` y ``dh_trace`` llevan ``survey_sha256``. Los nombres de las
        columnas no son palabras de SQL (se escriben sin comillas en QGIS)."""
        self.assertEqual(schema.BASE_TABLES, BASE)
        self.assertEqual(schema.COMPUTED_TABLES, COMPUTED)
        self.assertEqual(schema.SOURCE_ROLES, ROLES)
        self.assertEqual(list(schema.LAYOUTS), [*BASE, *COMPUTED,
                                                *(f"dh_src_{role}" for role in ROLES)])
        aliases: dict[tuple[str, str], str] = {}
        memory = self.enterContext(closing(sqlite3.connect(":memory:")))
        for name, layout in schema.LAYOUTS.items():
            with self.subTest(tabla=name):
                self.assertEqual(layout.name, name)
                self.assertEqual(layout.geometry_type, GEOMETRIES.get(name))
                self.assertEqual(layout.kind, "vector" if name in GEOMETRIES else "table")
                self.assertEqual(layout.has_z, name in GEOMETRIES)
                self.assertEqual(layout.source, name.startswith("dh_src_"))
                names = [column.name for column in layout.columns]
                self.assertEqual(list(layout.titles), names)
                self.assertEqual(layout.insert_columns,
                                 (("geom",) if name in GEOMETRIES else ()) + tuple(names))
                titles = list(layout.titles.values())
                self.assertEqual(len({title.casefold() for title in titles}), len(titles))
                for title in titles:
                    self.assertRegex(title, r"^[A-ZÁÉÍÓÚÑ]")
                memory.execute(f"CREATE TABLE {name} ({', '.join(names)})")
                for column in names:
                    aliases[(name, column)] = layout.titles[column]
        self.assertEqual(dict(schema.ALIASES), aliases)
        for name in ("dh_trace", "dh_validation_issue"):
            names = schema.LAYOUTS[name].column_names
            self.assertNotIn("operation_uid", names)
            self.assertNotIn("stale", names)
        for name in ("dh_collar", "dh_trace"):
            self.assertIn("survey_sha256", schema.LAYOUTS[name].column_names)
        collar = schema.LAYOUTS["dh_collar"]
        self.assertEqual([collar.titles[c] for c in ("name", "depth")],
                         ["Sondeo", "Profundidad (m)"])
        self.assertEqual(schema.LAYOUTS["dh_survey"].titles["azimuth"],
                         "Azimut de cuadrícula (°)")
        self.assertEqual(schema.LAYOUTS["dh_lithology"].titles["from_m"], "Desde (m)")
        self.assertEqual(schema.source_layout("zone_interval"),
                         schema.LAYOUTS["dh_src_zone_interval"])
        with self.assertRaises(ValueError):
            schema.source_layout("dh_collar")

    def test_names_of_the_imported_tables(self) -> None:
        """RF-005-01 (plan §5.6.1): lo importado de una entrada va a
        ``dh_src_<rol>_<nombre>_<entrada8>``, con el nombre de la orden en ASCII en minúsculas
        de 30 caracteres como mucho y las 8 primeras cifras del uid de la entrada: con el papel
        más largo y un nombre largo con tildes, 63 caracteres como mucho (el límite de un
        nombre de tabla) y un identificador válido de ``core.gpkg``; el dato es
        ``dh_src_<rol>_<nombre>``. ``layout_of`` da el ``TableLayout`` de cualquier tabla de los
        sondeos. Un nombre sin letras ni cifras es ``dh.dataset_name_invalid``; un papel o un
        uid que no lo son, ``ValueError``."""
        self.assertEqual(schema.slug("  Campaña 2026 «Norte» "), "campana_2026_norte")
        self.assertEqual(schema.slug("campana_2026"), "campana_2026")
        self.assertEqual(schema.slug("Campaña Norte 2026 de sondeos"),
                         "campana_norte_2026_de_sondeos")
        self.assertEqual(schema.slug("Campaña Norte 2026 de sondeos B"),
                         "campana_norte_2026_de_sondeos")  # sin «_» al final
        long = schema.slug(ORDER_NAME)
        self.assertEqual(long, ORDER_SLUG)
        self.assertEqual(len(long), schema.MAX_SLUG_CHARS)
        self.assertEqual(schema.MAX_SLUG_CHARS, 30)
        for role in ROLES:
            with self.subTest(papel=role):
                table = schema.source_table(role, ORDER_NAME, INPUT_UID)
                self.assertEqual(table, f"dh_src_{role}_{ORDER_SLUG}_3f2b9c1d")
                self.assertEqual(schema.source_name(role, ORDER_NAME),
                                 f"dh_src_{role}_{ORDER_SLUG}")
                self.assertLessEqual(len(table), schema.MAX_TABLE_CHARS)
                self.assertRegex(table, r"^[a-z][a-z0-9_]{0,62}$")
                self.assertIs(schema.layout_of(table), schema.source_layout(role))
        self.assertEqual(schema.MAX_TABLE_CHARS, 63)
        self.assertEqual(len(schema.source_table("zone_interval", ORDER_NAME, INPUT_UID)), 60)
        self.assertEqual(schema.input_tag(INPUT_UID.upper()), "3f2b9c1d")
        for name in (*BASE, *COMPUTED):
            self.assertIs(schema.layout_of(name), schema.LAYOUTS[name])
        for wrong in ("dh_collar_x", "dh_src_collar", "dh_src_nada_x_3f2b9c1d", "gis_pts_x"):
            with self.subTest(tabla=wrong), self.assertRaises(ValueError):
                schema.layout_of(wrong)
        with self.assertRaises(errors.ValidationError) as caught:
            schema.source_table("collar", " «» — ", INPUT_UID)
        self.assertEqual(caught.exception.code, "dh.dataset_name_invalid")
        for role, uid in (("bocas", INPUT_UID), ("collar", "3f2b9c1d"), ("collar", "x" * 36)):
            with self.subTest(papel=role, uid=uid), self.assertRaises(ValueError):
                schema.source_table(role, ORDER_NAME, uid)
        with self.assertRaises(TypeError):
            schema.slug(12)

    def test_hole_uid_is_deterministic(self) -> None:
        """RF-005-01 (plan §5.6.1): el ``uid`` de una boca es el uuid5 del uid del proyecto y
        su nombre sin espacios a los lados ni mayúsculas: el mismo sondeo da el mismo en cada
        reconstrucción de la base («S-12» y « s-12 », iguales), otro sondeo u otro proyecto,
        otro."""
        project = PROJECT_UID
        uid = schema.hole_uid(project, "S-12")
        self.assertEqual(uid, str(uuid.uuid5(uuid.UUID(project), "s-12")))
        self.assertEqual(uuid.UUID(uid).version, 5)
        self.assertEqual(schema.hole_uid(project, " s-12 "), uid)
        self.assertNotEqual(schema.hole_uid(project, "S-13"), uid)
        self.assertNotEqual(schema.hole_uid(str(uuid.uuid4()), "S-12"), uid)
        with self.assertRaises(ValueError):
            schema.hole_uid("no es un uid", "S-12")
        with self.assertRaises(ValueError):
            schema.hole_uid(project, "   ")


class ProjectTablesTest(unittest.TestCase):
    """Las tablas de los sondeos escritas en un proyecto de esquema 2."""

    @classmethod
    def setUpClass(cls) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="gb-005-t37-", ignore_cleanup_errors=True)
        cls.addClassCleanup(tmp.cleanup)
        cls.folder = Path(tmp.name)
        cls.project = _Project(cls.folder)

    def test_each_table_with_its_type_srs_titles_and_indexes(self) -> None:
        """RF-005-01 (plan §5.2.1 y §5.6.1): en el proyecto, ``dh_collar`` es una capa
        ``features`` ``POINT`` y ``dh_trace`` una ``LINESTRING``, las dos con ``z = 1``,
        ``m = 0`` y el SRS del proyecto; las demás, ``attributes`` sin SRS; cada una con sus
        columnas en orden, su identificador «Sondeos…: … (tabla)» y los títulos de su
        ``TableLayout`` en ``gpkg_data_columns`` (``name`` y ``title``). El nombre de una boca
        es único sin distinguir mayúsculas («s-12» no entra junto a «S-12») y un código de
        litología, único en su esquema; un nombre que no es el de su ``TableLayout`` se
        rechaza sin crear nada."""
        project = self.project
        self.assertEqual(project.before, [])
        with gpkg.GpkgConnection.open_read(project.database) as db:
            conn = db.connection
            contents = {row[0]: row[1:] for row in conn.execute(
                "SELECT table_name, data_type, identifier, srs_id FROM gpkg_contents")}
            geometry = {row[0]: row[1:] for row in conn.execute(
                "SELECT table_name, geometry_type_name, srs_id, z, m FROM gpkg_geometry_columns")}
            for name, layout in schema.LAYOUTS.items():
                table = project.tables[name]
                with self.subTest(tabla=table):
                    kind = "features" if layout.geometry_type else "attributes"
                    self.assertEqual(contents[table][0], kind)
                    self.assertEqual(contents[table][1], f"{layout.label} ({table})")
                    self.assertTrue(contents[table][1].startswith(
                        "Sondeos importados: " if layout.source else "Sondeos: "))
                    if layout.geometry_type:
                        self.assertEqual(contents[table][2], CRS.epsg)
                        self.assertEqual(geometry[table], (layout.geometry_type, CRS.epsg, 1, 0))
                    else:
                        self.assertIsNone(contents[table][2])
                        self.assertNotIn(table, geometry)
                    columns = [(row[1], row[2], row[3]) for row in conn.execute(
                        f'PRAGMA table_info("{table}")')]
                    expected = [("fid", "INTEGER", 1)]
                    expected += [("geom", layout.geometry_type, 0)] if layout.geometry_type else []
                    expected += [(c.name, c.sql_type, int(c.not_null)) for c in layout.columns]
                    self.assertEqual(columns, expected)
                    titles = conn.execute(
                        "SELECT column_name, name, title FROM gpkg_data_columns "
                        "WHERE table_name = ? ORDER BY rowid", (table,)).fetchall()
                    self.assertEqual(titles, [(c, t, t) for c, t in layout.titles.items()])
            indexes = {row[0]: row[1] for row in conn.execute(
                "SELECT name, tbl_name FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL")}
            for name, layout in schema.LAYOUTS.items():
                table = project.tables[name]
                found = sorted(index for index, owner in indexes.items() if owner == table)
                wanted = sorted(base.index_name(table, index.columns) for index in layout.indexes)
                self.assertEqual(found, wanted, table)
            keys = [row[2:5] for row in conn.execute(
                'PRAGMA index_xinfo("idx_dh_collar_name")') if row[5]]
            self.assertEqual(keys, [("name", 0, "NOCASE")])
        copy = self.folder / "unicos.gpkg"
        copy.write_bytes(project.database.read_bytes())
        conn = sqlite3.connect(copy)
        try:
            conn.execute("INSERT INTO dh_collar (uid, name, planned, grade_control, input_uid, "
                         "survey_sha256) VALUES ('u-1', 'Z-1', 0, 0, 'e', 'h')")
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO dh_collar (uid, name, planned, grade_control, "
                             "input_uid, survey_sha256) VALUES ('u-2', 'z-1', 0, 0, 'e', 'h')")
            litho = "INSERT INTO dh_lithology_code (code, log_set) VALUES (?, ?)"
            conn.execute(litho, ("CAL", "lithology"))
            conn.execute(litho, ("cal", "recmin_alteracion"))
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(litho, ("cal", "lithology"))
        finally:
            conn.close()
        with gpkg.GpkgConnection.open_write(copy) as db:
            for layout, table, error in (
                (schema.LAYOUTS["dh_collar"], "dh_bocas", ValueError),
                (schema.LAYOUTS["dh_src_collar"], "dh_src_survey_x_3f2b9c1d", ValueError),
                (schema.LAYOUTS["dh_src_collar"], "dh_src_collar", ValueError),
                (schema.LAYOUTS["dh_assay"], "dh_assay", errors.ValidationError),
            ):
                with self.subTest(tabla=table):
                    before = db.connection.execute(
                        "SELECT count(*) FROM sqlite_master").fetchone()
                    with self.assertRaises(error) as caught:
                        with db.transaction() as conn:
                            schema.create_table(conn, layout, table, CRS.epsg)
                    if error is errors.ValidationError:
                        self.assertEqual(caught.exception.code, "dh.table_exists")
                    self.assertEqual(db.connection.execute(
                        "SELECT count(*) FROM sqlite_master").fetchone(), before)
            with self.assertRaises(TypeError), db.transaction() as conn:
                schema.create_table(conn, "dh_survey", "dh_survey", CRS.epsg)

    def test_table_digest_is_the_hash_of_the_008_registry(self) -> None:
        """RF-005-01, RF-005-02 (plan §5.6.1 y §5.6.5; ADR-0024 §5): ``table_digest`` (las
        filas en un GeoPackage en memoria con la misma estructura, leído con
        ``core.gpkg_layer@1``) da, en cada una de las 21 tablas, el hash que calcula el
        registro de la 008 al leer la tabla escrita en el proyecto, en su transacción, y el que
        da leerla después del fichero: con ``NULL``, tildes, comillas, fechas y el Single 0,1
        guardado por su decimal más corto (se lee 0,1 exacto)."""
        project = self.project
        for name, layout in schema.LAYOUTS.items():
            with self.subTest(tabla=name):
                digest = schema.table_digest(layout, project.rows[name], CRS)
                self.assertEqual((digest.reader, digest.normalizer),
                                 (builtin.GPKG_LAYER.id, encoder.NORMALIZER))
                self.assertEqual(digest.content_sha256, project.registry[name])
                request = builtin.GPKG_LAYER.request(
                    layout.kind, {}, {"main": project.database}, {"layer": project.tables[name]})
                self.assertEqual(readers.read_content(builtin.GPKG_LAYER, request).content_sha256,
                                 digest.content_sha256)
        # Sectores y grupos tienen las mismas columnas y aquí las mismas filas: el nombre de la
        # tabla no es contenido. Las demás, cada una el suyo.
        self.assertEqual(project.registry["dh_sector"], project.registry["dh_group"])
        self.assertEqual(len(set(project.registry.values())), len(schema.LAYOUTS) - 1)
        with gpkg.GpkgConnection.open_read(project.database) as db:
            stored = db.connection.execute(
                "SELECT value, reported_value, unit FROM dh_assay ORDER BY fid").fetchall()
            imported = db.connection.execute(
                f'SELECT x, name, start_date FROM "{project.tables["dh_src_collar"]}" '
                "ORDER BY fid").fetchall()
        self.assertEqual([repr(row[0]) for row in stored], ["0.1", "None", "-60.25"])
        self.assertEqual(stored[0][1:], ("S-12 «Ñandú» reported_value", "S-12 «Ñandú» unit"))
        self.assertEqual(stored[1][1:], (None, "Pizarra árida (°) unit"))
        self.assertEqual(imported, [(0.1, "S-12 «Ñandú» name", "2026-10-14"),
                                    (None, "Pizarra árida (°) name", None),
                                    (-60.25, "Calcita name", "2024-12-31")])

    def test_same_rows_same_hash(self) -> None:
        """RF-005-01, RF-005-02 (plan §5.6.1; RF-008-26): las mismas filas dos veces dan el
        mismo hash, también en otro orden y con otros ``fid`` (el número interno no es
        contenido; el ``uid`` de cada boca, el determinista de su nombre); un Single guardado
        sin su decimal más corto (0,10000000149011612), una boca con otro ``uid`` o una Z
        distinta, otro hash; el hash de una tabla sin geometría no depende del CRS."""
        for name in ("dh_collar", "dh_assay", "dh_src_survey"):
            layout = schema.LAYOUTS[name]
            rows = _rows(layout)
            with self.subTest(tabla=name):
                first = schema.table_digest(layout, rows, CRS)
                self.assertEqual(schema.table_digest(layout, _rows(layout), CRS), first)
                self.assertEqual(schema.table_digest(layout, list(reversed(rows)), CRS), first)
        layout = schema.LAYOUTS["dh_assay"]
        rows = _rows(layout)
        k = layout.insert_columns.index("from_m")
        self.assertEqual(rows[0][k], SINGLE)
        widened = [rows[0][:k] + (float(np.float32(0.1)),) + rows[0][k + 1:], *rows[1:]]
        self.assertNotEqual(schema.table_digest(layout, widened, CRS),
                            schema.table_digest(layout, rows, CRS))
        self.assertEqual(schema.table_digest(layout, rows, ED50),
                         schema.table_digest(layout, rows, CRS))
        collar = schema.LAYOUTS["dh_collar"]
        rows = _rows(collar)
        uid = collar.insert_columns.index("uid")
        other = [rows[0][:uid] + ("otro",) + rows[0][uid + 1:], *rows[1:]]
        self.assertNotEqual(schema.table_digest(collar, other, CRS),
                            schema.table_digest(collar, rows, CRS))
        lifted = wkb.encode_geometry("POINT", np.array([700_010.5, 4_400_020.25, 812.25]),
                                     25830, True)
        self.assertNotEqual(schema.table_digest(collar, [(lifted, *rows[0][1:]), *rows[1:]], CRS),
                            schema.table_digest(collar, rows, CRS))

    def test_digest_progress_cancel_and_errors(self) -> None:
        """RF-005-01 (plan §5.6.7: el hash de cada tabla se calcula en el trabajo):
        ``table_digest`` da su avance tras cada trozo y para con ``JobCancelled`` si se pide
        entre trozos; un ``TableLayout`` o un CRS de otro tipo, ``TypeError``; una fila con
        otro número de valores, ``ValueError``."""
        layout = schema.LAYOUTS["dh_survey"]
        rows = _rows(layout) * 40
        seen: list[float] = []
        schema.table_digest(layout, rows, CRS, progress=lambda done, text: seen.append(done))
        self.assertTrue(seen)
        self.assertEqual(seen[-1], 1.0)
        self.assertEqual(seen, sorted(seen))
        with self.assertRaises(worker_api.JobCancelled):
            schema.table_digest(layout, rows, CRS, cancelled=lambda: True)
        with self.assertRaises(TypeError):
            schema.table_digest("dh_survey", rows, CRS)
        with self.assertRaises(TypeError):
            schema.table_digest(layout, rows, 25830)
        with self.assertRaises(ValueError):
            schema.table_digest(layout, [rows[0][:-1]], CRS)

    @requires(qgis.QGIS, qgis.QGIS_HINT)
    def test_ogrinfo_lists_collars_and_traces_without_warnings(self) -> None:
        """RF-005-01: ``ogrinfo -ro -so -al`` del GDAL de QGIS 4.2 termina con 0, sin ninguna
        línea con «Warning» ni «ERROR»; lista ``dh_collar`` como ``3D Point`` y ``dh_trace``
        como ``3D Line String`` en EPSG:25830 y las demás tablas sin geometría, con el nombre
        alternativo (el título) de cada campo."""
        info = qgis.run_tool("ogrinfo", "-ro", "-so", "-al", str(self.project.database))
        output = qgis.output_of(info)
        self.assertEqual(info.returncode, 0, output)
        noisy = [line for line in output.splitlines()
                 if "warning" in line.lower() or "ERROR" in line]
        self.assertEqual(noisy, [], output[:4000])
        layers = {block.split("\n", 1)[0]: block
                  for block in output.split("\nLayer name: ")[1:]}
        self.assertEqual(sorted(layers), sorted(self.project.tables.values()))
        for name, layout in schema.LAYOUTS.items():
            table = self.project.tables[name]
            block = layers[table]
            with self.subTest(tabla=table):
                geometry = re.findall(r"\nGeometry: (.+)\n", block)
                self.assertEqual(geometry, [{"dh_collar": "3D Point",
                                             "dh_trace": "3D Line String"}.get(name, "None")])
                if layout.geometry_type:
                    self.assertIn('ID["EPSG",25830]]\n', block)
                for column, title in layout.titles.items():
                    self.assertRegex(block, rf'\n{column}: \S+( \(\d+\.\d+\))?( UNIQUE)?'
                                            rf'( NOT NULL)?( DEFAULT [^,\n]+)?, '
                                            rf'alternative name="{re.escape(title)}"\n')


class NoTablesUntilWrittenTest(unittest.TestCase):
    def test_no_table_when_creating_opening_or_migrating(self) -> None:
        """RF-005-01, RF-008-62 (plan §5.6.1: sin paso de esquema): crear un proyecto, abrirlo y
        migrar uno del esquema 1 no crea ninguna tabla de los sondeos (se crean al escribirlas)
        ni cambia el esquema: queda en el de esta versión (el 3 desde la spec 009), que la 005
        no sube."""
        with project_tmp() as tmp:
            userdata = userdata_mod.UserData(tmp / "datos")
            (tmp / "p").mkdir()
            created = create.create_project(tmp / "p", make_settings(name="Sin sondeos"), SESSION,
                                            userdata, clock=FakeClock())
            created.project.close()
            root = created.root
            opened = open_mod.open_project(root, SESSION, userdata, clock=FakeClock(),
                                           pid_alive=FakePids({SESSION.pid}))
            opened.project.close()
            make_schema_1(root)
            list(migrations.migrate_steps(root, SESSION, userdata, clock=FakeClock(),
                                          pid_alive=FakePids({SESSION.pid})))
            with gpkg.GpkgConnection.open_read(root / "project.gpkg") as db:
                conn = db.connection
                self.assertEqual(_objects(conn, "dh_*"), [])
                self.assertEqual(conn.execute("SELECT schema_version FROM gb_project")
                                 .fetchone()[0], project_schema.SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
