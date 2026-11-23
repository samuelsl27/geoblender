# SPDX-License-Identifier: GPL-3.0-or-later
"""Las capas de cortas de una versión, **sin proyecto** (spec 018, T27; HU-018-4; RF-018-33, RF-015-27, RF-008-56, RF-009-05; plan 018 §5.2.3; D-19; el patrón de ``test_road_layer.py``):
``des.pit_layer`` es la operación de la **versión** que pone en ``des_pit_<vNN>`` una fila por polilínea de cada corta **calculada** —``LINESTRING`` con la cota en su Z, con el tipo (pie, cresta o rampa),
el banco, la cota, la zona, el sector y la longitud— y en ``des_sky_<vNN>`` una por línea de cielo, **enteras y por corta** y **no editables a mano**; QGIS las abre con su estilo por tipo. Con el proyecto
(crear, descartar, recalcular, «apoyo retirado») es de ``milestone_pit_layer``.

- **El formato** (:class:`PitLayerTableTest`): la fila, las dos tablas (``LINESTRING`` con Z, el CRS del proyecto), la escritura entera y determinista, el anillo cerrado, la lectura bit a bit y los rechazos
  del programa.
- **Las filas** (:class:`PitLayerRowsTest`): de lo que lee el almacén (:class:`~design.pit_layer.PitSource`) salen las filas por corta, con el eje de cada rampa a continuación y la línea de cielo aparte.
- **La operación** (:class:`PitLayerProvenanceTest`): su tipo, sus familias, sus papeles, sus entradas y sus ajustes.
- **El estilo** (:class:`PitLayerStyleTest`): por tipo (una regla por tipo y estado, más «otro tipo») y el de la línea de cielo, con todos los campos de solo lectura.
"""

from __future__ import annotations

import sqlite3
import unittest
import xml.etree.ElementTree as ET
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support.package import import_geoblender

base = import_geoblender("core.gpkg.base")
cstyles = import_geoblender("core.constraints.styles")
entities = import_geoblender("design.entities")
gwkb = import_geoblender("core.gpkg.wkb")
pit_layer = import_geoblender("design.pit_layer")
pit_lines = import_geoblender("design.pit_lines")
provenance = import_geoblender("design.provenance")
store = import_geoblender("design.store")

PIT_TABLE = "des_pit_v01"
SKY_TABLE = "des_sky_v01"
EntityState = entities.EntityState


def square(x0: float = 725_000.0, y0: float = 4_400_000.0, z: float = 100.0, size: float = 40.0) -> np.ndarray:
    """Un anillo de 4 vértices (sin repetir el primero) a la cota ``z``, con coordenadas absolutas."""
    return np.array([[x0, y0, z], [x0 + size, y0, z], [x0 + size, y0 + size, z], [x0, y0 + size, z]], dtype=np.float64)


def make_row(code: str = "PIT-001", name: str = "Corta A", **changes: Any) -> Any:
    """Una fila de la capa de prueba: el pie, cerrado, del banco 1."""
    values: dict[str, Any] = {"state": "current", "bench": 1, "kind": "foot", "points": square(), "ordinal": 1, "part": 1, "z_m": 100.0, "length_m": 160.0, "closed": True}
    return pit_layer.PitLayerRow(**{"code": code, "name": name, **values, **changes})


def make_sky(code: str = "PIT-001", name: str = "Corta A", **changes: Any) -> Any:
    values: dict[str, Any] = {"state": "current", "part": 1, "length_m": 30.0,
                              "points": np.array([[725_000.0, 4_400_000.0, 120.0], [725_030.0, 4_400_000.0, 121.5]], dtype=np.float64)}
    return pit_layer.SkyLayerRow(**{"code": code, "name": name, **values, **changes})


class PitLayerTableTest(unittest.TestCase):
    """RF-018-33, RF-008-56: las filas y las tablas ``des_pit_<vNN>`` y ``des_sky_<vNN>``, sin proyecto."""

    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        base.create_base(self.conn, cfx.CRS)

    def test_a_the_columns_are_the_ones_of_the_spec_and_the_tables_are_named_by_version(self) -> None:
        """RF-018-33: la tabla de polilíneas tiene la corta, su estado, el banco, el tipo, la cota, la zona, el sector y la longitud (y la parte, el orden, la rampa y si es una línea fijada), todos con su
        título en español; las dos se llaman ``des_pit_<vNN>`` y ``des_sky_<vNN>`` (una por versión) y el estilo y el dato son de la misma familia."""
        self.assertEqual(pit_layer.PIT_COLUMN_NAMES, ("code", "name", "state", "bench", "kind", "zone", "sector", "part", "ordinal", "ramp", "fixed", "z_m", "length_m"))
        self.assertEqual(pit_layer.SKY_COLUMN_NAMES, ("code", "name", "state", "part", "length_m"))
        self.assertEqual(set(pit_layer.PIT_COLUMN_TITLES), set(pit_layer.PIT_COLUMN_NAMES))
        self.assertEqual(set(pit_layer.SKY_COLUMN_TITLES), set(pit_layer.SKY_COLUMN_NAMES))
        self.assertEqual(cstyles.PIT_FIELDS, pit_layer.PIT_COLUMN_NAMES)
        self.assertEqual(cstyles.SKY_FIELDS, pit_layer.SKY_COLUMN_NAMES)
        self.assertEqual((pit_layer.pit_layer_table("V01"), pit_layer.pit_layer_table("V12")), (PIT_TABLE, "des_pit_v12"))
        self.assertEqual((pit_layer.sky_layer_table("V01"), pit_layer.sky_layer_table("V12")), (SKY_TABLE, "des_sky_v12"))
        self.assertEqual((provenance.dataset_name("pit"), provenance.dataset_name("sky")), (cstyles.PIT_LAYER, cstyles.SKY_LAYER))
        with self.assertRaises(ValueError):
            pit_layer.pit_layer_table("1")

    def test_b_writing_creates_line_layers_with_z_and_rewrites_the_whole_table_deterministically(self) -> None:
        """RF-018-33, RF-008-56: escribir crea las capas ``LINESTRING`` **con Z** en el CRS del proyecto, las registra y las **sustituye enteras**, por corta y orden y con los ``fid`` desde 1: las mismas
        filas, en cualquier orden, dan los mismos bytes; con otras filas, lo que ya no está desaparece."""
        rows = [make_row("PIT-002", "Corta B", ordinal=2), make_row(ordinal=2, bench=2, kind="crest", z_m=110.0), make_row()]
        self.assertEqual(pit_layer.write_pit_layer(self.conn, PIT_TABLE, rows, srs_id=cfx.CRS.epsg), (1, 2, 3))
        shown = self.conn.execute(f'SELECT code, ordinal FROM "{PIT_TABLE}" ORDER BY fid').fetchall()
        self.assertEqual(shown, [("PIT-001", 1), ("PIT-001", 2), ("PIT-002", 2)])
        self.assertEqual(self.conn.execute("SELECT geometry_type_name, z, srs_id FROM gpkg_geometry_columns WHERE table_name = ?", (PIT_TABLE,)).fetchone(), ("LINESTRING", 1, cfx.CRS.epsg))
        first = self.conn.execute(f'SELECT geom FROM "{PIT_TABLE}" ORDER BY fid').fetchall()
        pit_layer.write_pit_layer(self.conn, PIT_TABLE, list(reversed(rows)))
        self.assertEqual(self.conn.execute(f'SELECT geom FROM "{PIT_TABLE}" ORDER BY fid').fetchall(), first)
        pit_layer.write_pit_layer(self.conn, PIT_TABLE, rows[:1])
        self.assertEqual(self.conn.execute(f'SELECT COUNT(*) FROM "{PIT_TABLE}"').fetchone(), (1,))
        pit_layer.write_pit_layer(self.conn, PIT_TABLE, [])
        self.assertEqual(self.conn.execute(f'SELECT COUNT(*) FROM "{PIT_TABLE}"').fetchone(), (0,))
        self.assertEqual(pit_layer.write_sky_layer(self.conn, SKY_TABLE, [make_sky(part=2), make_sky()], srs_id=cfx.CRS.epsg), (1, 2))
        self.assertEqual(self.conn.execute(f'SELECT part FROM "{SKY_TABLE}" ORDER BY fid').fetchall(), [(1,), (2,)])

    def test_c_the_z_of_every_vertex_is_the_level_a_ring_is_closed_and_reading_gives_back_the_same_bit_for_bit(self) -> None:
        """RF-018-33: la Z de cada vértice es la cota (float64 exacto, coordenadas absolutas), un anillo se guarda con su primer vértice repetido al final y la lectura da los mismos vértices, con su
        capa y su ``fid``; la línea de cielo, igual."""
        wavy = np.array([[725_000.123456789, 4_400_000.987654321, 100.000000001], [725_010.5, 4_400_005.25, 100.5], [725_020.0, 4_400_000.0, 101.75]], dtype=np.float64)
        pit_layer.write_pit_layer(self.conn, PIT_TABLE, [make_row(), make_row(ordinal=2, bench=2, kind="crest", points=wavy, closed=False, z_m=None)], srs_id=cfx.CRS.epsg)
        (blob,) = self.conn.execute(f'SELECT geom FROM "{PIT_TABLE}" WHERE fid = 1').fetchone()
        self.assertEqual(np.asarray(gwkb.decode_geometry(bytes(blob), external=True).coords).reshape(-1, 3).shape, (5, 3))
        ring, crest = pit_layer.read_pit_layer(self.conn, PIT_TABLE)
        np.testing.assert_array_equal(ring.points, np.vstack([square(), square()[:1]]))
        np.testing.assert_array_equal(crest.points, wavy)
        self.assertEqual((ring.layer, ring.fid, crest.fid, crest.z_m, ring.state), (PIT_TABLE, 1, 2, None, EntityState.CURRENT))
        pit_layer.write_sky_layer(self.conn, SKY_TABLE, [make_sky()], srs_id=cfx.CRS.epsg)
        (line,) = pit_layer.read_sky_layer(self.conn, SKY_TABLE)
        np.testing.assert_array_equal(line.points, make_sky().points)
        self.assertEqual(pit_layer.read_pit_layer(self.conn, "des_pit_v99"), ())
        self.assertEqual(pit_layer.read_sky_layer(self.conn, "des_sky_v99"), ())

    def test_d_what_is_not_a_calculated_pit_with_a_line_is_a_program_error(self) -> None:
        """RF-018-33: el programa no escribe lo que no es una corta calculada con su línea: un código que no es de corta, un estado sin líneas (sin calcular), un tipo desconocido, una línea de un solo
        vértice o con coordenadas no finitas, dos filas con la misma corta y orden, y una tabla que no existe sin el SRS."""
        for changes in ({"code": "RDW-001"}, {"state": "uncalculated"}, {"kind": "berm"}, {"points": square()[:1]}, {"points": np.array([[1.0, 2.0, np.nan], [2.0, 3.0, 4.0]])}, {"name": " "}):
            with self.subTest(changes=changes), self.assertRaises((ValueError, TypeError)):
                make_row(**changes)
        with self.assertRaises(ValueError):
            pit_layer.write_pit_layer(self.conn, PIT_TABLE, [make_row(), make_row()], srs_id=cfx.CRS.epsg)
        with self.assertRaises(ValueError):
            pit_layer.write_pit_layer(self.conn, PIT_TABLE, [make_row()])
        with self.assertRaises(TypeError):
            pit_layer.write_pit_layer(self.conn, PIT_TABLE, [object()], srs_id=cfx.CRS.epsg)
        with self.assertRaises(ValueError):
            pit_layer.write_sky_layer(self.conn, SKY_TABLE, [make_sky(), make_sky()], srs_id=cfx.CRS.epsg)
        with self.assertRaises(ValueError):
            pit_layer.write_pit_layer(self.conn, "Des Pit", [], srs_id=cfx.CRS.epsg)
        pit_layer.write_pit_layer(self.conn, PIT_TABLE, [make_row()], srs_id=cfx.CRS.epsg)
        with self.assertRaises(ValueError):
            pit_layer.write_pit_layer(self.conn, PIT_TABLE, [make_row()], srs_id=4326)


def line_row(bench: int, kind: str, z: float, *, closed: bool = True, part: int = 1, ordinal: int = 1, zone: str = "", sector: str = "", fixed: int = 0) -> Any:
    points = square(z=z) if closed else np.array([[725_000.0, 4_400_000.0, z], [725_040.0, 4_400_000.0, z]], dtype=np.float64)
    return pit_lines.LineRow(points, (bench, kind, zone, sector, part, ordinal, int(closed), fixed, z, 160.0 if closed else 40.0), closed)


def make_source(code: str = "PIT-001", name: str = "Corta A", state: Any = EntityState.CURRENT, *, ramps: bool = True) -> Any:
    stations = np.array([[725_000.0 + 5 * n, 4_400_000.0, 100.0 + 0.5 * n] for n in range(4)], dtype=np.float64)
    return pit_layer.PitSource(code, name, name.lower().replace(" ", "_"), EntityState(state),
                               (line_row(1, "foot", 100.0, ordinal=1), line_row(1, "crest", 110.0, ordinal=2, closed=False, zone="Z1", sector="norte", fixed=1)),
                               (make_sky_line(),), (("RMP-001", 1, stations),) if ramps else ())


def make_sky_line() -> Any:
    return pit_lines.LineRow(np.array([[725_000.0, 4_400_000.0, 120.0], [725_030.0, 4_400_040.0, 121.5]], dtype=np.float64), (1, 50.0))


class PitLayerRowsTest(unittest.TestCase):
    """RF-018-33: de lo que lee el almacén salen las filas."""

    def test_a_the_rows_come_by_pit_with_the_ramp_axes_after_the_polylines_and_the_skyline_apart(self) -> None:
        """RF-018-33: las filas salen por código de corta; de cada una, sus polilíneas tal cual (tipo, banco, zona, sector, parte, orden, cota, longitud, si está fijada), **a continuación el eje de cada
        rampa** como una línea de tipo ``ramp`` con su banco, su rampa y la longitud en planta (sin cota: sube), y su línea de cielo en la otra tabla con su longitud en planta."""
        lines, sky = pit_layer.pit_layer_rows([make_source("PIT-002", "Corta B", EntityState.DISCARDED), make_source()])
        self.assertEqual([(row.code, row.kind, row.ordinal) for row in lines],
                         [("PIT-001", "foot", 1), ("PIT-001", "crest", 2), ("PIT-001", "ramp", 3), ("PIT-002", "foot", 1), ("PIT-002", "crest", 2), ("PIT-002", "ramp", 3)])
        crest, ramp = lines[1], lines[2]
        self.assertEqual((crest.zone, crest.sector, crest.fixed, crest.z_m, crest.closed), ("Z1", "norte", 1, 110.0, False))
        self.assertEqual((ramp.ramp, ramp.bench, ramp.z_m, ramp.fixed, ramp.length_m, str(ramp.state)), ("RMP-001", 1, None, 0, 15.0, "current"))
        self.assertTrue(lines[0].closed)
        self.assertEqual([(row.code, row.part, row.length_m, str(row.state)) for row in sky], [("PIT-001", 1, 50.0, "current"), ("PIT-002", 1, 50.0, "discarded")])

    def test_b_the_steps_report_one_pit_each_and_give_the_same_rows(self) -> None:
        """RF-018-33, RNF-018-06: los pasos cuentan una corta cada uno y dan las mismas filas que la versión de una vez."""
        sources = [make_source(), make_source("PIT-002", "Corta B")]
        work = pit_layer.pit_layer_rows_steps(sources)
        seen = []
        while True:
            try:
                seen.append(next(work))
            except StopIteration as stop:
                lines, sky = stop.value
                break
        self.assertEqual([(step.done, step.total) for step in seen], [(0, 2), (1, 2)])
        once_lines, once_sky = pit_layer.pit_layer_rows(sources)
        self.assertEqual([(row.code, row.ordinal) for row in lines], [(row.code, row.ordinal) for row in once_lines])
        self.assertEqual(len(sky), len(once_sky))

    def test_c_the_layer_says_what_the_registry_says(self) -> None:
        """RF-018-33: ``layer_differences`` da los códigos en que la capa no dice lo del registro (otro nombre, otro estado, falta o sobra), por orden de código; ninguno si dicen lo mismo."""
        shown = {"PIT-001": ("Corta A", "current"), "PIT-002": ("Corta B", "current"), "PIT-003": ("Corta C", "current")}
        self.assertEqual(pit_layer.layer_differences(shown, dict(shown)), ())
        wanted = {"PIT-001": ("Corta A", "stale"), "PIT-002": ("Corta B", "current"), "PIT-004": ("Corta D", "current")}
        self.assertEqual(pit_layer.layer_differences(shown, wanted), ("PIT-001", "PIT-003", "PIT-004"))
        self.assertEqual(pit_layer.layer_differences({}, {}), ())


class PitLayerProvenanceTest(unittest.TestCase):
    """RF-018-33, RF-009-05, RF-008-56: la operación ``des.pit_layer`` y sus familias."""

    def test_a_the_operation_is_of_the_version_repeatable_and_not_reproducible(self) -> None:
        """``des.pit_layer`` está en las listas cerradas de la 018 —los de la versión, los que repite «Recalcular lo obsoleto»— **sin** ser reproducible ni una entidad; escribe ``pit`` y ``sky`` y su
        recálculo reúne él mismo las cortas vivas (``drops_discarded``)."""
        found = provenance.OPERATION_TYPES_BY_NAME[provenance.PIT_LAYER]
        self.assertEqual(provenance.PIT_LAYER, "des.pit_layer")
        self.assertEqual((found.outputs, found.settings, found.figures, found.reproducible, found.drops_discarded, found.scope),
                         ((provenance.PIT_LAYER_TABLE, provenance.PIT_SKY_LAYER_TABLE), (), (), False, True, "version"))
        self.assertIn(provenance.PIT_LAYER, provenance.PIT_VERSION_TYPES)
        self.assertNotIn(provenance.PIT_LAYER, provenance.PIT_REPRODUCIBLE)
        self.assertNotIn(provenance.PIT_LAYER, provenance.ENTITY_OP_NAMES)
        self.assertIn(provenance.PIT_LAYER, store.RECOMPUTED)

    def test_b_the_families_are_one_per_version_read_only_layers_with_their_roles(self) -> None:
        """RF-008-56: ``pit`` y ``sky`` son capas de **una por versión** (sin nombre de operación), de líneas, no editables a mano y con sus papeles."""
        for family, role in ((provenance.PIT_LAYER_TABLE, provenance.PIT_LAYER_ROLE), (provenance.PIT_SKY_LAYER_TABLE, provenance.PIT_SKY_LAYER_ROLE)):
            with self.subTest(family=family):
                found = provenance.FAMILIES_BY_CODE[family]
                self.assertEqual((found.kind, found.role, found.named, found.qgis_editable), ("vector", role, False, False))
        self.assertEqual(provenance.dataset_locator(provenance.PIT_LAYER_TABLE, "", "V03"), "des_pit_v03")
        self.assertEqual(provenance.dataset_locator(provenance.PIT_SKY_LAYER_TABLE, "", "V03"), "des_sky_v03")

    def test_c_the_inputs_are_the_data_of_each_live_pit_and_the_settings_the_pits_it_shows(self) -> None:
        """RF-018-33: lo que consume es, de **cada corta viva**, sus polilíneas, su línea de cielo y sus rampas (con sus papeles); los ajustes, las cortas que enseña, también la descartada; sin repetir."""
        found = provenance.pit_layer_inputs(["corta_a", "corta_b", "corta_a"])
        self.assertEqual([(use.item, use.role) for use in found], [
            ("des_pbl_corta_a", provenance.PIT_POLYLINES_ROLE), ("des_psk_corta_a", provenance.PIT_SKYLINE_ROLE), ("des_prl_corta_a", provenance.PIT_RAMPS_ROLE),
            ("des_pbl_corta_b", provenance.PIT_POLYLINES_ROLE), ("des_psk_corta_b", provenance.PIT_SKYLINE_ROLE), ("des_prl_corta_b", provenance.PIT_RAMPS_ROLE)])
        self.assertEqual(provenance.pit_layer_inputs([]), ())
        self.assertEqual(provenance.pit_layer_settings([("PIT-001", "Corta A"), ("PIT-002", "Corta B")]),
                         {"entities": [{"code": "PIT-001", "name": "Corta A"}, {"code": "PIT-002", "name": "Corta B"}]})
        with self.assertRaises(ValueError):
            provenance.pit_layer_settings([("PIT-001", "A"), ("PIT-001", "B")])
        with self.assertRaises(ValueError):
            provenance.pit_layer_settings([("PIT-001", " ")])

    def test_d_a_version_has_a_pit_operation_only_if_a_live_pit_was_done(self) -> None:
        """RF-018-33: ``has_pit_operation`` mira una operación ``des.pit`` hecha y sin sustituir de la versión (una consulta); sin ella, las capas no se cargan."""
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.executescript(
            "CREATE TABLE gb_operation (uid TEXT, revision_uid TEXT, op_type TEXT, status TEXT, superseded_by TEXT);"
            "CREATE TABLE gb_revision (uid TEXT, version_uid TEXT);"
            "INSERT INTO gb_revision VALUES ('r1', 'v1');"
            "INSERT INTO gb_operation VALUES ('o1', 'r1', 'des.pit', 'done', NULL);"
            "INSERT INTO gb_operation VALUES ('o2', 'r1', 'des.pit', 'done', 'o3');")
        self.assertTrue(provenance.has_pit_operation(conn, "v1"))
        self.assertFalse(provenance.has_pit_operation(conn, "v2"))
        conn.execute("UPDATE gb_operation SET superseded_by = 'o9' WHERE uid = 'o1'")
        self.assertFalse(provenance.has_pit_operation(conn, "v1"))
        conn.execute("UPDATE gb_operation SET op_type = 'des.road', superseded_by = NULL WHERE uid = 'o1'")
        self.assertFalse(provenance.has_pit_operation(conn, "v1"))


class PitLayerStyleTest(unittest.TestCase):
    """RF-018-33, RF-008-56: el estilo por tipo de las dos capas."""

    def rules(self, table: str, **kwargs: Any) -> tuple[list[ET.Element], ET.Element]:
        row = cstyles.style_for(table, **kwargs)
        root = ET.fromstring(row.qml.split("\n", 1)[1])
        return list(root.iter("rule")), root

    def test_a_the_layers_are_version_layers_with_their_fields_and_styles(self) -> None:
        """RF-018-33: ``des_pit_<vNN>`` y ``des_sky_<vNN>`` son capas de versión con su estilo, de nombre propio, y el resto de las capas siguen igual."""
        self.assertEqual(cstyles.version_layer("des_pit_v01"), cstyles.VersionLayer.PITS)
        self.assertEqual(cstyles.version_layer("des_sky_v12"), cstyles.VersionLayer.SKYLINES)
        self.assertIsNone(cstyles.version_layer("des_pit_rose"))
        self.assertIsNone(cstyles.version_layer("des_pit_v01_x"))
        self.assertEqual(cstyles.style_for("des_pit_v01").name, cstyles.PIT_STYLE_NAME)
        self.assertEqual(cstyles.style_for("des_sky_v01").name, cstyles.SKY_STYLE_NAME)
        self.assertLessEqual(max(len(cstyles.PIT_STYLE_NAME), len(cstyles.SKY_STYLE_NAME)), 30)
        self.assertEqual(cstyles.version_layer("des_rax_v01"), cstyles.VersionLayer.ROADS)

    def test_b_one_rule_per_kind_and_state_plus_other_kind_each_line_in_one_rule(self) -> None:
        """RF-018-33: las polilíneas se pintan **por tipo** (pie, cresta, rampa y «otro tipo»), cada uno normal, descartado (atenuado) y con el apoyo retirado (marcado): 12 reglas con su símbolo cada
        una, que no se solapan; todos los campos, de solo lectura."""
        rules, root = self.rules("des_pit_v01")
        self.assertEqual(len(rules), 4 * 3)
        self.assertEqual(len(list(root.iter("symbol"))), 12)
        labels = [rule.get("label") for rule in rules]
        for label in ("Pie", "Cresta", "Rampa", "Otro tipo", "Pie descartada", "Rampa con el apoyo retirado"):
            self.assertIn(label, labels)
        self.assertEqual(len({rule.get("key") for rule in rules}), 12)
        self.assertEqual([field.get("name") for field in root.iter("field")], ["fid", *cstyles.PIT_FIELDS])
        self.assertTrue(all(field.get("editable") == "0" for field in root.iter("field")))
        conds = {rule.get("label"): rule.get("filter") for rule in rules}
        self.assertIn("\"kind\" = 'foot'", conds["Pie"] or "")

    def test_c_the_skyline_has_one_kind_and_three_states(self) -> None:
        """RF-018-33: la línea de cielo, un solo tipo con sus tres variantes (normal, atenuada, marcada) y sus campos de solo lectura."""
        rules, root = self.rules("des_sky_v01")
        self.assertEqual(len(rules), 3)
        self.assertEqual([field.get("name") for field in root.iter("field")], ["fid", *cstyles.SKY_FIELDS])

    def test_d_inserting_writes_the_default_style_once_with_the_fields_of_the_table(self) -> None:
        """RF-018-33: insertar el estilo por defecto de las dos capas lo escribe una vez, con los campos que la tabla tiene de verdad, y repetirlo no duplica."""
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        base.create_base(conn, cfx.CRS)
        cstyles.write_styles(conn, list(cstyles.CONSTRAINT_LAYERS.values()))
        pit_layer.write_pit_layer(conn, PIT_TABLE, [make_row()], srs_id=cfx.CRS.epsg)
        pit_layer.write_sky_layer(conn, SKY_TABLE, [make_sky()], srs_id=cfx.CRS.epsg)
        self.assertEqual(cstyles.insert_version_styles(conn, [PIT_TABLE, SKY_TABLE]), (PIT_TABLE, SKY_TABLE))
        self.assertEqual(cstyles.insert_version_styles(conn, [PIT_TABLE, SKY_TABLE]), ())
        names = dict(conn.execute("SELECT f_table_name, styleName FROM layer_styles WHERE f_table_name IN (?, ?)", (PIT_TABLE, SKY_TABLE)).fetchall())
        self.assertEqual(names, {PIT_TABLE: cstyles.PIT_STYLE_NAME, SKY_TABLE: cstyles.SKY_STYLE_NAME})


class WriterTest(unittest.TestCase):
    """RF-018-33: el almacén escribe las capas."""

    def test_a_the_writer_methods_exist_and_both_layers_are_declared_outputs_of_the_operation(self) -> None:
        """RF-018-33: ``DesignWriter`` tiene los pasos de las dos capas y la operación declara las dos como salida."""
        self.assertTrue(callable(store.DesignWriter.pit_layer_steps))
        self.assertTrue(callable(store.DesignWriter.sky_layer_steps))
        self.assertEqual(provenance.OPERATION_TYPES_BY_NAME[provenance.PIT_LAYER].outputs, (provenance.PIT_LAYER_TABLE, provenance.PIT_SKY_LAYER_TABLE))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
