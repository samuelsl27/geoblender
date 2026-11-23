# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que el dominio lee del proyecto para la barra N de una corta, sin Blender (spec 018, T34; HU-018-1, HU-018-4; RF-018-26, RF-018-29, RF-018-31, RF-015-25; plan 018 §5.5).

La barra N (``bl.ui.pit_panels``) solo escribe los textos traducidos; **todo lo que enseña se lee de lo guardado** de la operación vigente, con ``design.pit_card``
(``tests/blender/test_pit_entity_panel.py`` prueba los textos y ``tests/blender/milestone_pit_entity_panel.py``, con proyecto, cada estado). Aquí, con una base en memoria:

- (a) ``read_pit_facts`` da las cifras del informe (``des_prp_``), el criterio que paró la corta, las cifras de cada banco (``des_pbk_``), los hallazgos con su lugar (``des_pfn_``) y los avisos
  guardados; ``None`` sin informe (no inventa cifras).
- (b) la longitud y las pendientes de cada rampa salen de sus estaciones (``des_prl_``), contadas a mano, una por (definición, banco).
- (c) un hallazgo de un tipo que ya no es del dominio no sale; una corta sin tablas de bancos, hallazgos o rampas da listas vacías.
"""

from __future__ import annotations

import json
import sqlite3
import unittest

from tests.support.package import import_geoblender

pit_card = import_geoblender("design.pit_card")
provenance = import_geoblender("design.provenance")

OPERATION = "op1"


def _project() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE gb_dataset (uid TEXT, name TEXT, locator TEXT, status TEXT)")
    conn.execute("CREATE TABLE gb_operation_io (fid INTEGER PRIMARY KEY, operation_uid TEXT, direction TEXT, item_kind TEXT, item_uid TEXT, role TEXT)")
    return conn


def _table(conn: sqlite3.Connection, name: str, role: str, columns: str, rows: list[tuple[object, ...]]) -> None:
    conn.execute(f'CREATE TABLE "{name}" (fid INTEGER PRIMARY KEY, {columns})')
    marks = ", ".join("?" for _ in rows[0]) if rows else "?"
    names = ", ".join(part.split()[0] for part in columns.split(","))
    conn.executemany(f'INSERT INTO "{name}" ({names}) VALUES ({marks})', rows)
    conn.execute("INSERT INTO gb_dataset VALUES (?, ?, ?, 'current')", (name, name, name))
    conn.execute("INSERT INTO gb_operation_io (operation_uid, direction, item_kind, item_uid, role) VALUES (?, 'out', 'dataset', ?, ?)", (OPERATION, name, role))


def _report(conn: sqlite3.Connection) -> None:
    _table(conn, "des_prp_corta", provenance.ENTITY_REPORT_ROLE, "quantity TEXT, value REAL, unit_code TEXT, note TEXT", [
        ("benches", 3.0, "-", None), ("z_bottom_m", 100.0, "m", None), ("z_top_m", 130.0, "m", None), ("len_foot_m", 820.5, "m", None), ("len_crest_m", 900.25, "m", None),
        ("area_berm_m2", 4200.0, "m2", None), ("area_floor_m2", 1500.0, "m2", None), ("cut_m3", 125000.0, "m3", None), ("area_m2", 9800.0, "m2", None),
        ("sky_parts", 1.0, "-", None), ("sky_len_m", 410.0, "m", None), ("findings", 2.0, "-", None), ("unknown_figure", 7.0, "-", None),
        ("stop", None, None, "surface"),
        ("warning", None, None, json.dumps({"code": "des.pit_ramp_mean_gradient", "values": {"mean": 9.5, "limit": 8.0}}, sort_keys=True)),
        ("note", None, None, json.dumps({"code": "no_such_code_of_the_catalogue", "values": {}}))])


class PitFactsTest(unittest.TestCase):
    def test_a_the_facts_are_read_from_what_the_operation_stored(self) -> None:
        """RF-018-31, RF-018-26, RF-015-25 (a): las cifras del informe (solo las del catálogo de cifras), el criterio de parada, los bancos con su corte, los hallazgos con su lugar y los avisos
        guardados; el aviso de un código que ya no es del catálogo no sale."""
        conn = _project()
        _report(conn)
        _table(conn, "des_pbk_corta", provenance.PIT_BENCHES_ROLE, "bench INTEGER, z_foot_m REAL, z_crest_m REAL, len_foot_m REAL, len_crest_m REAL, area_berm_m2 REAL, area_floor_m2 REAL, cut_m3 REAL",
               [(2, 110.0, 120.0, 300.0, 330.0, 2000.0, None, 50000.0), (1, 100.0, 110.0, 200.0, 240.0, 1500.0, 1500.0, 40000.0)])
        _table(conn, "des_pfn_corta", provenance.PIT_FINDINGS_ROLE, "kind TEXT, bench INTEGER, value REAL, limit_value REAL, unit TEXT, x REAL, y REAL, detail TEXT",
               [("face_slope", 2, 74.5, 72.0, "°", 700010.25, 4400020.5, ""), ("unexcavated", None, 350.0, 0.0, "m²", 700030.0, 4400040.0, "")])
        found = pit_card.read_pit_facts(conn, OPERATION)
        self.assertIsNotNone(found)
        self.assertEqual(found.figures["benches"], 3.0)
        self.assertEqual(found.figures["cut_m3"], 125000.0)
        self.assertEqual(found.figures["sky_len_m"], 410.0)
        self.assertNotIn("unknown_figure", found.figures)
        self.assertEqual(found.stop, "surface")
        self.assertEqual([row.bench for row in found.benches], [1, 2], "por orden de banco")
        self.assertEqual((found.benches[1].area_floor_m2, found.benches[0].area_floor_m2, found.benches[0].cut_m3), (None, 1500.0, 40000.0))
        self.assertEqual([(str(item.kind), item.bench, item.value, item.limit, item.unit, item.place) for item in found.findings],
                         [("face_slope", 2, 74.5, 72.0, "°", (700010.25, 4400020.5)), ("unexcavated", None, 350.0, 0.0, "m²", (700030.0, 4400040.0))])
        self.assertEqual([notice.code for notice in found.notices], ["des.pit_ramp_mean_gradient"])

    def test_b_a_ramp_is_measured_on_its_stored_stations(self) -> None:
        """RF-018-31 (b): la longitud, la pendiente media y la máxima de cada rampa salen de sus estaciones: una por (definición, banco); 40 m de eje que bajan 2 m en un tramo de 10 m (20 %) y 1 m en
        otro de 30 m dan una longitud de 40 m, una media del 7,5 % y una máxima del 20 %; una con una sola estación no sale."""
        conn = _project()
        _report(conn)
        _table(conn, "des_prl_corta", provenance.PIT_RAMPS_ROLE, "ramp TEXT, bench INTEGER, station INTEGER, x REAL, y REAL, level_m REAL, half_width_m REAL", [
            ("R1", 1, 1, 700000.0, 4400000.0, 110.0, 5.0), ("R1", 1, 2, 700010.0, 4400000.0, 108.0, 5.0), ("R1", 1, 3, 700010.0, 4400030.0, 107.0, 5.0),
            ("R1", 2, 1, 700100.0, 4400000.0, 120.0, 5.0), ("R1", 2, 2, 700100.0, 4400020.0, 118.0, 5.0), ("R2", 3, 1, 700200.0, 4400000.0, 130.0, 5.0)])
        ramps = pit_card.read_pit_facts(conn, OPERATION).ramps
        self.assertEqual([(item.code, item.bench) for item in ramps], [("R1", 1), ("R1", 2)])
        first = ramps[0]
        self.assertAlmostEqual(first.length_m, 40.0, places=9)
        self.assertAlmostEqual(first.gradient_mean_pct, 7.5, places=9)
        self.assertAlmostEqual(first.gradient_max_pct, 20.0, places=9)
        self.assertEqual((first.x, first.y), (700000.0, 4400000.0), "el inicio, absoluto y en float64")
        self.assertAlmostEqual(ramps[1].gradient_mean_pct, 10.0, places=9)

    def test_c_without_report_or_tables_it_does_not_invent(self) -> None:
        """RF-015-25 (c): sin informe, ``None``; con informe y sin las tablas de bancos, hallazgos y rampas, listas vacías; un hallazgo de un tipo desconocido no sale."""
        conn = _project()
        self.assertIsNone(pit_card.read_pit_facts(conn, OPERATION))
        _report(conn)
        bare = pit_card.read_pit_facts(conn, OPERATION)
        self.assertEqual((bare.benches, bare.findings, bare.ramps), ((), (), ()))
        _table(conn, "des_pfn_corta", provenance.PIT_FINDINGS_ROLE, "kind TEXT, bench INTEGER, value REAL, limit_value REAL, unit TEXT, x REAL, y REAL, detail TEXT",
               [("from_the_future", 1, 1.0, 2.0, "m", 0.0, 0.0, ""), ("no_profile", 4, None, None, "", 700001.0, 4400001.0, "perímetro")])
        found = pit_card.read_pit_facts(conn, OPERATION).findings
        self.assertEqual([(str(item.kind), item.bench, item.value, item.detail) for item in found], [("no_profile", 4, None, "perímetro")])


if __name__ == "__main__":
    unittest.main()
