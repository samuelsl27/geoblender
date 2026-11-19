# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que el dominio da a la vista y a la barra N de los acopios y de los tipos nuevos (spec 016, T33; HU-016-1 a HU-016-4; RF-015-25,
RF-016-14; plan 016 §5.5), sin Blender: la lectura de las tablas guardadas por su localizador y los textos de cada fila.

El objeto de la vista y la barra N (``bl.scene.entity_views``, ``bl.ui.des_panels``) se prueban en
``tests/blender/test_stockpile_views.py``; aquí, lo que no necesita Blender:

- **Leer una tabla guardada** (:class:`ReadStoredRowsTest`): ``stockpile_store.read_stored_rows`` da las filas de una tabla de la
  detección (``des_stk_``, ``des_stc_`` o ``des_prp_``) por el nombre de sus columnas y en su orden, con el localizador del dato (el
  cargador de la vista conoce el dato, no el nombre de la detección).
- **Lo que dice cada fila** (:class:`RowNoticesTest`): la nota de un acopio guardado, la de un candidato y los avisos de su fila
  (``notes``) son los mensajes del resumen de «Calcular» con lo guardado, en los dos idiomas.
- **El informe de una entidad** (:class:`EntityReportTest`): ``entity_store.read_entity_report`` lee el ``des_prp_`` que escribió una
  operación, en su orden y con sus cantidades repetidas, y ``()`` si no escribió ninguno.
"""

from __future__ import annotations

import json
import sqlite3
import unittest

from tests.support.package import import_geoblender

entity_store = import_geoblender("design.entity_store")
provenance = import_geoblender("design.provenance")
store = import_geoblender("design.store")
stockpile_store = import_geoblender("design.stockpile_store")


def _table(name: str, columns: tuple[object, ...], rows: list[tuple[object, ...]]) -> sqlite3.Connection:
    """Una base en memoria con la tabla ``name`` (``fid`` y las columnas de ``columns``) y sus ``rows`` (sin el ``fid``)."""
    conn = sqlite3.connect(":memory:")
    names = ", ".join(f'"{column.name}"' for column in columns)  # type: ignore[attr-defined]
    conn.execute(f'CREATE TABLE "{name}" (fid INTEGER PRIMARY KEY, {names})')
    marks = ", ".join("?" for _ in columns)
    conn.executemany(f'INSERT INTO "{name}" ({names}) VALUES ({marks})', rows)
    return conn


class ReadStoredRowsTest(unittest.TestCase):
    """RF-015-25, RF-016-14 (plan 016 §5.5): las filas de una tabla de la detección leídas por su localizador."""

    def test_the_rows_come_by_column_name_and_in_the_order_of_the_table(self) -> None:
        """Las filas de ``des_stk_`` salen como diccionarios por el nombre de su columna y por orden de ``fid``, no del texto."""
        columns = store.STOCKPILE_COLUMNS
        first = ["STK-001", "m02", "Dos", "mark", "marcas", 2, "mineral", None, 3.0, 4, 16.0, 40.5, 2.5, 10.0, 20.0, 100.0, 1.5,
                 90.0, 0.8, 3, 1, "[[1,2,4]]", "[]"]
        second = ["STK-001", "m01", "Uno", "candidate", None, None, None, None, None, 2, 8.0, 5.0, 1.0, 30.0, 40.0, None, None,
                  None, None, 1, 1, "[[5,6,8]]", "[]"]
        conn = _table("des_stk_acopios", columns, [tuple(first), tuple(second)])
        found = stockpile_store.read_stored_rows(conn, provenance.STOCKPILES_TABLE, "des_stk_acopios")
        self.assertEqual([row["key"] for row in found], ["m02", "m01"], "el orden es el de la tabla, no el de las claves")
        self.assertEqual(found[0]["volume_m3"], 40.5)
        self.assertEqual(found[0]["footprint"], "[[1,2,4]]")
        self.assertIsNone(found[1]["material"])
        self.assertEqual(set(found[0]), {column.name for column in columns})

    def test_the_candidates_and_the_report_have_their_own_columns(self) -> None:
        """``des_stc_`` y ``des_prp_`` se leen con las columnas de su familia; una familia que no es de la detección es un error."""
        conn = _table("des_stc_acopios", store.CANDIDATE_COLUMNS,
                      [("c01", "pending", None, None, None, 9, 36.0, 12.0, 5.0, 6.0, 100.0, 1.0, 0.0, "[[0,0,3]]")])
        (row,) = stockpile_store.read_stored_rows(conn, provenance.STOCKPILE_CANDIDATES_TABLE, "des_stc_acopios")
        self.assertEqual((row["key"], row["state"], row["area_m2"]), ("c01", "pending", 36.0))
        report = _table("des_prp_acopios", store.REPORT_COLUMNS, [("stockpiles", 2.0, "-", None)])
        (line,) = stockpile_store.read_stored_rows(report, provenance.ENTITY_REPORT_TABLE, "des_prp_acopios")
        self.assertEqual((line["quantity"], line["value"]), ("stockpiles", 2.0))
        with self.assertRaises(ValueError):
            stockpile_store.read_stored_rows(conn, provenance.STOCKPILE_BASE_GRID, "des_stc_acopios")


def _stockpile(**changes: object) -> dict[str, object]:
    """Una fila de ``des_stk_`` (por el nombre de sus columnas) con lo de ``changes``."""
    row: dict[str, object] = {
        "code": "STK-001", "key": "m02", "name": "Dos", "origin": "mark", "layer": "marcas", "source_fid": 2, "material": "mineral",
        "base_surface": None, "margin_m": 3.0, "cells": 4, "area_m2": 16.0, "volume_m3": 40.5, "thickness_max_m": 2.5, "x": 10.0,
        "y": 20.0, "plane_level_m": 100.0, "plane_slope_percent": 1.5, "plane_azimuth_deg": 90.0, "plane_tilt_deg": 0.8, "turns": 3,
        "converged": 1, "footprint": "[[1,2,4]]", "notes": "[]"}
    row.update(changes)
    return row


class RowNoticesTest(unittest.TestCase):
    """RF-015-25, RF-016-14 (plan 016 §5.5): lo que dice cada fila guardada de la detección, como el resumen de «Calcular»."""

    def test_a_stored_stockpile_says_its_footprint_volume_thickness_material_and_plane(self) -> None:
        """La nota de un acopio con plano: su marca, su material, huella, volumen y espesor máximo, el nivel, la pendiente y el azimut de su
        plano de base y su lugar, en los dos idiomas (lo guardado tal cual, sin recalcular)."""
        notice = stockpile_store.stockpile_row_notice(_stockpile())
        self.assertEqual(notice.code, "des.stockpile_item")
        es, en = notice.text("es"), notice.text("en")
        for text in ("«Dos»", "mineral", "16", "40,5", "2,5", "100", "1,5", "90", "x = 10"):
            self.assertIn(text, es)
        self.assertTrue(es.startswith("Acopio «Dos» (material mineral): huella de 16 m²"), es)
        self.assertTrue(en.startswith("Stockpile «Dos» (material mineral): footprint 16 m²"), en)
        self.assertIn("40.5", en)

    def test_a_stored_stockpile_with_its_own_base_says_the_surface_and_has_no_plane(self) -> None:
        """Con una base propia (sin plano ajustado) la nota dice la superficie de su base, no un plano; sin material, «—»."""
        notice = stockpile_store.stockpile_row_notice(_stockpile(
            plane_level_m=None, plane_slope_percent=None, plane_azimuth_deg=None, plane_tilt_deg=None, material=None,
            base_surface="Base propia"))
        self.assertEqual(notice.code, "des.stockpile_item_own_base")
        self.assertIn("«Base propia»", notice.text("es"))
        self.assertIn("(material —)", notice.text("es"))

    def test_a_stored_candidate_says_its_key_footprint_volume_and_plane(self) -> None:
        """La nota de un candidato dice su clave (``c03``), su huella, su volumen y su plano en el centro (RF-016-08)."""
        row = {"key": "c03", "state": "pending", "reason": None, "decided_by": None, "decided_on": None, "cells": 9, "area_m2": 36.0,
               "volume_m3": 12.0, "x": 5.0, "y": 6.0, "plane_level_m": 100.0, "plane_slope_percent": 2.0, "plane_azimuth_deg": 45.0,
               "footprint": "[[0,0,3]]"}
        notice = stockpile_store.candidate_row_notice(row)
        self.assertEqual(notice.code, "des.stockpile_candidate_item")
        self.assertTrue(notice.text("es").startswith("Candidato c03: huella de 36 m², volumen de 12,0 m³"), notice.text("es"))
        self.assertTrue(notice.text("en").startswith("Candidate c03: footprint 36 m²"), notice.text("en"))

    def test_the_notes_of_a_stored_stockpile_are_its_warnings_in_order(self) -> None:
        """Los avisos de ``notes`` (JSON: código, gravedad y valores, no el texto) salen como avisos con su texto y su gravedad, en su orden;
        sin ninguno, ``()``; lo que no es una lista de avisos, un error."""
        notes = json.dumps([
            {"code": "des.stockpile_footprint_at_edge", "severity": "warning", "values": {"mark": "Dos", "x": 1.0, "y": 2.0}},
            {"code": "des.stockpile_tilt_limited", "severity": "warning", "values": {
                "mark": "Dos", "fitted": 6.0, "limit": 4.0, "quantile": 0.6, "x": 1.0, "y": 2.0}}])
        found = stockpile_store.stored_notes(_stockpile(notes=notes))
        self.assertEqual([item.code for item in found], ["des.stockpile_footprint_at_edge", "des.stockpile_tilt_limited"])
        self.assertEqual([item.severity for item in found], ["warning", "warning"])
        self.assertIn("«Dos»", found[0].text("es"))
        self.assertIn("se limita a 4", found[1].text("es"))
        self.assertEqual(stockpile_store.stored_notes(_stockpile()), ())
        for bad in ('{"code": "x"}', "[1]", '[{"values": {}}]'):
            with self.subTest(notes=bad), self.assertRaises(ValueError):
                stockpile_store.stored_notes(_stockpile(notes=bad))


class EntityReportTest(unittest.TestCase):
    """RF-015-25 (plan 016 §5.5): el informe (``des_prp_``) de una entidad leído por la operación que lo escribió."""

    @staticmethod
    def _project(rows: list[tuple[object, ...]]) -> sqlite3.Connection:
        conn = _table("des_prp_retirada", store.REPORT_COLUMNS, rows)
        conn.execute("CREATE TABLE gb_dataset (uid TEXT, locator TEXT)")
        conn.execute("CREATE TABLE gb_operation_io (fid INTEGER PRIMARY KEY, operation_uid TEXT, direction TEXT, item_kind TEXT, "
                     "item_uid TEXT, role TEXT)")
        conn.execute("INSERT INTO gb_dataset VALUES ('d1', 'des_prp_retirada')")
        conn.execute("INSERT INTO gb_operation_io (operation_uid, direction, item_kind, item_uid, role) VALUES (?, 'out', 'dataset', 'd1', ?)",
                     ("op1", provenance.ENTITY_REPORT_ROLE))
        conn.execute("INSERT INTO gb_operation_io (operation_uid, direction, item_kind, item_uid, role) VALUES (?, 'in', 'dataset', 'd1', ?)",
                     ("op2", provenance.ENTITY_REPORT_ROLE))
        return conn

    def test_the_report_is_read_in_order_with_repeated_quantities(self) -> None:
        """Las filas de ``des_prp_`` de la operación que lo escribió, en su orden y con las cantidades repetidas, con su valor, su unidad y
        su nota; la operación que solo lo consume, o la que no escribió ninguno, no tiene informe."""
        conn = self._project([("removed_m3", 12.5, "m3", None), ("wall_stretch", 3.0, "m", '{"x":1}'), ("wall_stretch", 4.0, "m", None),
                              ("warning", None, None, '{"code":"a"}')])
        found = entity_store.read_entity_report(conn, "op1")
        self.assertEqual([item[0] for item in found], ["removed_m3", "wall_stretch", "wall_stretch", "warning"])
        self.assertEqual(found[0], ("removed_m3", 12.5, "m3", None))
        self.assertEqual(found[1][3], '{"x":1}')
        self.assertIsNone(found[3][1])
        self.assertEqual(entity_store.read_entity_report(conn, "op2"), (), "la que solo lo consume no lo escribió")
        self.assertEqual(entity_store.read_entity_report(conn, "otra"), ())


if __name__ == "__main__":
    unittest.main()
