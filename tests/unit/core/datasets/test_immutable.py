# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo importado de una entrada no se modifica (spec 008, T10; RF-008-52, RF-008-21;
ADR-0025 §4; plan 008 §5.2.1).

``core.datasets.tracking.protect_immutable`` pone en la tabla de lo importado disparadores
``BEFORE INSERT/UPDATE/DELETE`` que abortan para cualquier conexión (Geoblender, QGIS,
GDAL) con «<tabla>: es lo importado de la entrada «<nombre>»: no se modifica»; con un
selector (``{"column": "input_uid", "equals": <uid>}``), solo en las filas de esa entrada,
para que varias entradas importen a una tabla común (plan 008 §5.4.8, acumular). En SQLite
``INSERT OR REPLACE`` y ``UPDATE OR REPLACE`` borran la fila con la que chocan sin disparar
los ``BEFORE DELETE``: los disparadores con selector rechazan también la fila que chocaría
con una protegida por su ``fid`` o por un índice único. Un ``ALTER TABLE … DROP COLUMN``
no dispara nada: lo ve ``table_states`` porque cambia el SQL de la tabla (el dato quedará
«dañado», T30).
"""

from __future__ import annotations

import sqlite3
import unittest
from collections.abc import Sequence
from typing import Any

from tests.support import dataset_tables as tables
from tests.support.package import import_geoblender

tracking = import_geoblender("core.datasets.tracking")
errors = import_geoblender("core.errors")
hashing = import_geoblender("core.hashing")

LAYER = tables.LAYER
SHARED = tables.SHARED
OTHER = tables.OTHER
ODD = tables.ODD
OLD = tables.OLD_CHANGE
A = tables.INPUT_A
B = tables.INPUT_B
C = tables.INPUT_C
NAME_A = "Ensayos del cliente (entrega 1)"
NAME_B = "Ensayos d'IMGA «revisados»"
NAME_LAYER = "Límites de la concesión"
q = tables.quote


def _message(table: str, name: str) -> str:
    return f"{table}: es lo importado de la entrada «{name}»: no se modifica"


def _selector(uid: str) -> dict[str, str]:
    return {"column": "input_uid", "equals": uid}


class ImmutableCase(tables.DatasetTablesCase):
    """Comprobaciones comunes: una sentencia aborta con el mensaje y no cambia nada."""

    def connections(self) -> tuple[tuple[str, sqlite3.Connection], ...]:
        return (("proyecto", self.conn), ("QGIS", self.qgis))

    def snapshot(self) -> list[list[tuple[Any, ...]]]:
        """Las filas de las tablas de datos y de ``gpkg_contents``."""
        found = [tables.rows(self.conn, table) for table in tables.REGISTERED]
        found.append(self.conn.execute("SELECT * FROM gpkg_contents ORDER BY 1").fetchall())
        return found

    def assertAborts(
        self, conn: sqlite3.Connection, sql: str, args: Sequence[Any], message: str
    ) -> None:
        before = self.snapshot()
        with self.assertRaises(sqlite3.IntegrityError) as caught:
            if conn is self.conn:
                with self.db.transaction() as writer:
                    writer.execute(sql, args)
            else:
                conn.execute(sql, args)
        self.assertEqual(str(caught.exception), message)
        self.assertEqual(self.snapshot(), before)

    def assertPasses(self, conn: sqlite3.Connection, sql: str, args: Sequence[Any]) -> None:
        if conn is self.conn:
            with self.db.transaction() as writer:
                writer.execute(sql, args)
        else:
            conn.execute(sql, args)


class WholeTableTest(ImmutableCase):
    """Una tabla que es entera lo importado de una entrada (RF-008-52; ADR-0025 §4)."""

    def setUp(self) -> None:
        super().setUp()
        with self.db.transaction() as conn:
            tracking.track_table(conn, LAYER)
            self.assertTrue(tracking.protect_immutable(conn, LAYER, input_name=NAME_LAYER))

    def test_every_write_aborts_from_any_connection(self) -> None:
        """Insertar, cambiar, borrar (también todo) y sustituir abortan desde Geoblender y
        desde QGIS con el mensaje que nombra la entrada, sin cambiar ninguna fila ni
        ``last_change`` (RF-008-52)."""
        message = _message(LAYER, NAME_LAYER)
        statements = (
            (f"INSERT INTO {LAYER} (geom, codigo) VALUES (NULL, 'P-09')", ()),
            (f"UPDATE {LAYER} SET tipo = ? WHERE fid = 1", ("exclusion",)),
            (f"UPDATE {LAYER} SET tipo = tipo", ()),
            (f"DELETE FROM {LAYER} WHERE fid = 2", ()),
            (f"DELETE FROM {LAYER}", ()),
            (f"INSERT OR REPLACE INTO {LAYER} (fid, codigo) VALUES (1, 'P-01')", ()),
            (f"UPDATE OR REPLACE {LAYER} SET fid = 1 WHERE fid = 2", ()),
        )
        for who, conn in self.connections():
            for sql, args in statements:
                with self.subTest(who=who, sql=sql):
                    self.assertAborts(conn, sql, args, message)
                    self.assertEqual(tables.last_change(self.conn, LAYER), OLD)
        self.assertPasses(self.qgis, f"INSERT INTO {OTHER} (valor) VALUES (2.5)", ())

    def test_triggers_and_idempotence(self) -> None:
        """Los disparadores ``gbim_<tabla>_ins``, ``_upd`` y ``_del`` constan en
        ``table_states`` junto a los del seguimiento; volver a proteger igual no cambia
        nada y da falso, y protegerla para otra entrada se rechaza (RF-008-52)."""
        names = tracking.protection_trigger_names(LAYER)
        self.assertEqual(names, (f"gbim_{LAYER}_ins", f"gbim_{LAYER}_upd", f"gbim_{LAYER}_del"))
        state = tracking.table_states(self.conn)[LAYER]
        self.assertTrue(state.tracked)
        self.assertEqual(
            state.triggers, frozenset(names) | frozenset(tracking.tracking_trigger_names(LAYER))
        )
        dump = tables.dump(self.conn)
        with self.db.transaction() as conn:
            self.assertFalse(tracking.protect_immutable(conn, LAYER, input_name=NAME_LAYER))
        with self.assertRaises(errors.ValidationError) as caught:
            with self.db.transaction() as conn:
                tracking.protect_immutable(conn, LAYER, input_name="Otra entrega")
        self.assertEqual(caught.exception.code, "core.dataset_protection_conflict")
        self.assertEqual(tables.dump(self.conn), dump)

    def test_drop_column_shows_up_in_table_states(self) -> None:
        """Un ``ALTER TABLE … DROP COLUMN`` no dispara nada y pasa, pero cambia la huella
        del SQL en ``table_states`` (los disparadores siguen y ``last_change`` no cambia):
        así se ve que lo importado cambió (RF-008-52, RF-008-21; ADR-0025 §4)."""
        before = tracking.table_states(self.conn)[LAYER]
        self.qgis.execute(f"ALTER TABLE {LAYER} DROP COLUMN tipo")
        after = tracking.table_states(self.conn)[LAYER]
        self.assertNotEqual(after.schema_sha256, before.schema_sha256)
        self.assertEqual(after.triggers, before.triggers)
        self.assertEqual(after.last_change, OLD)


class SelectorTest(ImmutableCase):
    """Una tabla común de varias entradas: cada una protege sus filas (RF-008-52; plan 008
    §5.4.8)."""

    def setUp(self) -> None:
        super().setUp()
        with self.db.transaction() as conn:
            tracking.track_table(conn, SHARED)
            tracking.protect_immutable(conn, SHARED, _selector(A), input_name=NAME_A)
            tracking.protect_immutable(conn, SHARED, _selector(B), input_name=NAME_B)

    def test_rows_of_each_input_are_protected(self) -> None:
        """Las filas de A y de B no se insertan, cambian, borran ni sustituyen desde ninguna
        conexión, con el nombre de su entrada; tampoco se mueve una fila libre a una
        entrada protegida ni se le quita a una (RF-008-52)."""
        cases = (
            (f"INSERT INTO {SHARED} (input_uid, codigo) VALUES (?, 'S-09')", (A,), NAME_A),
            (f"INSERT INTO {SHARED} (input_uid, codigo) VALUES (?, 'S-09')", (B,), NAME_B),
            (f"UPDATE {SHARED} SET ley = 9.9 WHERE fid = 1", (), NAME_A),
            (f"UPDATE {SHARED} SET ley = ley WHERE fid = 3", (), NAME_B),
            (f"UPDATE {SHARED} SET input_uid = ? WHERE fid = 2", (C,), NAME_A),
            (f"UPDATE {SHARED} SET input_uid = ? WHERE fid = 4", (B,), NAME_B),
            (f"UPDATE {SHARED} SET fid = 99, input_uid = ?, codigo = 'S-99' WHERE fid = 2", (C,),
             NAME_A),
            (f"DELETE FROM {SHARED} WHERE fid = 2", (), NAME_A),
            (f"DELETE FROM {SHARED} WHERE input_uid = ?", (B,), NAME_B),
            (f"DELETE FROM {SHARED}", (), NAME_A),
        )
        for who, conn in self.connections():
            for sql, args, name in cases:
                with self.subTest(who=who, sql=sql, args=args):
                    self.assertAborts(conn, sql, args, _message(SHARED, name))
        self.assertEqual(tables.last_change(self.conn, SHARED), OLD)

    def test_replace_cannot_remove_a_protected_row(self) -> None:
        """``INSERT OR REPLACE`` y ``UPDATE OR REPLACE`` de una fila libre que chocaría por
        ``fid`` o por el índice único con una protegida (y la borraría sin disparar el
        ``BEFORE DELETE``) abortan; si choca con otra libre, pasan (RF-008-52)."""
        cases = (
            (f"INSERT OR REPLACE INTO {SHARED} (fid, input_uid, codigo) VALUES (1, ?, 'S-09')",
             (C,), NAME_A),
            (f"INSERT OR REPLACE INTO {SHARED} (input_uid, codigo) VALUES (?, 'S-03')",
             (C,), NAME_B),
            (f"UPDATE OR REPLACE {SHARED} SET fid = 3 WHERE fid = 4", (), NAME_B),
            (f"UPDATE OR REPLACE {SHARED} SET codigo = 'S-01' WHERE fid = 4", (), NAME_A),
        )
        for who, conn in self.connections():
            for sql, args, name in cases:
                with self.subTest(who=who, sql=sql):
                    self.assertAborts(conn, sql, args, _message(SHARED, name))
        self.assertPasses(
            self.qgis,
            f"INSERT OR REPLACE INTO {SHARED} (input_uid, codigo, nota) VALUES (?, 'S-04', 'n')",
            (C,),
        )
        self.assertEqual(
            self.conn.execute(
                f"SELECT input_uid, codigo, nota FROM {SHARED} WHERE codigo = 'S-04'"
            ).fetchall(),
            [(C, "S-04", "n")],
        )

    def test_other_rows_are_free(self) -> None:
        """Las filas de otra entrada (C) se insertan, cambian y borran desde cualquier
        conexión, y cuentan en ``last_change``; las protegidas siguen intactas
        (RF-008-52, RF-008-21)."""
        protected = [row for row in tables.rows(self.conn, SHARED) if row[1] in (A, B)]
        for who, conn in self.connections():
            with self.subTest(who):
                tables.set_last_change(self.conn, SHARED)
                self.assertPasses(
                    conn, f"INSERT INTO {SHARED} (input_uid, codigo) VALUES (?, ?)", (C, who)
                )
                self.assertPasses(conn, f"UPDATE {SHARED} SET ley = 0.5 WHERE input_uid = ?", (C,))
                self.assertPasses(conn, f"DELETE FROM {SHARED} WHERE codigo = ?", (who,))
                self.assertNotEqual(tables.last_change(self.conn, SHARED), OLD)
        self.assertPasses(self.qgis, f"DELETE FROM {SHARED} WHERE input_uid = ?", (C,))
        self.assertEqual(tables.rows(self.conn, SHARED), protected)

    def test_names_per_selector(self) -> None:
        """Cada selector tiene sus tres disparadores, con nombres distintos y que da
        ``protection_trigger_names``; todos constan en ``table_states`` (RF-008-52)."""
        names_a = tracking.protection_trigger_names(SHARED, _selector(A))
        names_b = tracking.protection_trigger_names(SHARED, _selector(B))
        self.assertEqual(len(set(names_a) | set(names_b)), 6)
        for name in (*names_a, *names_b):
            self.assertTrue(name.startswith(f"gbim_{SHARED}_"), name)
        self.assertNotEqual(names_a, tracking.protection_trigger_names(SHARED))
        state = tracking.table_states(self.conn)[SHARED]
        self.assertLessEqual(set(names_a) | set(names_b), state.triggers)
        self.assertTrue(state.tracked)

    def test_drop_column_shows_up_in_table_states(self) -> None:
        """Quitar una columna que los disparadores no usan pasa y cambia la huella del SQL
        (RF-008-52, RF-008-21)."""
        before = tracking.table_states(self.conn)[SHARED]
        self.qgis.execute(f"ALTER TABLE {SHARED} DROP COLUMN nota")
        after = tracking.table_states(self.conn)[SHARED]
        self.assertNotEqual(after.schema_sha256, before.schema_sha256)
        self.assertEqual(after.triggers, before.triggers)


class ProtectArgumentsTest(ImmutableCase):
    """Lo que ``protect_immutable`` no acepta, sin dejar nada a medias (RF-008-52)."""

    def test_rejects_bad_arguments(self) -> None:
        """Un selector sin la forma ``{"column", "equals"}``, con una columna que la tabla
        no tiene o un valor que no es texto ni entero, una entrada sin nombre y una tabla
        que no es de datos se rechazan sin crear nada (RF-008-52)."""
        dump = tables.dump(self.conn)
        cases = (
            (SHARED, {"column": "input_uid"}, NAME_A, "core.dataset_selector_invalid"),
            (SHARED, {"column": "input_uid", "of": "current_inputs"}, NAME_A,
             "core.dataset_selector_invalid"),
            (SHARED, {"column": "input_uid", "equals": A, "x": 1}, NAME_A,
             "core.dataset_selector_invalid"),
            (SHARED, {"column": "no_hay", "equals": A}, NAME_A, "core.dataset_selector_invalid"),
            (SHARED, {"column": "input_uid", "equals": True}, NAME_A,
             "core.dataset_selector_invalid"),
            (SHARED, {"column": "input_uid", "equals": 1.5}, NAME_A,
             "core.dataset_selector_invalid"),
            (SHARED, {"column": "input_uid", "equals": None}, NAME_A,
             "core.dataset_selector_invalid"),
            (SHARED, None, "  ", "core.dataset_input_name_missing"),
            (tables.UNREGISTERED, None, NAME_A, "core.dataset_table_unregistered"),
            ("gb_input", None, NAME_A, "core.dataset_table_reserved"),
        )
        for table, where, name, code in cases:
            with self.subTest(table=table, where=where, name=name):
                with self.assertRaises(errors.ValidationError) as caught:
                    with self.db.transaction() as conn:
                        tracking.protect_immutable(conn, table, where, input_name=name)
                self.assertEqual(caught.exception.code, code)
        with self.assertRaises(TypeError):
            tracking.protect_immutable(self.conn, SHARED, "input_uid = 'x'", input_name=NAME_A)
        with self.assertRaises(TypeError):
            tracking.protect_immutable(self.conn, SHARED, None, input_name=None)
        self.assertEqual(tables.dump(self.conn), dump)

    def test_integer_selector_and_odd_names(self) -> None:
        """Un selector entero y una tabla con comillas en el nombre también se protegen, con
        el nombre de la entrada intacto en el mensaje (RF-008-52)."""
        with self.db.transaction() as conn:
            tracking.protect_immutable(
                conn, ODD, {"column": "fid", "equals": 1}, input_name=NAME_B
            )
        self.assertAborts(
            self.qgis, f"UPDATE {q(ODD)} SET nombre = 'x' WHERE fid = 1", (), _message(ODD, NAME_B)
        )
        self.assertPasses(self.qgis, f"INSERT INTO {q(ODD)} (nombre) VALUES ('dos')", ())
        self.assertPasses(self.qgis, f"UPDATE {q(ODD)} SET nombre = 'tres' WHERE fid = 2", ())


if __name__ == "__main__":
    unittest.main()
