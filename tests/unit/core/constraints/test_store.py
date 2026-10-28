# SPDX-License-Identifier: GPL-3.0-or-later
"""Las tablas del proyecto de las restricciones (spec 012, T06; HU-012-2; RF-012-01, RF-012-03,
RF-012-07, RF-012-09, RF-012-26; plan 012 §5.2.1, §5.3.1, D-20, D-21, D-22 y D-35).

``core.constraints.store`` crea, en la transacción que las escribe por primera vez y con
``execute`` (nunca ``executescript``, que confirma), las siete tablas de §5.2.1: las tres capas
de restricciones (``core_constraint_polygon``, ``_line`` y ``_point``, editables en QGIS),
``core_intention``, ``core_sector``, ``core_untouchable_search`` y ``core_untouchable_hit``;
escribe y lee sus filas con la geometría **absoluta en float64** (``core.gpkg.wkb``), que vuelve
bit a bit; pone en el tipo la lista de valores de los once tipos con su español (D-35) y
declara sus datos (``dataset_specs``: las tres capas, editables en QGIS; lo demás, no).

Una fila escrita desde una conexión **sin** ``gb_writer()`` (como QGIS) entra con sus valores
por defecto y se lee como incompleta; un ``ctype`` fuera de la lista se rechaza; un código
repetido en las tres capas se lee y queda «no válida» (``checks.incomplete``).
"""

from __future__ import annotations

import json
import re
import sqlite3
import unittest
from datetime import date

import numpy as np

from tests.support import constraints_fixtures as fx
from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender

gpkg = import_geoblender("core.gpkg")
base = import_geoblender("core.gpkg.base")
wkb = import_geoblender("core.gpkg.wkb")
model = import_geoblender("core.constraints.model")
checks = import_geoblender("core.constraints.checks")
messages = import_geoblender("core.constraints.messages")
store = import_geoblender("core.constraints.store")
datasets = import_geoblender("core.datasets")

T = model.ConstraintType
G = model.GeometryKind
SRS = fx.SRS_ID
LAYERS = ("core_constraint_polygon", "core_constraint_line", "core_constraint_point")
SEVEN = LAYERS + ("core_intention", "core_sector", "core_untouchable_search",
                  "core_untouchable_hit")
# Coordenadas con decimales que float32 perdería (y una mitad exacta).
ODD = (0.123456789012, 0.987654321098)


def _new(path):
    db = gpkg.GpkgConnection.open_write(path, create=True)
    with db.transaction() as conn:
        base.create_base(conn, fx.CRS)
    return db


def _with_tables(path):
    db = _new(path)
    with db.transaction() as conn:
        store.create_tables(conn, SRS)
    return db


def _ring(left: float, bottom: float, right: float, top: float) -> np.ndarray:
    ring = fx.rectangle(left, bottom, right, top)
    ring = ring + np.array(ODD)
    ring[-1] = ring[0]
    return ring


def _polygon_parts():
    """Dos partes: un cuadrado con un hueco y otro cuadrado."""
    outer = _ring(0, 0, 100, 100)
    hole = _ring(40, 40, 60, 60)[::-1].copy()
    return ((outer, hole), (_ring(150, 0, 170, 20),))


def _constraint(code: str, kind, parts, *, fid: int = 0, **changes):
    kind = G(kind)
    fields = {
        "uid": (code + "0" * 32)[:32], "code": code, "name": f"Restricción {code}",
        "ctype": T.UNTOUCHABLE, "kind": kind, "parts": parts, "priority": 2,
        "reason": "Servidumbre de la línea", "decided_by": "Propiedad",
        "decided_on": date(2026, 10, 2), "decision_uid": "d" * 32, "intention_uid": None,
        "source_input": "i" * 32, "source_fid": 7, "layer": store.layer_of(kind), "fid": fid,
    }
    fields.update(changes)
    return model.Constraint(**fields)


def _three():
    line = (fx.absolute([(0, 0), (50, 10), (80, -5)]) + np.array(ODD),)
    point = (fx.absolute([(186, 100)]) + np.array(ODD),)
    return (
        _constraint("vivienda", G.POLYGON, _polygon_parts(), ctype=T.LEGAL_LIMIT),
        _constraint("camino", G.LINE, (line,), ctype=T.SETBACK, decided_on=None,
                    decision_uid=None, source_input=None, source_fid=None),
        _constraint("torre", G.POINT, (point,)),
    )


def _same_geometry(test: unittest.TestCase, got, expected) -> None:
    test.assertEqual(len(got), len(expected))
    for got_part, part in zip(got, expected, strict=True):
        test.assertEqual(len(got_part), len(part))
        for got_coords, coords in zip(got_part, part, strict=True):
            test.assertEqual(got_coords.dtype, np.float64)
            test.assertEqual(got_coords.shape, coords.shape)
            test.assertEqual(got_coords.tobytes(), np.asarray(coords, np.float64).tobytes())


class TablesTest(unittest.TestCase):
    def test_seven_tables_in_one_transaction(self) -> None:
        """RF-012-01, RF-012-03 (plan §5.2.1): las siete tablas se crean dentro de la
        transacción del que escribe (si esta se deshace, no queda ninguna); las cinco con
        geometría van a ``gpkg_contents`` y ``gpkg_geometry_columns`` con su tipo (2D, CRS del
        proyecto) y las dos de búsquedas como tablas de atributos; crearlas otra vez no hace
        nada; la base sigue íntegra."""
        with project_tmp() as tmp, _new(tmp / "p.gpkg") as db:
            with self.assertRaises(RuntimeError), db.transaction() as conn:
                self.assertEqual(store.create_tables(conn, SRS), SEVEN)
                raise RuntimeError("se deshace")
            conn = db.connection
            names = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
            self.assertEqual(names & set(SEVEN), set())
            with db.transaction() as conn:
                self.assertEqual(store.create_tables(conn, SRS), SEVEN)
            with db.transaction() as conn:
                self.assertEqual(store.create_tables(conn, SRS), ())
            conn = db.connection
            self.assertEqual(store.TABLES, SEVEN)
            contents = dict(conn.execute(
                "SELECT table_name, data_type FROM gpkg_contents WHERE table_name LIKE 'core_%'"))
            self.assertEqual(contents, {
                **{name: "features" for name in SEVEN[:5]},
                "core_untouchable_search": "attributes", "core_untouchable_hit": "attributes"})
            geometry = {row[0]: row[1:] for row in conn.execute(
                "SELECT table_name, geometry_type_name, srs_id, z, m FROM gpkg_geometry_columns")}
            self.assertEqual(geometry, {
                "core_constraint_polygon": ("MULTIPOLYGON", SRS, 0, 0),
                "core_constraint_line": ("MULTILINESTRING", SRS, 0, 0),
                "core_constraint_point": ("MULTIPOINT", SRS, 0, 0),
                "core_intention": ("GEOMETRY", SRS, 0, 0),
                "core_sector": ("MULTIPOLYGON", SRS, 0, 0)})
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_type_value_list_in_spanish(self) -> None:
        """RF-012-03, D-35: ``gpkg_data_column_constraints`` tiene una lista ``enum`` con los
        once códigos y su texto español (el de ``ConstraintType.label``), y la columna
        ``ctype`` de las tres capas la nombra."""
        with project_tmp() as tmp, _with_tables(tmp / "p.gpkg") as db:
            conn = db.connection
            rows = conn.execute(
                "SELECT constraint_name, constraint_type, value, description "
                "FROM gpkg_data_column_constraints ORDER BY rowid").fetchall()
            self.assertEqual(rows, [(store.CTYPE_ENUM, "enum", ctype.value, ctype.label("es"))
                                    for ctype in T])
            self.assertEqual(len(rows), 11)
            self.assertEqual({value: text for _n, _t, value, text in rows}["setback"],
                             "Banda de resguardo")
            links = conn.execute("SELECT table_name, constraint_name FROM gpkg_data_columns "
                                 "WHERE column_name = 'ctype' ORDER BY table_name").fetchall()
            self.assertEqual(links, sorted((name, store.CTYPE_ENUM) for name in LAYERS))

    def test_dataset_specs(self) -> None:
        """RF-008-56 (plan §5.2.1): un dato de ``core`` por tabla, con su nombre, del proyecto y
        con ``core.gpkg_layer@1``; las tres capas de restricciones, editables en QGIS; las
        intenciones, los sectores y las búsquedas, no."""
        specs = store.dataset_specs(crs_epsg=SRS)
        self.assertEqual(tuple(spec.name for spec in specs), SEVEN)
        for spec in specs:
            with self.subTest(spec.name):
                self.assertIsInstance(spec, datasets.DatasetSpec)
                self.assertEqual((spec.module, spec.store, spec.locator, spec.reader),
                                 ("core", datasets.Store.GPKG, spec.name, "core.gpkg_layer@1"))
                self.assertEqual(spec.qgis_editable, spec.name in LAYERS)
                self.assertEqual(spec.kind, "table" if "untouchable" in spec.name else "vector")


class ConstraintRowsTest(unittest.TestCase):
    def test_round_trip_bit_for_bit(self) -> None:
        """RF-012-01: un polígono con hueco (y otra parte), una línea y un punto se escriben
        en su capa y vuelven con sus campos y su geometría absoluta float64 bit a bit; cada
        uno recibe su fid; se leen por capa (polígonos, líneas, puntos) y fid."""
        with project_tmp() as tmp, _with_tables(tmp / "p.gpkg") as db:
            written = _three()
            with db.transaction() as conn:
                fids = store.write_constraints(conn, written, srs_id=SRS)
            self.assertEqual(fids, (1, 1, 1))
            read = store.read_constraints(db.connection)
            self.assertEqual([item.layer for item in read], list(LAYERS))
            for got, item in zip(read, written, strict=True):
                with self.subTest(item.code):
                    for name in ("uid", "code", "name", "ctype", "kind", "priority", "reason",
                                 "decided_by", "decided_on", "decision_uid", "intention_uid",
                                 "source_input", "source_fid"):
                        self.assertEqual(getattr(got, name), getattr(item, name), name)
                    self.assertEqual(got.fid, 1)
                    _same_geometry(self, got.parts, item.parts)
            blob = db.connection.execute(
                "SELECT geom FROM core_constraint_polygon").fetchone()[0]
            decoded = wkb.decode_geometry(blob)
            self.assertEqual((decoded.geometry_type, decoded.srs_id, decoded.has_z),
                             ("MULTIPOLYGON", SRS, False))

    def test_update_keeps_the_code(self) -> None:
        """D-22: reescribir una restricción por su fid cambia sus campos; su código es
        inmutable (otro código se rechaza) y único en las tres capas al escribir."""
        with project_tmp() as tmp, _with_tables(tmp / "p.gpkg") as db:
            first, line, point = _three()
            with db.transaction() as conn:
                store.write_constraints(conn, (first, line, point), srs_id=SRS)
            renamed = _constraint("vivienda", G.POLYGON, _polygon_parts(), fid=1,
                                  ctype=T.LEGAL_LIMIT, name="Vivienda del guarda", priority=5)
            with db.transaction() as conn:
                self.assertEqual(store.write_constraints(conn, (renamed,), srs_id=SRS), (1,))
            got = store.read_constraints(db.connection)[0]
            self.assertEqual((got.name, got.priority, got.code), ("Vivienda del guarda", 5,
                                                                  "vivienda"))
            cases = {
                "core.constraint_code_immutable": _constraint(
                    "casa", G.POLYGON, _polygon_parts(), fid=1, uid=first.uid),
                "core.constraint_code_taken": _constraint(
                    "torre", G.POLYGON, _polygon_parts(), uid="e" * 32),
            }
            for code, row in cases.items():
                with self.subTest(code):
                    with self.assertRaises(messages.ConstraintError) as caught:
                        with db.transaction() as conn:
                            store.write_constraints(conn, (row,), srs_id=SRS)
                    self.assertEqual(caught.exception.code, code)
            self.assertEqual(len(store.read_constraints(db.connection)), 3)

    def test_row_from_qgis_gets_defaults_and_is_incomplete(self) -> None:
        """RF-012-03, RF-012-04: una fila escrita desde una conexión sin ``gb_writer()`` (como
        QGIS) con solo su geometría entra con su ``uid`` aleatorio, código y nombre vacíos, sin
        tipo y prioridad 0, y se lee como incompleta (sin código, tipo, motivo ni decisor)."""
        with project_tmp() as tmp:
            path = tmp / "p.gpkg"
            _with_tables(path).close()
            outside = sqlite3.connect(path)
            try:
                with self.assertRaises(sqlite3.OperationalError):
                    outside.execute("SELECT gb_writer()")
                blob = wkb.encode_geometry("MULTIPOLYGON", [[_ring(0, 0, 10, 10)]], SRS, False)
                outside.execute("INSERT INTO core_constraint_polygon (geom) VALUES (?)", (blob,))
                outside.commit()
            finally:
                outside.close()
            with gpkg.GpkgConnection.open_read(path) as db:
                (row,) = store.read_constraints(db.connection)
            self.assertRegex(row.uid, re.compile(r"[0-9a-f]{32}"))
            self.assertEqual((row.code, row.name, row.ctype, row.priority, row.reason,
                              row.decided_by, row.source_input, row.fid),
                             ("", "", None, 0, None, None, None, 1))
            problems = [item.problem for item in checks.incomplete((row,), {})]
            self.assertEqual(problems, ["core.constraint_no_code", "core.constraint_no_type",
                                        "core.constraint_no_reason",
                                        "core.constraint_no_decider"])

    def test_type_outside_the_list_is_rejected(self) -> None:
        """RF-012-03: un ``ctype`` que no es uno de los once lo rechaza la propia tabla
        (``CHECK``), también desde una conexión sin ``gb_writer()``; nada queda escrito."""
        with project_tmp() as tmp:
            path = tmp / "p.gpkg"
            _with_tables(path).close()
            outside = sqlite3.connect(path)
            try:
                for table in LAYERS:
                    with self.subTest(table), self.assertRaises(sqlite3.IntegrityError):
                        outside.execute(f"INSERT INTO {table} (ctype) VALUES ('tower')")
                outside.execute("INSERT INTO core_constraint_line (ctype) VALUES ('no_fill')")
                outside.commit()
                self.assertEqual(outside.execute(
                    "SELECT count(*) FROM core_constraint_polygon").fetchone()[0], 0)
            finally:
                outside.close()

    def test_code_repeated_across_layers_is_not_valid(self) -> None:
        """D-22: el código es único en las tres capas al leer; dos filas con el mismo (una
        copiada en QGIS a otra capa) se leen las dos y las dos quedan «no válidas»
        (``core.constraint_code_repeated``)."""
        with project_tmp() as tmp:
            path = tmp / "p.gpkg"
            db = _with_tables(path)
            with db, db.transaction() as conn:
                store.write_constraints(conn, _three(), srs_id=SRS)
            outside = sqlite3.connect(path)
            try:
                outside.execute("UPDATE core_constraint_point SET code = 'vivienda'")
                outside.commit()
            finally:
                outside.close()
            with gpkg.GpkgConnection.open_read(path) as db:
                read = store.read_constraints(db.connection)
            repeated = [(item.layer, item.problem) for item in checks.incomplete(read, {})
                        if item.problem == "core.constraint_code_repeated"]
            self.assertEqual(repeated, [("core_constraint_polygon",
                                         "core.constraint_code_repeated"),
                                        ("core_constraint_point",
                                         "core.constraint_code_repeated")])

    def test_no_tables_reads_nothing(self) -> None:
        """Un proyecto sin las tablas (nadie ha escrito restricciones) no tiene ninguna."""
        with project_tmp() as tmp, _new(tmp / "p.gpkg") as db:
            conn = db.connection
            self.assertEqual(store.read_constraints(conn), ())
            self.assertEqual(store.read_intentions(conn), ())
            self.assertEqual(store.read_sectors(conn), ())
            self.assertEqual(store.read_searches(conn), ())
            self.assertEqual(store.read_hits(conn), ())


class OtherRowsTest(unittest.TestCase):
    def test_intentions_round_trip(self) -> None:
        """RF-012-26: las intenciones (un punto, una línea y un polígono con hueco en la misma
        capa ``GEOMETRY``) vuelven con su rol, su cota (solo «explotar a una cota»), fecha,
        documento, decisión y origen, y su geometría absoluta bit a bit."""
        point = (fx.absolute([(10, 10)]) + np.array(ODD),)
        line = (fx.absolute([(0, 0), (30, 40)]) + np.array(ODD),)
        written = (
            model.Intention("a" * 32, "Pozo", "protect", G.POINT, (point,), None,
                            date(2026, 9, 1), "doc1", None, "src", 1, 0),
            model.Intention("b" * 32, "Camino", "keep_as_is", G.LINE, (line,), None,
                            date(2026, 9, 1), "doc1", "d" * 32, "src", 2, 0),
            model.Intention("c" * 32, "Hueco", "mine_to_elevation", G.POLYGON,
                            _polygon_parts(), fx.MINE_ELEVATION_M, date(2026, 9, 2), "doc2",
                            None, "src", 3, 0),
        )
        with project_tmp() as tmp, _with_tables(tmp / "p.gpkg") as db:
            with db.transaction() as conn:
                self.assertEqual(store.write_intentions(conn, written, srs_id=SRS), (1, 2, 3))
            read = store.read_intentions(db.connection)
        self.assertEqual(len(read), 3)
        for got, item in zip(read, written, strict=True):
            with self.subTest(item.name):
                for name in ("uid", "name", "role", "kind", "elevation_m", "stated_on",
                             "document_input", "decision_uid", "source_input", "source_fid"):
                    self.assertEqual(getattr(got, name), getattr(item, name), name)
                _same_geometry(self, got.parts, item.parts)

    def test_sectors_round_trip_with_fingerprint(self) -> None:
        """RF-012-07, D-26: los sectores (uno con un hueco, otro de dos polígonos) vuelven con
        su código, nombre y anillos bit a bit; su huella guardada es ``sector_sha256``, que no
        depende del CRS; un código repetido lo rechaza la tabla."""
        outer, hole = _polygon_parts()[0]
        written = (
            model.Sector("s" * 32, "norte", "Sector norte", (outer, hole)),
            model.Sector("t" * 32, "sur", "Sector sur",
                         (_ring(200, 0, 220, 20), _ring(300, 0, 320, 20))),
        )
        with project_tmp() as tmp, _with_tables(tmp / "p.gpkg") as db:
            with db.transaction() as conn:
                store.write_sectors(conn, written, srs_id=SRS)
            read = store.read_sectors(db.connection)
            stored = [row[0] for row in db.connection.execute(
                "SELECT geom_sha256 FROM core_sector ORDER BY fid")]
            with self.assertRaises(sqlite3.IntegrityError), db.transaction() as conn:
                store.write_sectors(conn, (model.Sector("u" * 32, "norte", "Otro",
                                                        (outer,)),), srs_id=SRS)
        self.assertEqual(stored, [store.sector_sha256(item) for item in written])
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{64}", sha) for sha in stored))
        self.assertNotEqual(stored[0], stored[1])
        for got, item in zip(read, written, strict=True):
            self.assertEqual((got.uid, got.code, got.name), (item.uid, item.code, item.name))
            _same_geometry(self, (got.rings,), (item.rings,))

    def test_searches_and_hits_are_appended(self) -> None:
        """RF-012-09: cerrar una búsqueda añade su fila y la de cada entidad hallada
        (convertida, con su restricción; o descartada), con sus atributos en JSON canónico y su
        motivo; las de otra búsqueda se añaden sin tocar las primeras."""
        record = model.SearchRecord("r" * 32, "o" * 32, "norte", "f" * 64, 25.0, "Ana",
                                    "2026-10-28T10:00:00.000Z")
        hits = (
            model.SearchHit(record.uid, "gis_fea_infra_12345678", 3, 6.0,
                            {"tipo": "torre", "kV": 132, "altura": 31.5}, "converted",
                            "Torre de alta tensión", "torre_132_kv"),
            model.SearchHit(record.uid, "gis_fea_infra_12345678", 9, 24.5, {"tipo": "poste"},
                            "discarded", "Poste retirado en 2025", None),
        )
        later = model.SearchRecord("q" * 32, "p" * 32, "", "e" * 64, 30.0, "Luis",
                                   "2026-10-29T08:00:00.000Z")
        with project_tmp() as tmp, _with_tables(tmp / "p.gpkg") as db:
            with db.transaction() as conn:
                store.append_search(conn, record, hits)
            with db.transaction() as conn:
                store.append_search(conn, later, ())
            conn = db.connection
            self.assertEqual(store.read_searches(conn), (record, later))
            self.assertEqual(store.read_hits(conn), hits)
            self.assertEqual(store.read_hits(conn, record.uid), hits)
            self.assertEqual(store.read_hits(conn, later.uid), ())
            text = conn.execute("SELECT attributes FROM core_untouchable_hit "
                                "ORDER BY fid").fetchone()[0]
        self.assertEqual(text, '{"altura":31.5,"kV":132,"tipo":"torre"}')
        self.assertEqual(json.loads(text), dict(hits[0].attributes))


if __name__ == "__main__":
    unittest.main()
