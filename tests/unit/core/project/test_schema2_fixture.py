# SPDX-License-Identifier: GPL-3.0-or-later
"""El proyecto del esquema 2 de prueba (spec 009, T03; RF-009-02, RF-009-23; plan 009 §7.1).

``tests/data/core/projects/esquema2.zip`` lo escribió ``tests/support/schema2_project.py`` con
el código de partida, antes de cualquier cambio de la 009: la ida de la migración ``m0003``
(T04) y las comprobaciones de las instantáneas (RF-009-23) parten de él. Aquí se comprueba que
es lo que dice su generador: su huella (la anotada en el docstring y en el README), que se
descomprime en una carpeta temporal y abre con el esquema 2, que tiene los datos de la 005, la
006 y la 008 con sus ficheros, sus entradas y su vista, y que no lleva nada del equipo que lo
generó (su sesión es la sintética).
"""

import hashlib
import json
import sqlite3
import unittest
from pathlib import Path

from tests.support import schema2_project as fixture
from tests.support.core_fixtures import make_session, project_tmp
from tests.support.package import import_geoblender

open_mod = import_geoblender("core.project.open")
schema = import_geoblender("core.project.schema")
inputs = import_geoblender("core.inputs")
userdata_mod = import_geoblender("core.userdata")

SESSION = make_session()
USER_HOST = "prueba@PC-PRUEBA-A"
README = fixture.DATA_DIR / "README.md"
DEMO_OPERATIONS = ("demo.area", "demo.digitize", "demo.bench_years", "demo.detect_stockpiles",
                   "demo.filter_stockpiles", "demo.balance")
GIS_OPERATIONS = ("gis.import_dtm", "gis.resample")
DH_OPERATIONS = ("dh.import_tabular", "dh.build_base", "dh.validate", "dh.desurvey")
DEMO_DATASETS = ("demo_benches", "demo_marks", "demo_bench_years", "demo_stockpile_candidates",
                 "demo_stockpiles")
GIS_DATASETS = ("gis_src_mdt", "gis_dtm_mdt")
DH_HOLES = ("C-01", "S-01", "S-02", "S-03", "S-04", "S-12")
SCHEMA_2_TABLES = ("gb_project", "gb_event", "gb_schema_migration", "gb_parameter",
                   "gb_parameter_history", "gb_input", "gb_input_file", "gb_dataset",
                   "gb_dataset_change", "gb_operation", "gb_operation_io", "gb_operation_param",
                   "gb_figure", "gb_stale", "gb_ignored")
"""Las tablas internas del esquema 2 (las del 1 y las de la procedencia de la 008)."""
BOUNDARY_HA = 12.0  # el área de Limites_v1 (tests/data/core/provenance/README.md)
# Lo que delataría el equipo que lo generó: la carpeta temporal de Windows y la del generador.
MACHINE_MARKERS = (b"AppData", b"gb-s2-", b"gb-s2e-", b"gb_tests")
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
BLEND_MAGICS = (b"BLENDER", ZSTD_MAGIC)
"""Un ``.blend`` empieza por «BLENDER» o, comprimido (lo que guarda Blender 5.2), es zstd."""


def _blend_bytes(path: Path) -> bytes | None:
    """El ``.blend`` ``path`` sin comprimir; ``None`` si está comprimido y este Python no trae
    ``zstandard`` (el de Blender lo trae; con ``-S``, el paso «motor» de ``check.py``, no: el
    zip es el de su huella, así que basta con haberlo comprobado con el de Blender)."""
    data = path.read_bytes()
    if not data.startswith(ZSTD_MAGIC):
        return data
    try:
        import zstandard
    except ImportError:
        return None
    return zstandard.ZstdDecompressor().stream_reader(data).read()


class Schema2FixtureTest(unittest.TestCase):
    """El zip descomprimido una vez en una carpeta temporal, abierto en solo lectura."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = cls.enterClassContext(project_tmp("gb-s2t-"))
        cls.root = fixture.extract(cls.tmp)
        cls.userdata = userdata_mod.UserData(cls.tmp / "u")
        cls.inspection = open_mod.inspect_project(cls.root, SESSION, cls.userdata)
        cls.project = open_mod.open_project(cls.root, SESSION, cls.userdata,
                                            want_write=False).project
        cls.addClassCleanup(cls.project.close)

    def rows(self, sql: str, *args: object) -> list[tuple]:
        with self.project.read() as conn:
            return conn.execute(sql, args).fetchall()

    def test_its_fingerprint_is_the_annotated_one(self) -> None:
        """RF-009-23, RF-009-02 (T03): el zip pesa como mucho 2 MiB y su tamaño y su sha256 son
        los de su generador, que los anota en su docstring y en la línea de
        ``tests/data/core/projects/README.md``."""
        data = fixture.ZIP_PATH.read_bytes()
        self.assertLessEqual(len(data), fixture.MAX_ZIP_BYTES)
        self.assertEqual((len(data), hashlib.sha256(data).hexdigest()),
                         (fixture.ZIP_BYTES, fixture.ZIP_SHA256))
        self.assertIn(fixture.ZIP_SHA256, fixture.__doc__ or "")
        self.assertIn(f"{fixture.ZIP_BYTES:,}".replace(",", " "), fixture.__doc__ or "")
        line = f"| `esquema2.zip` | {fixture.ZIP_BYTES} | `{fixture.ZIP_SHA256}` |"
        self.assertIn(line, README.read_text(encoding="utf-8").splitlines())

    def test_it_opens_with_schema_2(self) -> None:
        """RF-009-02 (T03): descomprimido, es un proyecto cerrado del esquema 2 creado en él
        (sin migraciones), con la cabecera de acuerdo con la base y el diario clásico; se abre
        (en solo lectura, como lo abrirá cualquier versión posterior) con su CRS y su ventana.
        Con el código del esquema 2 es «el mismo esquema»; con uno posterior, «anterior»."""
        record = self.project.record
        self.assertEqual((record.schema_version, self.project.manifest.schema_version),
                         (fixture.SCHEMA, fixture.SCHEMA))
        self.assertEqual(self.inspection.migrations, ())
        expected = (open_mod.SchemaRelation.SAME if schema.SCHEMA_VERSION == fixture.SCHEMA
                    else open_mod.SchemaRelation.OLDER)
        self.assertEqual(self.inspection.schema, expected)
        self.assertIsNotNone(self.inspection.check)
        self.assertEqual(self.inspection.check.differences, ())
        self.assertEqual(self.inspection.lock.state.value, "free")
        self.assertEqual((record.name, record.crs_epsg, record.vcrs_epsg),
                         (fixture.PROJECT_NAME, 25830, 5782))
        self.assertEqual(self.rows("PRAGMA journal_mode"), [("delete",)])
        files = {path.name for path in self.root.iterdir()}
        self.assertNotIn(".lock", files)
        self.assertNotIn("project.gpkg-journal", files)
        self.assertNotIn("cache", files)

    def test_it_has_the_data_of_005_006_and_008(self) -> None:
        """RF-009-02, RF-009-23 (T03): las operaciones de la cadena de la demostración (008), del
        MDT y su rejilla del proyecto (006) y de los sondeos de ``csv_basico`` con sus trazas
        (005), todas hechas; sus datos vivos, con su fichero en ``rasters/`` los de la 006; el
        área del límite, 12 ha; la fracción mínima que leyó la rejilla; los seis sondeos con su
        traza; ocho entradas (el límite, el MDT y seis tablas), cada una con su fichero en
        ``fuentes/`` y su huella; y la vista ``scenes/principal.blend``."""
        operations = dict(self.rows(
            "SELECT op_type, count(*) FROM gb_operation WHERE status = 'done' GROUP BY op_type"))
        for op_type in (*DEMO_OPERATIONS, *GIS_OPERATIONS, *DH_OPERATIONS):
            with self.subTest(operacion=op_type):
                self.assertGreaterEqual(operations.get(op_type, 0), 1)
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation WHERE status <> 'done'"),
                         [(0,)])
        live = dict(self.rows("SELECT name, locator FROM gb_dataset WHERE status = 'current'"))
        for name in (*DEMO_DATASETS, *GIS_DATASETS, "dh_collar"):
            with self.subTest(dato=name):
                self.assertIn(name, live)
        for name in GIS_DATASETS:
            with self.subTest(fichero=name):
                self.assertTrue(live[name].startswith("rasters/"))
                self.assertTrue((self.root / live[name]).is_file())
        (area,) = self.rows("SELECT value, unit FROM gb_figure WHERE key = 'demo.boundary_area'")
        self.assertAlmostEqual(area[0], BOUNDARY_HA, places=9)
        self.assertEqual(area[1], "ha")
        self.assertEqual(self.rows("SELECT key FROM gb_operation_param AS p JOIN gb_operation AS o "
                                   "ON o.uid = p.operation_uid WHERE o.op_type = 'gis.resample'"),
                         [("gis.resample.min_valid_fraction",)])
        holes = [row[0] for row in self.rows("SELECT name FROM dh_collar ORDER BY name")]
        self.assertEqual(tuple(holes), DH_HOLES)
        traces = self.rows("SELECT count(DISTINCT hole_id) FROM dh_trace")
        self.assertEqual(traces, [(len(DH_HOLES),)])
        self.assertTrue((self.root / fixture.VIEW).read_bytes().startswith(BLEND_MAGICS))
        blend = _blend_bytes(self.root / fixture.VIEW)
        if blend is not None:
            self.assertTrue(blend.startswith(b"BLENDER"))

        sources = self.tmp / fixture.SOURCES_FOLDER
        files = self.rows("SELECT i.name, f.anchor, f.path, f.sha256 FROM gb_input AS i "
                          "JOIN gb_input_file AS f ON f.input_uid = i.uid ORDER BY i.fid, f.ord")
        self.assertEqual(len({name for name, *_ in files}), 8)
        for name, anchor, path, digest in files:
            with self.subTest(entrada=name):
                self.assertEqual(anchor, "original")
                found = inputs.resolve_source(
                    inputs.SourceFile(path, "main", anchor), self.project, self.userdata)
                self.assertEqual(found.parent.resolve(), sources.resolve())
                self.assertEqual(hashlib.sha256(found.read_bytes()).hexdigest(), digest)

    def test_nothing_of_the_machine_that_made_it(self) -> None:
        """RF-009-23 (T03; ningún dato del equipo que lo generó): cada evento y cada
        operación, con la sesión sintética de las pruebas; ninguna ruta absoluta en la cabecera
        ni en las rutas de las entradas y los datos (así sigue valiendo copiado a otra carpeta);
        y ningún fichero, tampoco la vista sin comprimir, lleva la carpeta temporal de Windows
        ni las del generador."""
        users = {row[0] for row in self.rows("SELECT user_host FROM gb_event")}
        self.assertEqual(users, {USER_HOST})
        self.assertEqual(set(self.rows("SELECT user_host, host, session_uid FROM gb_operation")),
                         {(USER_HOST, "PC-PRUEBA-A", SESSION.session_uid)})
        manifest = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
        self.assertNotIn(":\\", json.dumps(manifest, ensure_ascii=False))
        for (path,) in self.rows("SELECT path FROM gb_input_file UNION ALL "
                                 "SELECT locator FROM gb_dataset"):
            with self.subTest(ruta=path):
                self.assertFalse(Path(path).is_absolute() or ":" in path)
        for path in sorted(self.tmp.rglob("*")):
            if not path.is_file() or path.is_relative_to(self.tmp / "u"):
                continue
            data = path.read_bytes()
            if path.suffix == ".blend":
                data = _blend_bytes(path) or data
            for marker in MACHINE_MARKERS:
                for encoded in (marker, marker.decode().encode("utf-16-le")):
                    with self.subTest(fichero=path.relative_to(self.tmp).as_posix(),
                                      marca=marker):
                        self.assertNotIn(encoded, data)

    def test_no_wal_and_internal_tables_of_schema_2(self) -> None:
        """RF-009-23 (T03): la base del zip tiene las tablas internas del esquema 2 y ninguna
        más de Geoblender (``gb_version`` y las demás de la 009 aún no existen), sin WAL en su
        cabecera (bytes 18 y 19 a 1)."""
        database = self.root / "project.gpkg"
        header = database.read_bytes()[:100]
        self.assertEqual((header[18], header[19]), (1, 1))
        conn = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
        try:
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'gb\\_%' "
                "ESCAPE '\\'")}
        finally:
            conn.close()
        self.assertEqual(tables, set(SCHEMA_2_TABLES))


if __name__ == "__main__":
    unittest.main()
