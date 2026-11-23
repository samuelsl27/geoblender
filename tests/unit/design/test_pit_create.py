# SPDX-License-Identifier: GPL-3.0-or-later
"""Las filas que escribe «Crear» una corta, sin proyecto (spec 018, T23; HU-018-1, HU-018-5; RF-018-01, RF-018-25, RF-018-26, RF-018-29, RF-018-31; RF-015-01, RF-015-10, RF-015-12): la huella de la
entidad, las polilíneas y la línea de cielo con Z, las rampas por estaciones, los hallazgos, las cifras de cada banco y el informe, a partir de un ``PitOutcome``; y el formato de las líneas con Z
(``design.pit_lines``). Con proyecto, en ``milestone_pit_create``."""

from __future__ import annotations

import sqlite3
import unittest

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import pit_data as pd
from tests.support.package import import_geoblender
from tests.unit.design import milestone_pit_h1 as h1
from tests.unit.design import test_pit_bench_ramp as rp
from tests.unit.design.test_pit_compute import STEP_M, run

base = import_geoblender("core.gpkg.base")
pit_lines = import_geoblender("design.pit_lines")
pit_store = import_geoblender("design.pit_store")
provenance = import_geoblender("design.provenance")
store = import_geoblender("design.store")


class RowsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.job = h1.up_job(pd.grid_of(STEP_M))
        cls.outcome, _times = run(cls.job)

    def test_entity_row_has_the_footprint_and_one_combined_source_hash(self) -> None:
        """RF-015-01, RF-018-01: una fila de ``des_epr_`` con el tipo ``pit``, la huella en tramos y el hash de las geometrías de origen (por nombre)."""
        rows = pit_store.pit_entity_rows(self.job, self.outcome, fid=0, start_surface="terreno", support_surface=None, sources_sha256={"b": "2" * 64, "a": "1" * 64})
        self.assertEqual(len(rows), 1)
        row = dict(zip([column.name for column in store.ENTITY_COLUMNS], rows[0], strict=True))
        self.assertEqual((row["code"], row["kind"], row["mode"], row["start_surface"], row["support_surface"]), ("PIT-001", "pit", "up", "terreno", None))
        self.assertEqual(row["cells"], int(self.outcome.footprint.sum()))
        again = pit_store.pit_entity_rows(self.job, self.outcome, fid=0, start_surface="terreno", support_surface=None, sources_sha256={"a": "1" * 64, "b": "2" * 64})
        self.assertEqual(rows, again)
        changed = pit_store.pit_entity_rows(self.job, self.outcome, fid=0, start_surface="terreno", support_surface=None, sources_sha256={"a": "1" * 64, "b": "3" * 64})
        self.assertNotEqual(rows[0][7], changed[0][7])

    def test_polylines_keep_the_registered_order_with_their_z(self) -> None:
        """RF-018-25: una línea por polilínea, en el orden registrado y con la cota en la Z; el anillo no repite su primer vértice."""
        rows = pit_store.pit_polyline_rows(self.outcome)
        self.assertEqual(len(rows), len(self.outcome.polylines))
        for ordinal, (row, line) in enumerate(zip(rows, self.outcome.polylines, strict=True), start=1):
            values = dict(zip([column.name for column in pit_lines.POLYLINE_COLUMNS], row.values, strict=True))
            self.assertEqual((values["bench"], values["kind"], values["ordinal"], values["closed"]), (line.bench, line.kind.value, ordinal, int(line.closed)))
            self.assertTrue(np.array_equal(row.points, line.vertices))
            self.assertAlmostEqual(values["z_m"], line.z_m)
            self.assertAlmostEqual(values["length_m"], line.length_m)

    def test_skyline_benches_and_findings(self) -> None:
        """RF-018-26, RF-018-29, RF-018-31: la línea de cielo con Z, una fila por banco y una por hallazgo."""
        sky = pit_store.pit_skyline_rows(self.outcome)
        self.assertEqual(len(sky), len(self.outcome.skyline))
        self.assertTrue(all(np.array_equal(row.points, line) for row, line in zip(sky, self.outcome.skyline, strict=True)))
        benches = pit_store.pit_bench_rows(self.outcome)
        self.assertEqual([row[0] for row in benches], [item.bench for item in self.outcome.benches])
        self.assertAlmostEqual(sum(row[7] for row in benches), {f.key: f.value for f in self.outcome.figures}["des.pit_cut_m3"], delta=1e-6)
        findings = pit_store.pit_finding_rows(self.outcome)
        self.assertEqual(len(findings), len(self.outcome.findings))
        self.assertEqual(pit_store.pit_ramp_rows(self.outcome), [])

    def test_report_has_the_figures_and_no_nan(self) -> None:
        """RF-018-31: el informe en formato largo lleva las cifras del cálculo y ninguna que no sea finita."""
        rows = pit_store.pit_report_rows(self.outcome)
        names = [row[0] for row in rows]
        for key in ("benches", "cut_m3", "area_m2", "findings"):
            self.assertIn(key, names)
        self.assertTrue(all(row[1] is None or np.isfinite(row[1]) for row in rows))


class RampRowsTest(unittest.TestCase):
    def test_ramps_by_station(self) -> None:
        """RF-018-16: una fila por estación del eje de cada rampa, con su cota y el semiancho de la banda."""
        outcome, _times = run(rp.spiral_job())
        rows = pit_store.pit_ramp_rows(outcome)
        path = outcome.ramps[0]
        self.assertEqual(len(rows), len(path.axis))
        self.assertEqual((rows[0][0], rows[0][1], rows[0][2]), (path.code, path.bench, 1))
        self.assertEqual(rows[-1][2], len(path.axis))
        self.assertEqual((rows[0][3], rows[0][4], rows[0][5]), tuple(float(v) for v in path.axis[0]))
        self.assertEqual(rows[0][6], float(path.half_width_m[0]))


class LinesFormatTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        base.create_base(self.conn, cfx.CRS)

    def test_write_read_round_trip_with_closed_rings(self) -> None:
        """RF-018-25: la tabla se escribe entera, con los ``fid`` desde 1, la Z exacta en float64 y el anillo cerrado, y se lee igual; rescribirla da los mismos bytes."""
        ring = np.array([[4400000.123456789, 500000.5, 100.25], [4400010.0, 500000.5, 100.25], [4400010.0, 500010.0, 100.25]])
        line = np.array([[4400000.0, 500000.0, 90.0], [4400001.0, 500002.0, 91.5]])
        rows = [pit_lines.LineRow(ring, (1, "foot", "", "", 0, 1, 1, 0, 100.25, 30.0), True), pit_lines.LineRow(line, (2, "crest", "z1", "s1", 0, 2, 0, 1, 90.0, 2.2), False)]
        with self.conn:
            fids = pit_lines.write_pit_lines(self.conn, "des_pbl_demo_v01", "pbl", rows, srs_id=25830, label="Demo")
        self.assertEqual(fids, (1, 2))
        first = self.conn.execute('SELECT * FROM "des_pbl_demo_v01" ORDER BY fid').fetchall()
        back = pit_lines.read_pit_lines(self.conn, "des_pbl_demo_v01", "pbl", closed_column="closed")
        self.assertTrue(np.array_equal(back[0].points, ring) and back[0].closed)
        self.assertTrue(np.array_equal(back[1].points, line) and not back[1].closed)
        self.assertEqual(back[1].values, rows[1].values)
        with self.conn:
            pit_lines.write_pit_lines(self.conn, "des_pbl_demo_v01", "pbl", rows)
        self.assertEqual(self.conn.execute('SELECT * FROM "des_pbl_demo_v01" ORDER BY fid').fetchall(), first)

    def test_a_row_with_the_wrong_columns_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            pit_lines.write_pit_lines(self.conn, "des_psk_demo_v01", "psk", [pit_lines.LineRow(np.zeros((2, 3)), (1,))], srs_id=25830)
        with self.assertRaises(TypeError):
            pit_lines.write_pit_lines(self.conn, "des_psk_demo_v01", "psk", [object()], srs_id=25830)


if __name__ == "__main__":
    unittest.main()
