# SPDX-License-Identifier: GPL-3.0-or-later
"""Seguimiento de las tablas de los datos del proyecto (spec 008, T10; RF-008-21; ADR-0025
§6; plan 008 §5.2.1 y §5.4.2).

``core.datasets.tracking`` pone en cada tabla de un dato seguido tres disparadores ``AFTER
INSERT/UPDATE/DELETE`` (``gbtc_<tabla>_ins``, ``_upd`` y ``_del``) que escriben en
``gpkg_contents.last_change`` la hora de la escritura con el formato del estándar
(``AAAA-MM-DDTHH:MM:SS.mmmZ``). Están en SQL estándar, sin ``gb_writer()``, para que actúen
también cuando escribe QGIS o cualquier otro programa. ``table_states`` da de una vez, de
cada tabla, ese ``last_change``, la huella del SQL con el que está creada y los disparadores
de Geoblender que tiene: así la comprobación (T30) ve una escritura, un cambio de
estructura (que no dispara nada), un disparador quitado o la tabla rehecha como hace GDAL
(que los pierde), y ``ensure_triggers`` los vuelve a poner.
"""

from __future__ import annotations

import datetime as dt
import re
import sqlite3
import unittest

from tests.support import dataset_tables as tables
from tests.support.package import import_geoblender

tracking = import_geoblender("core.datasets.tracking")
datasets = import_geoblender("core.datasets")
errors = import_geoblender("core.errors")
hashing = import_geoblender("core.hashing")
timeutil = import_geoblender("core.timeutil")

STANDARD_FORMAT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
LAYER = tables.LAYER
SHARED = tables.SHARED
OTHER = tables.OTHER
ODD = tables.ODD
OLD = tables.OLD_CHANGE
q = tables.quote

# Escrituras de una fila o más en la capa: (descripción, SQL).
WRITES: tuple[tuple[str, str], ...] = (
    ("insertar", f"INSERT INTO {LAYER} (geom, codigo, tipo) VALUES (NULL, 'P-09', 'nueva')"),
    ("cambiar", f"UPDATE {LAYER} SET tipo = 'exclusion' WHERE codigo = 'P-01'"),
    ("borrar", f"DELETE FROM {LAYER} WHERE codigo = 'P-02'"),
    ("borrar todo", f"DELETE FROM {LAYER}"),
    (
        "insertar sustituyendo",
        f"INSERT OR REPLACE INTO {LAYER} (fid, geom, codigo, tipo) VALUES (1, NULL, 'P-01', 'x')",
    ),
)


def _sql(conn: sqlite3.Connection, name: str) -> str | None:
    row = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (name,)).fetchone()
    return None if row is None else row[0]


def _schema_sha(conn: sqlite3.Connection, table: str) -> str:
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()[0]
    return hashing.sha256_bytes(sql.encode("utf-8"))


def _names(table: str) -> tuple[str, str, str]:
    return (f"gbtc_{table}_ins", f"gbtc_{table}_upd", f"gbtc_{table}_del")


class TrackTableTest(tables.DatasetTablesCase):
    """Los disparadores de ``last_change`` (RF-008-21; ADR-0025 §6)."""

    def _track(self, *names: str) -> None:
        with self.db.transaction() as conn:
            for name in names:
                self.assertTrue(tracking.track_table(conn, name))

    def assertFreshChange(self, value: object, before: dt.datetime, label: str) -> None:
        """``value`` es un ``last_change`` del estándar, con milisegundos, puesto ahora."""
        after = dt.datetime.now(dt.UTC)
        self.assertIsInstance(value, str, label)
        self.assertNotEqual(value, OLD, label)
        self.assertRegex(value, STANDARD_FORMAT, label)
        moment = timeutil.parse_utc(value)
        slack = dt.timedelta(seconds=1)
        self.assertLessEqual(before - slack, moment, label)
        self.assertLessEqual(moment, after + slack, label)

    def test_writes_from_geoblender_change_last_change(self) -> None:
        """Insertar, cambiar, borrar, borrar todo e insertar con ``REPLACE`` desde la
        conexión de Geoblender ponen la hora en ``last_change``, con el formato del estándar
        y milisegundos; no la cambian ni una sentencia que no toca filas, ni una que falla,
        ni una transacción deshecha, y no tocan otras tablas (RF-008-21; ADR-0025 §6)."""
        self._track(LAYER)
        for label, sql in WRITES:
            with self.subTest(label):
                tables.set_last_change(self.conn, LAYER)
                before = dt.datetime.now(dt.UTC)
                with self.db.transaction() as conn:
                    conn.execute(sql)
                self.assertFreshChange(tables.last_change(self.conn, LAYER), before, label)
                self.assertEqual(tables.last_change(self.conn, OTHER), OLD)
        tables.set_last_change(self.conn, LAYER)
        with self.db.transaction() as conn:
            conn.execute(f"UPDATE {LAYER} SET tipo = 'x' WHERE codigo = 'no existe'")
            conn.execute(f"DELETE FROM {LAYER} WHERE fid < 0")
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db.transaction() as conn:
                conn.execute(f"INSERT INTO {LAYER} (fid, codigo) VALUES (NULL, 'P-10')")
                conn.execute(f"INSERT INTO {SHARED} (input_uid) VALUES (NULL)")
        self.assertEqual(tables.last_change(self.conn, LAYER), OLD)
        self.assertEqual(tables.last_change(self.conn, SHARED), OLD)

    def test_writes_from_a_foreign_connection_change_last_change(self) -> None:
        """Desde una conexión sin ``gb_writer()`` (QGIS, GDAL) las mismas escrituras
        también ponen la hora: los disparadores no la necesitan (RF-008-21; ADR-0025
        §6)."""
        self._track(LAYER, SHARED)
        with self.assertRaisesRegex(sqlite3.OperationalError, "no such function"):
            self.qgis.execute("SELECT gb_writer()")
        for label, sql in WRITES:
            with self.subTest(label):
                tables.set_last_change(self.qgis, LAYER)
                before = dt.datetime.now(dt.UTC)
                self.qgis.execute(sql)
                self.assertFreshChange(tables.last_change(self.qgis, LAYER), before, label)
        before = dt.datetime.now(dt.UTC)
        self.qgis.execute("BEGIN")
        self.qgis.execute(f"UPDATE {SHARED} SET nota = 'editada' WHERE fid = 4")
        self.qgis.execute("COMMIT")
        self.assertFreshChange(tables.last_change(self.conn, SHARED), before, "transacción")

    def test_vacuum_does_not_change_it(self) -> None:
        """Un ``VACUUM`` (de Geoblender o de QGIS) no cambia ``last_change`` ni nada de lo
        que da ``table_states`` (RF-008-21)."""
        self._track(LAYER, SHARED)
        with self.db.transaction() as conn:
            conn.execute(f"DELETE FROM {LAYER} WHERE fid = 3")
        states = tracking.table_states(self.conn)
        changed = tables.last_change(self.conn, LAYER)
        self.assertNotEqual(changed, OLD)
        self.conn.execute("VACUUM")
        self.qgis.execute("VACUUM")
        self.assertEqual(tables.last_change(self.conn, LAYER), changed)
        self.assertEqual(tables.last_change(self.conn, SHARED), OLD)
        self.assertEqual(tracking.table_states(self.conn), states)

    def test_triggers_are_standard_sql_and_idempotent(self) -> None:
        """``track_table`` crea ``gbtc_<tabla>_ins``, ``_upd`` y ``_del`` sin
        ``gb_writer()``; volver a llamarla (o ``ensure_triggers``) no cambia nada y da
        falso (ADR-0025 §6)."""
        self._track(LAYER)
        self.assertEqual(tracking.tracking_trigger_names(LAYER), _names(LAYER))
        for name in _names(LAYER):
            sql = _sql(self.conn, name)
            self.assertIsNotNone(sql, name)
            self.assertNotIn("gb_writer", sql)
            self.assertIn("gpkg_contents", sql)
            self.assertIn("strftime('%Y-%m-%dT%H:%M:%fZ', 'now')", sql)
        dump = tables.dump(self.conn)
        with self.db.transaction() as conn:
            self.assertFalse(tracking.track_table(conn, LAYER))
            self.assertEqual(tracking.ensure_triggers(conn, [LAYER]), [])
        self.assertEqual(tables.dump(self.conn), dump)

    def test_odd_table_names(self) -> None:
        """Una tabla con espacios, comillas y mayúsculas, como las que crea una persona en
        QGIS, también se sigue (RF-008-21)."""
        self._track(ODD)
        before = dt.datetime.now(dt.UTC)
        self.qgis.execute(f"INSERT INTO {q(ODD)} (nombre) VALUES ('dos')")
        self.assertFreshChange(tables.last_change(self.conn, ODD), before, ODD)
        state = tracking.table_states(self.conn)[ODD]
        self.assertTrue(state.tracked)
        self.assertEqual(state.triggers, frozenset(_names(ODD)))

    def test_rejects_tables_that_are_not_data_tables(self) -> None:
        """No se sigue una tabla que no existe, una fuera de ``gpkg_contents``, una del
        estándar o una interna de Geoblender, ni con un nombre que no es texto; y
        ``ensure_triggers`` no deja nada a medias (RF-008-21)."""
        dump = tables.dump(self.conn)
        cases = (
            ("no_existe", "core.dataset_table_missing"),
            (tables.UNREGISTERED, "core.dataset_table_unregistered"),
            ("gpkg_contents", "core.dataset_table_reserved"),
            ("gb_project", "core.dataset_table_reserved"),
            ("GB_dataset", "core.dataset_table_reserved"),
        )
        for name, code in cases:
            with self.subTest(name):
                with self.assertRaises(errors.ValidationError) as caught:
                    with self.db.transaction() as conn:
                        tracking.track_table(conn, name)
                self.assertEqual(caught.exception.code, code)
                self.assertIn(name, str(caught.exception))
        with self.assertRaises(errors.ValidationError):
            with self.db.transaction() as conn:
                tracking.ensure_triggers(conn, [LAYER, "no_existe"])
        with self.assertRaises(TypeError):
            tracking.track_table(self.conn, None)
        with self.assertRaises(TypeError):
            tracking.ensure_triggers(self.conn, LAYER)
        self.assertEqual(tables.dump(self.conn), dump)

    def test_package_reexports_the_api(self) -> None:
        """``core.datasets`` reexporta la API del seguimiento (plan 008 §5.3.1)."""
        for name in (
            "track_table",
            "ensure_triggers",
            "table_states",
            "protect_immutable",
            "TableState",
            "tracking_trigger_names",
            "protection_trigger_names",
        ):
            self.assertIs(getattr(datasets, name), getattr(tracking, name), name)


class TableStatesTest(tables.DatasetTablesCase):
    """Lo que ve la comprobación de una tabla: ``last_change``, SQL y disparadores
    (RF-008-21; ADR-0025 §6; plan 008 §5.4.2)."""

    def setUp(self) -> None:
        super().setUp()
        with self.db.transaction() as conn:
            tracking.ensure_triggers(conn, [LAYER, SHARED])

    def test_states_of_every_data_table(self) -> None:
        """Una entrada por tabla de ``gpkg_contents`` (y ninguna de las internas ni de las
        que no están registradas), con su ``last_change``, la huella de su SQL y los
        disparadores de Geoblender que tiene; con ``tables``, solo esas (RF-008-21)."""
        states = tracking.table_states(self.conn)
        self.assertEqual(set(states), set(tables.REGISTERED))
        for name in tables.REGISTERED:
            with self.subTest(name):
                state = states[name]
                self.assertIsInstance(state, tracking.TableState)
                self.assertEqual(state.table, name)
                self.assertTrue(state.exists)
                self.assertTrue(state.registered)
                self.assertEqual(state.last_change, OLD)
                self.assertEqual(state.schema_sha256, _schema_sha(self.conn, name))
        for name in (LAYER, SHARED):
            self.assertEqual(states[name].triggers, frozenset(_names(name)))
            self.assertTrue(states[name].tracked)
            self.assertEqual(states[name].missing_tracking, ())
        self.assertEqual(states[OTHER].triggers, frozenset())
        self.assertFalse(states[OTHER].tracked)
        self.assertEqual(states[OTHER].missing_tracking, _names(OTHER))
        only = tracking.table_states(self.conn, [SHARED, "no_existe"])
        self.assertEqual(set(only), {SHARED, "no_existe"})
        self.assertEqual(only[SHARED], states[SHARED])
        absent = only["no_existe"]
        self.assertEqual(
            (absent.exists, absent.registered, absent.last_change, absent.schema_sha256),
            (False, False, None, None),
        )

    def test_dropped_trigger_shows_up_and_is_restored(self) -> None:
        """Un disparador quitado (desde QGIS) aparece en ``table_states``; una escritura
        que ya no lo dispara no cambia ``last_change``, y ``ensure_triggers`` lo vuelve a
        poner, solo en esa tabla (RF-008-21; ADR-0025 §6)."""
        self.qgis.execute(f"DROP TRIGGER gbtc_{LAYER}_upd")
        state = tracking.table_states(self.conn)[LAYER]
        self.assertFalse(state.tracked)
        self.assertEqual(state.missing_tracking, (f"gbtc_{LAYER}_upd",))
        self.qgis.execute(f"UPDATE {LAYER} SET tipo = 'x'")
        self.assertEqual(tables.last_change(self.conn, LAYER), OLD)
        with self.db.transaction() as conn:
            self.assertEqual(tracking.ensure_triggers(conn, [SHARED, LAYER]), [LAYER])
        self.assertTrue(tracking.table_states(self.conn)[LAYER].tracked)
        self.qgis.execute(f"UPDATE {LAYER} SET tipo = 'y'")
        self.assertNotEqual(tables.last_change(self.conn, LAYER), OLD)

    def test_impostor_trigger_is_replaced(self) -> None:
        """Un disparador con el nombre de los del seguimiento pero otro SQL (que ya no pone
        la hora) se sustituye con ``ensure_triggers`` (RF-008-21; ADR-0025 §6)."""
        name = f"gbtc_{LAYER}_upd"
        self.qgis.execute(f"DROP TRIGGER {name}")
        self.qgis.execute(f"CREATE TRIGGER {name} AFTER UPDATE ON {LAYER} BEGIN SELECT 1; END")
        self.qgis.execute(f"UPDATE {LAYER} SET tipo = 'x'")
        self.assertEqual(tables.last_change(self.conn, LAYER), OLD)
        with self.db.transaction() as conn:
            self.assertEqual(tracking.ensure_triggers(conn, [LAYER, SHARED]), [LAYER])
        self.assertIn("gpkg_contents", _sql(self.conn, name))
        self.qgis.execute(f"UPDATE {LAYER} SET tipo = 'y'")
        self.assertNotEqual(tables.last_change(self.conn, LAYER), OLD)

    def test_table_rebuilt_like_gdal_shows_up(self) -> None:
        """La tabla rehecha como GDAL (temporal, copia, borrar, renombrar) pierde sus
        disparadores sin cambiar ``last_change`` ni su SQL: solo lo dice la falta de
        disparadores en ``table_states``; ``ensure_triggers`` los repone y las escrituras
        vuelven a contar (RF-008-21; ADR-0025 §6)."""
        before = tracking.table_states(self.conn)[LAYER]
        tables.rebuild_like_gdal(self.qgis, LAYER)
        after = tracking.table_states(self.conn)[LAYER]
        self.assertEqual(after.triggers, frozenset())
        self.assertFalse(after.tracked)
        self.assertEqual(after.last_change, OLD)
        self.assertEqual(after.schema_sha256, before.schema_sha256)
        self.assertEqual(tables.rows(self.conn, LAYER), tables.rows(self.qgis, LAYER))
        with self.db.transaction() as conn:
            self.assertEqual(tracking.ensure_triggers(conn, [LAYER]), [LAYER])
        self.assertEqual(tracking.table_states(self.conn)[LAYER].triggers, before.triggers)
        self.qgis.execute(f"DELETE FROM {LAYER} WHERE fid = 1")
        self.assertNotEqual(tables.last_change(self.conn, LAYER), OLD)

    def test_structure_changes_show_up(self) -> None:
        """Añadir o renombrar una columna (que no dispara nada) cambia la huella del SQL y
        no ``last_change``; los disparadores siguen (RF-008-21; ADR-0025 §6)."""
        seen = {tracking.table_states(self.conn)[SHARED].schema_sha256}
        for sql in (
            f"ALTER TABLE {SHARED} ADD COLUMN muestra TEXT",
            f"ALTER TABLE {SHARED} RENAME COLUMN nota TO observaciones",
        ):
            with self.subTest(sql):
                self.qgis.execute(sql)
                state = tracking.table_states(self.conn)[SHARED]
                self.assertNotIn(state.schema_sha256, seen)
                seen.add(state.schema_sha256)
                self.assertEqual(state.last_change, OLD)
                self.assertTrue(state.tracked)

    def test_dropped_tables(self) -> None:
        """Una tabla borrada con SQL que sigue en ``gpkg_contents`` consta sin SQL; una
        borrada como lo hace QGIS (también su fila de ``gpkg_contents``) ya no está; los
        disparadores de una tabla que no se registró sí constan (RF-008-21, RF-008-57)."""
        self.qgis.execute(f"DROP TABLE {SHARED}")
        self.qgis.execute(f"DROP TABLE {OTHER}")
        self.qgis.execute("DELETE FROM gpkg_contents WHERE table_name = ?", (OTHER,))
        self.qgis.execute("DELETE FROM gpkg_contents WHERE table_name = ?", (LAYER,))
        states = tracking.table_states(self.conn)
        self.assertNotIn(OTHER, states)
        gone = states[SHARED]
        self.assertEqual((gone.exists, gone.registered), (False, True))
        self.assertIsNone(gone.schema_sha256)
        self.assertEqual(gone.triggers, frozenset())
        unregistered = states[LAYER]
        self.assertEqual((unregistered.exists, unregistered.registered), (True, False))
        self.assertIsNone(unregistered.last_change)
        self.assertEqual(unregistered.triggers, frozenset(_names(LAYER)))


if __name__ == "__main__":
    unittest.main()
