# SPDX-License-Identifier: GPL-3.0-or-later
"""Almacén del aspecto en el proyecto (spec 019, T03; RF-019-07 a 09; ADR-0033; plan 019 §5.2).

Escribir, leer y restablecer filas de ``gb_appearance``; la fila solo existe si hubo cambio; los
valores se guardan canónicos y se validan por tipo (todo o nada); y un cambio de aspecto no cambia
ninguna otra tabla, ningún estado de seguimiento ni ninguna huella (ADR-0033, punto 5).
"""

from __future__ import annotations

import sqlite3
import unittest

from tests.support.core_fixtures import FakeClock, make_session, make_settings, project_tmp
from tests.support.package import import_geoblender

store = import_geoblender("core.appearance.store")
errors = import_geoblender("core.errors")
create = import_geoblender("core.project.create")
tracking = import_geoblender("core.datasets.tracking")
userdata_mod = import_geoblender("core.userdata")

SESSION = make_session(session_uid="00000000-0000-4000-8000-000000000005", host="PC-PRUEBA-D",
                       user="otra", pid=780, geoblender_version="0.5.0")
WHO = "otra@PC-PRUEBA-D"
NOW = "2026-11-25T10:00:00.000Z"
LATER = "2026-11-25T11:00:00.000Z"


def _others(conn: sqlite3.Connection) -> dict[str, list[tuple]]:
    """Cada fila de cada tabla menos ``gb_appearance``."""
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name != 'gb_appearance' "
        "ORDER BY name")]
    return {n: conn.execute(f'SELECT * FROM "{n}" ORDER BY rowid').fetchall() for n in names}


class StoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = project_tmp("gb-ap-")
        tmp = self._tmp.__enter__()
        self.addCleanup(self._tmp.__exit__, None, None, None)
        created = create.create_project(
            tmp, make_settings(name="Cantera Aspecto"), SESSION,
            userdata_mod.UserData(tmp / "u"), clock=FakeClock(),
        )
        self.project = created.project
        self.addCleanup(self.project.close)

    def test_a_row_exists_only_after_a_change(self) -> None:
        """RF-019-08: sin cambios no hay filas (el predefinido sale del catálogo); leer un nombre
        sin filas no lo devuelve."""
        with self.project.read() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM gb_appearance").fetchone()[0], 0)
            self.assertEqual(store.read(conn, ["DTM-001", "TIN-002"]), {})
            self.assertEqual(store.read(conn, []), {})

    def test_write_read_and_reset(self) -> None:
        """RF-019-07, RF-019-08: escribir guarda valores canónicos con quién y cuándo, leer los
        devuelve por nombre, volver a escribir sustituye (una fila por ``(nombre, propiedad)``) y
        restablecer borra las filas pedidas o todas."""
        with self.project.write_transaction() as conn:
            written = store.write(conn, "DTM-001", "DTM",
                                  {"color": "#56b4e9", "transparency": 30, "visible": True},
                                  WHO, NOW)
            store.write(conn, "POINTS-003", "POINTS", {"point_size": "4,5"}, WHO, NOW)
        self.assertEqual(written, {"color": "#56B4E9", "transparency": "30", "visible": "1"})
        with self.project.read() as conn:
            self.assertEqual(
                store.read(conn, ["DTM-001", "POINTS-003", "otro"]),
                {"DTM-001": {"color": "#56B4E9", "transparency": "30", "visible": "1"},
                 "POINTS-003": {"point_size": "4.5"}},
            )
            self.assertEqual(
                conn.execute("SELECT item_kind, modified_at, modified_by FROM gb_appearance "
                             "WHERE item_name = 'DTM-001' AND prop = 'color'").fetchone(),
                ("DTM", NOW, WHO))
        with self.project.write_transaction() as conn:
            store.write(conn, "DTM-001", "DTM", {"color": "#009E73"}, "yo@otro", LATER)
        with self.project.read() as conn:
            self.assertEqual(store.read(conn, ["DTM-001"])["DTM-001"]["color"], "#009E73")
            self.assertEqual(conn.execute(
                "SELECT modified_at, modified_by FROM gb_appearance "
                "WHERE item_name = 'DTM-001' AND prop = 'color'").fetchone(), (LATER, "yo@otro"))
            self.assertEqual(conn.execute("SELECT count(*) FROM gb_appearance").fetchone()[0], 4)
        with self.project.write_transaction() as conn:
            self.assertEqual(store.reset(conn, "DTM-001", ["color", "nada"]), 1)
            self.assertEqual(store.reset(conn, "DTM-001", []), 0)
        with self.project.read() as conn:
            self.assertEqual(sorted(store.read(conn, ["DTM-001"])["DTM-001"]),
                             ["transparency", "visible"])
        with self.project.write_transaction() as conn:
            self.assertEqual(store.reset(conn, "DTM-001"), 2)
            self.assertEqual(store.reset(conn, "DTM-001"), 0)
        with self.project.read() as conn:
            self.assertEqual(sorted(store.read(conn, ["DTM-001", "POINTS-003"])), ["POINTS-003"])

    def test_invalid_values_write_nothing(self) -> None:
        """RF-019-08: un valor fuera de rango o una propiedad que el tipo no tiene se rechazan con
        objeto, campo y valor, y no se escribe nada (ni los valores buenos del mismo gesto)."""
        with self.project.write_transaction() as conn:
            for kind, values in (("DTM", {"color": "#56B4E9", "transparency": 101}),
                                 ("DTM", {"color": "azul"}),
                                 ("DTM", {"line_width": 2}),
                                 ("NOPE", {"color": "#56B4E9"})):
                with self.subTest(values=values):
                    with self.assertRaises(errors.GeoblenderError):
                        store.write(conn, "DTM-001", kind, values, WHO, NOW)
            self.assertEqual(conn.execute("SELECT count(*) FROM gb_appearance").fetchone()[0], 0)

    def test_changing_the_appearance_changes_nothing_else(self) -> None:
        """RF-019-08, ADR-0033 (punto 5): escribir, cambiar y restablecer el aspecto no cambia
        ninguna fila de ninguna otra tabla (datos, operaciones, versiones, eventos), ni el
        seguimiento de las tablas de datos (``last_change`` y huella), ni el título y la
        fecha de ``gb_project``: ni un hash, un estado o un obsoleto se mueve."""
        with self.project.read() as conn:
            before_rows = _others(conn)
            before_states = tracking.table_states(conn)
        with self.project.write_transaction() as conn:
            store.write(conn, "DTM-001", "DTM", {"color": "#D55E00", "visible": "0"}, WHO, NOW)
        with self.project.write_transaction() as conn:
            store.write(conn, "DTM-001", "DTM", {"transparency": "50"}, WHO, LATER)
            store.reset(conn, "DTM-001", ["visible"])
        with self.project.read() as conn:
            self.assertEqual(_others(conn), before_rows)
            self.assertEqual(tracking.table_states(conn), before_states)
            self.assertNotIn("gb_appearance", tracking.table_states(conn))
        with self.project.write_transaction() as conn:
            store.reset(conn, "DTM-001")
        with self.project.read() as conn:
            self.assertEqual(_others(conn), before_rows)
            self.assertEqual(conn.execute("SELECT count(*) FROM gb_appearance").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
