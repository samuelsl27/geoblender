# SPDX-License-Identifier: GPL-3.0-or-later
"""«Expandir banco…» y su capa propuesta ``des_pxb_``, **sin proyecto** (spec 018, T28; HU-018-2; RF-018-22, RF-018-23, RF-018-24; plan 018 §5.2.3, §5.4 A7 y §5.7 P-12): con el proyecto, en
``milestone_pit_expand``.

- **El formato** (:class:`ExpandedLayerTest`): la fila, la tabla (``LINESTRING`` con Z, el anillo cerrado, la cota y la longitud de los vértices), la escritura entera y determinista, la lectura bit a bit y los
  errores del programa.
- **La petición** (:class:`ExpandRequestTest`): sus ajustes son toda la petición y piden lo mismo otra vez; los parámetros que lee son los del perfil y la roseta, ninguno de entidad; el tipo está declarado
  con su capa editable.
- **La línea de partida** (:class:`SourcePolylineTest`): se elige por su número, su nombre o su banco, tipo y parte; sus rechazos (abierta, no plana, sin Z, sin tipo, varias, ninguna).
"""

from __future__ import annotations

import sqlite3
import unittest
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support.package import import_geoblender

base = import_geoblender("core.gpkg.base")
messages = import_geoblender("design.messages")
pit_expand = import_geoblender("design.pit_expand")
pit_layer = import_geoblender("design.pit_layer")
provenance = import_geoblender("design.provenance")
road_model = import_geoblender("design.road_model")
road_store = import_geoblender("design.road_store")

TABLE = "des_pxb_banco_v01"


def square(z: float = 100.0, x0: float = 725_000.0, size: float = 40.0) -> np.ndarray:
    """Un anillo de 4 vértices (sin repetir el primero) a la cota ``z``, con coordenadas absolutas."""
    return np.array([[x0, 4_400_000.0, z], [x0 + size, 4_400_000.0, z], [x0 + size, 4_400_040.0, z], [x0, 4_400_040.0, z]], dtype=np.float64)


def make(**changes: Any) -> Any:
    values: dict[str, Any] = {"name": "Banco", "bench": 2, "kind": "crest", "points": square(), "part": 0}
    values.update(changes)
    return pit_layer.ExpandedRow(**values)


def asked(**changes: Any) -> Any:
    values: dict[str, Any] = {"profile": "expl_10_60_6", "arc_tol_m": 0.05, "simplify_m": 1e-6}
    values.update(changes)
    return pit_expand.ExpandRequest("Cresta expandida", road_model.LayerFields("des_pbl_corta", None), "up", "terreno", **values)


class ExpandedLayerTest(unittest.TestCase):
    """RF-018-22, P-12: la fila y la tabla ``des_pxb_``, sin proyecto."""

    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        base.create_base(self.conn, cfx.CRS)

    def test_a_the_row_derives_the_level_and_the_length_and_is_checked(self) -> None:
        """RF-018-22: la cota es la Z de los vértices y la longitud la del anillo con su cierre; un tipo que no es pie ni cresta, un anillo de dos vértices y una fila sin nombre son errores del programa."""
        row = make()
        self.assertEqual((row.z_m, row.length_m), (100.0, 160.0))
        with self.assertRaises(ValueError):
            make(kind="ramp")
        with self.assertRaises(ValueError):
            make(points=square()[:2])
        with self.assertRaises(ValueError):
            make(name=" ")
        with self.assertRaises(TypeError):
            make(bench=1.5)

    def test_b_the_table_is_named_by_operation_and_version(self) -> None:
        """RF-018-22: ``des_pxb_<nombre>_<vNN>``, con el nombre en ASCII y en minúsculas."""
        self.assertEqual(pit_layer.expanded_table("Banco", "V01"), TABLE)
        self.assertEqual(pit_layer.expanded_table("Cresta del banco 2", "V03"), "des_pxb_cresta_del_banco_2_v03")
        self.assertEqual(pit_layer.EXPANDED_COLUMN_NAMES, ("name", "bench", "kind", "part", "z_m", "length_m"))
        self.assertEqual(set(pit_layer.EXPANDED_COLUMN_TITLES), set(pit_layer.EXPANDED_COLUMN_NAMES))

    def test_c_writing_is_whole_deterministic_closed_and_reads_back_bit_for_bit(self) -> None:
        """RF-018-22, RF-018-25: escribir deja una línea con Z por fila, **cerrada** (primer vértice repetido), con los ``fid`` desde 1; las mismas filas dan los mismos bytes; leer devuelve los vértices
        sin repetir, bit a bit, y la tabla se reescribe entera."""
        rows = (make(), make(name="Banco 2", part=1, points=square(110.0, x0=725_100.0)))
        fids = pit_layer.write_expanded_layer(self.conn, TABLE, rows, srs_id=cfx.CRS.epsg, name="Banco")
        self.assertEqual(fids, (1, 2))
        first = self.conn.execute(f'SELECT geom, name, bench, kind, part, z_m, length_m FROM "{TABLE}" ORDER BY fid').fetchall()
        back = pit_layer.read_expanded_layer(self.conn, TABLE)
        self.assertEqual([(item.name, item.bench, item.kind, item.part, item.fid) for item in back], [("Banco", 2, "crest", 0, 1), ("Banco 2", 2, "crest", 1, 2)])
        np.testing.assert_array_equal(back[0].points, square())
        np.testing.assert_array_equal(back[1].points, square(110.0, x0=725_100.0))
        self.assertEqual(pit_layer.write_expanded_layer(self.conn, TABLE, rows), (1, 2))
        self.assertEqual(self.conn.execute(f'SELECT geom, name, bench, kind, part, z_m, length_m FROM "{TABLE}" ORDER BY fid').fetchall(), first)
        self.assertEqual(pit_layer.write_expanded_layer(self.conn, TABLE, rows[:1]), (1,))
        self.assertEqual(len(pit_layer.read_expanded_layer(self.conn, TABLE)), 1)
        self.assertEqual(self.conn.execute("SELECT geometry_type_name, z FROM gpkg_geometry_columns WHERE table_name = ?", (TABLE,)).fetchone(), ("LINESTRING", 1))
        self.assertEqual(pit_layer.read_expanded_layer(self.conn, "des_pxb_no_existe_v01"), ())

    def test_d_the_errors_of_the_programme_write_nothing(self) -> None:
        """Dos filas con el mismo nombre, una fila que no lo es y una tabla que no existe sin SRS: ``ValueError`` o ``TypeError`` y ninguna tabla."""
        with self.assertRaises(ValueError):
            pit_layer.write_expanded_layer(self.conn, TABLE, (make(), make()), srs_id=cfx.CRS.epsg)
        with self.assertRaises(TypeError):
            pit_layer.write_expanded_layer(self.conn, TABLE, ("fila",), srs_id=cfx.CRS.epsg)
        with self.assertRaises(ValueError):
            pit_layer.write_expanded_layer(self.conn, TABLE, (make(),))
        self.assertEqual(self.conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (TABLE,)).fetchone(), None)


class ExpandRequestTest(unittest.TestCase):
    """RF-018-22, RF-015-02: la petición, sus ajustes y lo que lee la operación."""

    def test_a_the_settings_are_the_whole_request_and_ask_for_the_same_again(self) -> None:
        """RF-015-02: los ajustes llevan la petición entera y :func:`expand_request` la devuelve igual (con los valores por sector); son JSON."""
        import json

        request = asked(kind="foot", bench=1, part=2, rose="rosa", n_berm=2, corner="round", az_window_m=5.0, sector_profiles={"norte": "expl_10_45_6"})
        settings = pit_expand.expand_settings(request)
        again = pit_expand.expand_request(json.loads(json.dumps(settings)))
        self.assertEqual(again, request)
        self.assertEqual(pit_expand.expand_settings(again), settings)
        with self.assertRaises(ValueError):
            pit_expand.expand_request({"name": "x"})
        with self.assertRaises(TypeError):
            pit_expand.expand_settings("no es una petición")

    def test_b_the_request_is_checked_like_a_pit(self) -> None:
        """RF-018-22: un modo que no es arriba ni abajo, un banco que no es entero son errores del programa y un nombre vacío, un rechazo con su código."""
        with self.assertRaises(ValueError):
            pit_expand.ExpandRequest("X", road_model.LayerFields("des_pbl_c", None), "sideways", "terreno")
        with self.assertRaises(messages.DesignError):
            pit_expand.ExpandRequest("  ", road_model.LayerFields("des_pbl_c", None), "up", "terreno")
        with self.assertRaises(TypeError):
            asked(bench=1.5)
        with self.assertRaises(ValueError):
            asked(part=-1)

    def test_c_the_parameters_are_the_ones_of_the_profile_and_the_rose_and_no_entity_ones(self) -> None:
        """RF-015-08: lee los cinco valores de cada perfil y los cuatro de cada rango de cada roseta, y ninguno de una entidad (``des.pit.…``)."""
        params = pit_expand.expand_params(("expl_10_60_6",), {"rosa": 2})
        self.assertEqual(len([key for key in params if key.startswith("des.bench.expl_10_60_6.")]), 5)
        self.assertEqual(len([key for key in params if key.startswith("des.rose.rosa.")]), 8)
        self.assertFalse([key for key in params if key.startswith("des.pit.")])
        self.assertEqual(len(params), len(set(params)))

    def test_d_the_type_is_declared_with_its_editable_layer_and_the_two_figures(self) -> None:
        """P-12, RF-018-31: ``des.pit_expand`` produce solo la capa ``pxb`` (editable en QGIS) y las dos cifras de longitud, con el ámbito del nombre; no es una entidad."""
        declared = provenance.OPERATION_TYPES_BY_NAME[provenance.PIT_EXPAND]
        self.assertEqual(declared.outputs, (provenance.PIT_EXPANDED_TABLE,))
        self.assertTrue(provenance.FAMILIES_BY_CODE[provenance.PIT_EXPANDED_TABLE].qgis_editable)
        figures = provenance.pit_expand_figures("Banco", {"des.pit_len_foot_m": 10.0, "des.pit_len_crest_m": None})
        self.assertEqual([(item.key, item.value) for item in figures], [("des.pit_len_foot_m", 10.0)])


class FakeLines:
    """Una capa de líneas con Z en memoria, leída como la lee el proyecto (``road_store.read_lines_3d``)."""

    def __init__(self, rows: list[tuple[str, int, str, int, np.ndarray]]) -> None:
        self.conn = sqlite3.connect(":memory:")
        base.create_base(self.conn, cfx.CRS)
        pit_layer.create_expanded_table(self.conn, "des_pxb_x_v01", cfx.CRS.epsg, "x")
        gwkb = import_geoblender("core.gpkg.wkb")
        for name, bench, kind, part, points in rows:
            blob = gwkb.encode_geometry("LINESTRING", points, cfx.CRS.epsg, True)
            self.conn.execute('INSERT INTO "des_pxb_x_v01" (geom, name, bench, kind, part, z_m, length_m) VALUES (?, ?, ?, ?, ?, 0, 0)', (blob, name, bench, kind, part))
        self.lines = road_store.read_lines_3d(self.conn, "des_pxb_x_v01")


def closed(points: np.ndarray) -> np.ndarray:
    return np.vstack([points, points[:1]])


class SourcePolylineTest(unittest.TestCase):
    """RF-018-22, RF-018-24: la línea de partida y sus rechazos."""

    def setUp(self) -> None:
        slanted = square()
        slanted[0, 2] = 101.0
        self.fake = FakeLines([("A", 1, "foot", 0, closed(square())), ("B", 2, "crest", 0, closed(square(110.0, x0=725_100.0))), ("C", 2, "crest", 1, closed(square(110.0, x0=725_200.0))),
                               ("abierta", 3, "foot", 0, square()), ("no plana", 4, "foot", 0, closed(slanted)), ("rampa", 5, "ramp", 0, closed(square()))])
        self.addCleanup(self.fake.conn.close)

    def pick(self, **changes: Any) -> Any:
        request = pit_expand.ExpandRequest("Paso", road_model.LayerFields("des_pxb_x", "name"), "up", "terreno", profile="p", arc_tol_m=0.05, simplify_m=1e-6, **changes)
        return pit_expand.source_polyline(self.fake.lines, request)

    def refused(self, reason: str, **changes: Any) -> None:
        with self.assertRaises(messages.DesignError) as caught:
            self.pick(**changes)
        self.assertEqual(caught.exception.code, "des.pit_expand_source")
        self.assertIn(reason, caught.exception.text)
        for text in (caught.exception.text, caught.exception.text_in("en")):
            self.assertNotIn("{", text)

    def test_a_it_is_picked_by_name_by_number_or_by_bench_kind_and_part(self) -> None:
        """RF-018-22: por el nombre, por el número de fila o por el banco, el tipo y la parte; el anillo sale sin repetir el primer vértice, con la Z exacta, y el banco, el tipo y la parte, los de la fila."""
        by_name = self.pick(feature="A")
        np.testing.assert_array_equal(by_name.vertices, square())
        self.assertEqual((str(by_name.kind), by_name.bench, by_name.part), ("foot", 1, 0))
        by_number = self.pick(feature="2")
        self.assertEqual((by_number.bench, str(by_number.kind), by_number.z_m), (2, "crest", 110.0))
        by_bench = self.pick(bench=2, kind="crest", part=1)
        np.testing.assert_array_equal(by_bench.vertices, square(110.0, x0=725_200.0))
        self.assertEqual(by_bench.part, 1)

    def test_b_the_refusals_name_the_layer_the_line_and_the_reason(self) -> None:
        """RF-018-24: una línea abierta, una no plana, una que no es pie ni cresta, una que no existe y dos que coinciden se rechazan con su motivo; no se modifica la línea del usuario."""
        self.refused("abierta", feature="abierta")
        self.refused("plana", feature="no plana")
        self.refused("pie ni una cresta", feature="rampa")
        self.refused("ninguna línea", feature="no existe")
        self.refused("ninguna línea", bench=9, kind="foot")
        self.refused("indique la línea", kind="foot")
        np.testing.assert_array_equal(road_store.read_lines_3d(self.fake.conn, "des_pxb_x_v01").xyz[0], closed(square()))

    def test_c_the_lines_of_a_layer_are_described_for_the_lists_of_the_dialog(self) -> None:
        """RF-018-22, T40j (ensayo de CE-018-13): de cada línea de la capa, su número, su nombre, su banco, su tipo, su parte y su cota (la Z de sus vértices; ``None`` si no la tiene), en el orden
        de la capa, para ofrecerlas en listas en vez de pedir texto libre; **solo lee**."""
        found = pit_expand.describe_lines(self.fake.lines)
        self.assertEqual([(item.name, item.bench, item.kind, item.part) for item in found],
                         [("A", 1, "foot", 0), ("B", 2, "crest", 0), ("C", 2, "crest", 1), ("abierta", 3, "foot", 0), ("no plana", 4, "foot", 0), ("rampa", 5, "ramp", 0)])
        self.assertEqual([item.fid for item in found], [1, 2, 3, 4, 5, 6])
        self.assertEqual([item.level_m for item in found[:3]], [100.0, 110.0, 110.0])
        self.assertAlmostEqual(found[4].level_m, 100.4)
        self.assertEqual(pit_expand.describe_lines(self.fake.lines)[0].columns, True)


if __name__ == "__main__":
    unittest.main()
