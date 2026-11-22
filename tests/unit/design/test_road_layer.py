# SPDX-License-Identifier: GPL-3.0-or-later
"""La capa de ejes de pistas de una versión, **sin proyecto** (spec 017, T26; HU-017-1 y HU-017-3; RF-017-27, RF-015-27, RF-008-56, RF-009-05; plan 017 §5.2.3 «La capa de ejes de pistas»; D-19;
decisión T26-a de la sesión principal): ``des.road_layer`` es la operación de la **versión** que pone en ``des_rax_<vNN>`` una fila por pista **calculada** —``LINESTRING`` con la rasante en su Z, con su
nombre, su clase normativa, su longitud, sus cotas, su desnivel, sus pendientes, su radio mínimo, sus anchuras, su perfil y su estado—, **entera y por código** (como ``des_enl_``) y **no editable a mano**
(D-19); QGIS la abre con su estilo por clase. Con el proyecto (crear, repetir, descartar, «apoyo retirado», recalcular, cambiar un parámetro) es de ``milestone_road_layer``; con QGIS real,
``tests/referencia/core/test_ref_road_layer_qgis.py``.

- **El formato** (:class:`RoadLayerTableTest`): la fila, la tabla (``LINESTRING`` con Z, el CRS del proyecto), la escritura entera y determinista (el mismo orden de filas da los mismos bytes), la
  lectura bit a bit (la Z de cada vértice es la rasante) y los rechazos del programa.
- **Las filas** (:class:`RoadLayerRowsTest`): de lo que lee el almacén (:class:`~design.road_layer.RoadSource`) salen las filas por código, con las cifras que la operación de la pista registró.
- **La operación** (:class:`RoadLayerProvenanceTest`): su tipo, su familia, su papel, sus entradas, sus ajustes y su lugar en las listas cerradas (se recalcula, no se reproduce, no es una entidad).
- **El estilo** (:class:`RoadLayerStyleTest`): por clase (una regla por clase y estado, más «otra clase»), con todos los campos de solo lectura y su nota; se rehace si cambian las clases y respeta el
  que guardó QGIS.
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
cstore = import_geoblender("core.constraints.store")
contract = import_geoblender("core.provenance.contract")
entities = import_geoblender("design.entities")
gwkb = import_geoblender("core.gpkg.wkb")
provenance = import_geoblender("design.provenance")
road_layer = import_geoblender("design.road_layer")
store = import_geoblender("design.store")

TABLE = "des_rax_v01"
EntityState = entities.EntityState


def line(x0: float = 725_000.0, y0: float = 4_400_000.0, z0: float = 100.0, *, size: int = 4) -> np.ndarray:
    """Una línea de ``size`` estaciones con coordenadas absolutas (x, y) y una rasante que sube 0,5 m por estación."""
    return np.array([[x0 + 10.5 * number, y0 + 0.25 * number, z0 + 0.5 * number] for number in range(size)], dtype=np.float64)


def make_row(code: str = "RDW-001", name: str = "Pista a P1", **changes: Any) -> Any:
    """Una fila de la capa de prueba: una pista de 4 estaciones de la clase «Principal»."""
    values: dict[str, Any] = {
        "code": code, "name": name, "class_name": "Principal", "profile": "PISTA_PRINCIPAL", "state": "current", "points": line(),
        "length_m": 31.5, "z_start_m": 100.0, "z_end_m": 101.5, "drop_m": 1.5, "gradient_mean_pct": 4.76, "gradient_max_pct": 5.0, "radius_min_m": None,
        "width_m": 10.5, "section_m": 11.5}
    return road_layer.RoadLayerRow(**{**values, **changes})


class RoadLayerTableTest(unittest.TestCase):
    """RF-017-27, RF-008-56: la fila y la tabla ``des_rax_<vNN>``, sin proyecto."""

    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        base.create_base(self.conn, cfx.CRS)

    def dump(self) -> list[tuple[Any, ...]]:
        return self.conn.execute(f'SELECT * FROM "{TABLE}" ORDER BY fid').fetchall()

    def test_a_the_columns_are_the_ones_of_the_spec_and_the_table_is_named_by_version(self) -> None:
        """RF-017-27: la tabla tiene el nombre, la clase normativa, la longitud, las cotas de inicio y de fin, el desnivel, las pendientes media y máxima, el radio mínimo, las anchuras de la calzada y
        de la sección, el perfil y el estado (y el código de la pista), todos con su título en español; se llama ``des_rax_<vNN>`` (``rax``, una por versión) y el estilo y el dato son de la misma
        familia."""
        self.assertEqual(road_layer.COLUMN_NAMES, ("code", "name", "class_name", "state", "profile", "length_m", "z_start_m", "z_end_m", "drop_m", "gradient_mean_pct", "gradient_max_pct",
                                                   "radius_min_m", "width_m", "section_m"))
        self.assertEqual(set(road_layer.COLUMN_TITLES), set(road_layer.COLUMN_NAMES))
        self.assertTrue(set(cstyles.ROAD_FIELDS) <= set(road_layer.COLUMN_NAMES))
        self.assertEqual(road_layer.road_layer_table("V01"), TABLE)
        self.assertEqual(road_layer.road_layer_table("V12"), "des_rax_v12")
        self.assertEqual(provenance.dataset_name("rax"), cstyles.ROAD_LAYER)
        with self.assertRaises(ValueError):
            road_layer.road_layer_table("1")

    def test_b_writing_creates_a_line_layer_with_z_and_rewrites_the_whole_table_deterministically(self) -> None:
        """RF-017-27, RF-015-27: ``write_road_layer`` crea la capa (``LINESTRING`` **con Z**, registrada en ``gpkg_contents`` y ``gpkg_geometry_columns`` con el CRS del proyecto y los títulos de las
        columnas), escribe las filas por código con ``fid`` desde 1 y la **sustituye entera**: otra escritura deja solo sus filas, y las mismas filas en otro orden dan los mismos bytes."""
        rows = (make_row("RDW-002", "Ramal", points=line(725_100.0)), make_row())
        fids = road_layer.write_road_layer(self.conn, TABLE, rows, srs_id=25830)
        self.assertEqual(fids, (1, 2))
        first = self.dump()
        self.assertEqual([row[2] for row in first], ["RDW-001", "RDW-002"], "por código")
        self.assertEqual(self.conn.execute("SELECT data_type, srs_id FROM gpkg_contents WHERE table_name = ?", (TABLE,)).fetchone(), ("features", 25830))
        self.assertEqual(self.conn.execute("SELECT geometry_type_name, z, m FROM gpkg_geometry_columns WHERE table_name = ?", (TABLE,)).fetchone(), ("LINESTRING", 1, 0))
        titles = dict(self.conn.execute("SELECT column_name, title FROM gpkg_data_columns WHERE table_name = ?", (TABLE,)).fetchall())
        self.assertEqual(titles, dict(road_layer.COLUMN_TITLES))
        road_layer.write_road_layer(self.conn, TABLE, reversed(rows), srs_id=25830)
        self.assertEqual(self.dump(), first, "el orden de las filas no cambia los bytes")
        road_layer.write_road_layer(self.conn, TABLE, [make_row("RDW-007", "Otra")])
        self.assertEqual([(row[0], row[2]) for row in self.dump()], [(1, "RDW-007")])
        road_layer.write_road_layer(self.conn, TABLE, [])
        self.assertEqual(self.dump(), [])

    def test_c_the_z_of_every_vertex_is_the_gradient_and_reading_gives_back_the_same_bit_for_bit(self) -> None:
        """RF-017-27, RF-015-27: la geometría guardada es la del eje por estaciones con **la rasante en la Z de cada vértice** (coordenadas absolutas en float64: ni un bit de menos) y
        ``read_road_layer`` da las filas por ``fid`` con su capa, el estado como enumerado y lo que falta (el radio mínimo de una recta) sin valor."""
        points = np.array([[725_000.123456789, 4_400_000.000000123, 100.1], [725_010.5, 4_400_000.25, 101.25], [725_021.0, 4_400_000.5, 99.875]])
        rows = (make_row("RDW-001", "Pista a P1", points=points, radius_min_m=None),
                make_row("RDW-002", "Ramal", state=EntityState.DISCARDED, radius_min_m=35.5, points=line(725_100.0, size=2)))
        road_layer.write_road_layer(self.conn, TABLE, rows, srs_id=25830)
        geometry = gwkb.decode_geometry(bytes(self.conn.execute(f'SELECT geom FROM "{TABLE}" WHERE code = ?', ("RDW-001",)).fetchone()[0]))
        self.assertEqual((geometry.geometry_type, np.asarray(geometry.coords).tobytes()), ("LINESTRING", points.tobytes()))
        found = road_layer.read_road_layer(self.conn, TABLE)
        self.assertEqual([(item.code, item.layer, item.fid) for item in found], [("RDW-001", TABLE, 1), ("RDW-002", TABLE, 2)])
        self.assertEqual((found[0].state, found[1].state), (EntityState.CURRENT, EntityState.DISCARDED))
        self.assertIsNone(found[0].radius_min_m)
        self.assertEqual(found[1].radius_min_m, 35.5)
        self.assertEqual(found[0].points.tobytes(), points.tobytes())
        self.assertEqual(found[0].points[:, 2].tolist(), [100.1, 101.25, 99.875], "la Z es la rasante")
        self.assertEqual(road_layer.read_road_layer(self.conn, "des_rax_v09"), ())

    def test_d_what_is_not_a_calculated_road_with_a_line_is_a_program_error(self) -> None:
        """RF-017-27 (las «sin calcular» no tienen geometría): una pista sin calcular, con una línea de una sola estación, sin Z o con coordenadas que no son finitas, un código que no es el de una
        pista, un nombre en blanco, una cifra que no es finita, dos filas con el mismo código o algo que no es una fila, es ``ValueError`` o ``TypeError``: no se escribe nada."""
        bad: list[dict[str, Any]] = [
            {"state": EntityState.UNCALCULATED}, {"state": "inventado"}, {"points": line(size=1)}, {"points": np.zeros((3, 2))}, {"points": np.array([[0.0, 0.0, np.nan], [1.0, 0.0, 1.0]])},
            {"points": ()}, {"code": "P1"}, {"code": "PLT-001"}, {"name": "  "}, {"length_m": float("nan")}, {"drop_m": "mucho"}, {"class_name": 3}]
        for changes in bad:
            with self.subTest(changes=list(changes)), self.assertRaises((ValueError, TypeError)):
                make_row(**changes)
        with self.assertRaises(ValueError):
            road_layer.write_road_layer(self.conn, TABLE, [make_row(), make_row(name="Otra")], srs_id=25830)
        with self.assertRaises(TypeError):
            road_layer.write_road_layer(self.conn, TABLE, ["fila"], srs_id=25830)  # type: ignore[list-item]
        with self.assertRaises(ValueError):
            road_layer.write_road_layer(self.conn, TABLE, [make_row()])  # la tabla no existe: falta el SRS
        self.assertEqual(self.conn.execute("SELECT count(*) FROM sqlite_master WHERE name = ?", (TABLE,)).fetchone(), (0,))
        road_layer.write_road_layer(self.conn, TABLE, [make_row()], srs_id=25830)
        with self.assertRaises(ValueError):
            road_layer.write_road_layer(self.conn, TABLE, [make_row()], srs_id=4326)
        with self.assertRaises(ValueError):
            road_layer.write_road_layer(self.conn, "Tabla mal", [make_row()], srs_id=25830)


def source(code: str = "RDW-001", name: str = "Pista a P1", **changes: Any) -> Any:
    """Lo que lee el almacén de una pista calculada (una ``RoadSource``)."""
    values: dict[str, Any] = {
        "code": code, "name": name, "calc_name": "pista_a_p1", "state": EntityState.CURRENT, "profile": "PISTA_PRINCIPAL", "class_name": "Principal", "points": line(),
        "figures": {"des.road_length_m": 31.5, "des.road_z_start_m": 100.0, "des.road_z_end_m": 101.5, "des.road_drop_m": 1.5, "des.road_gradient_mean_pct": 4.76,
                    "des.road_gradient_max_pct": 5.0, "des.road_width_m": 10.5, "des.road_section_m": 11.5}}
    return road_layer.RoadSource(**{**values, **changes})


class RoadLayerRowsTest(unittest.TestCase):
    """RF-017-27: las filas de la capa salen de lo que lee el almacén, por código y con las cifras de la operación de la pista."""

    def test_a_the_rows_come_by_code_with_the_figures_of_the_road_and_no_radius_without_curves(self) -> None:
        """RF-017-27: de cada pista, una fila con su nombre, su clase, su perfil, su estado, su línea y **las cifras que registró su operación** (la longitud, las cotas, el desnivel, las pendientes, las
        anchuras); la que no tiene una (el radio mínimo de una recta) queda sin valor; por código, sea cual sea el orden de las fuentes."""
        sources = (source("RDW-010", "Décima", points=line(725_300.0)), source("RDW-002", "Ramal", figures={"des.road_length_m": 10.0, "des.road_radius_min_m": 40.0}), source())
        rows = road_layer.road_layer_rows(sources)
        self.assertEqual([row.code for row in rows], ["RDW-001", "RDW-002", "RDW-010"])
        first, second, _third = rows
        self.assertEqual((first.name, first.class_name, first.profile, first.state), ("Pista a P1", "Principal", "PISTA_PRINCIPAL", EntityState.CURRENT))
        self.assertEqual((first.length_m, first.z_start_m, first.z_end_m, first.drop_m, first.gradient_mean_pct, first.gradient_max_pct, first.radius_min_m, first.width_m, first.section_m),
                         (31.5, 100.0, 101.5, 1.5, 4.76, 5.0, None, 10.5, 11.5))
        self.assertEqual((second.length_m, second.radius_min_m, second.width_m), (10.0, 40.0, None))
        self.assertEqual(first.points.tobytes(), line().tobytes())

    def test_b_the_steps_report_one_road_each_and_give_the_same_rows(self) -> None:
        """RF-017-27, RF-015-29: ``road_layer_rows_steps`` avanza una pista por paso (con su nombre en el mensaje) y devuelve las mismas filas que ``road_layer_rows``."""
        sources = (source("RDW-002", "Ramal"), source())
        work = road_layer.road_layer_rows_steps(sources)
        seen, found = [], None
        while True:
            try:
                seen.append(next(work))
            except StopIteration as stop:
                found = stop.value
                break
        self.assertEqual([(step.done, step.total) for step in seen], [(0, 2), (1, 2)])
        self.assertIn("Pista a P1", seen[0].message)
        self.assertEqual([(row.code, row.points.tobytes()) for row in found], [(row.code, row.points.tobytes()) for row in road_layer.road_layer_rows(sources)])

    def test_c_the_layer_says_what_the_registry_says(self) -> None:
        """RF-017-27, RF-015-27 (D-1 de la 016): ``layer_differences`` compara lo que dice la capa (código → nombre, estado, clase y perfil) con lo que dice el registro y da los códigos que
        difieren, también una fila de más o de menos; iguales, ninguno."""
        wanted = {"RDW-001": ("Pista a P1", "current", "Principal", "PISTA_PRINCIPAL"), "RDW-002": ("Ramal", "stale", "Principal", "PISTA_PRINCIPAL")}
        self.assertEqual(road_layer.layer_differences(dict(wanted), wanted), ())
        shown = dict(wanted)
        shown["RDW-002"] = ("Ramal", "current", "Principal", "PISTA_PRINCIPAL")
        self.assertEqual(road_layer.layer_differences(shown, wanted), ("RDW-002",))
        shown["RDW-001"] = ("Otro nombre", "current", "Principal", "PISTA_PRINCIPAL")
        shown["RDW-009"] = ("Sobra", "current", "Principal", "PISTA_PRINCIPAL")
        self.assertEqual(road_layer.layer_differences(shown, wanted), ("RDW-001", "RDW-002", "RDW-009"))
        self.assertEqual(road_layer.layer_differences({}, wanted), ("RDW-001", "RDW-002"))
        changed = {**wanted, "RDW-001": ("Pista a P1", "current", "Secundaria", "PISTA_PRINCIPAL")}
        self.assertEqual(road_layer.layer_differences(changed, wanted), ("RDW-001",), "la clase que cambia en el perfil no la lee la pista: la capa la rehace")


class RoadLayerProvenanceTest(unittest.TestCase):
    """RF-017-27, RF-015-27, RF-009-05, RF-008-56 (T26-a): la operación ``des.road_layer`` y su familia."""

    def test_a_the_operation_is_of_the_version_repeatable_and_not_reproducible(self) -> None:
        """T26-a: ``des.road_layer`` está en las listas cerradas —los tipos de la 017, los de la versión, los que repite «Recalcular lo obsoleto»— **sin** ser reproducible ni una entidad: su contenido
        incluye el estado de cada pista, que deduce el grafo (como ``des.entity_layer``); escribe solo ``rax`` y su recálculo reúne él mismo las pistas vivas (``drops_discarded``)."""
        found = provenance.OPERATION_TYPES_BY_NAME[provenance.ROAD_LAYER]
        self.assertEqual(provenance.ROAD_LAYER, "des.road_layer")
        self.assertEqual((found.outputs, found.settings, found.figures, found.reproducible, found.drops_discarded, found.scope), ((provenance.ROAD_LAYER_TABLE,), (), (), False, True, "version"))
        self.assertIn(provenance.ROAD_LAYER, provenance.ROAD_VERSION_TYPES)
        self.assertNotIn(provenance.ROAD_LAYER, provenance.ROAD_REPRODUCIBLE)
        self.assertNotIn(provenance.ROAD_LAYER, provenance.ENTITY_OP_NAMES)
        self.assertIn(provenance.ROAD_LAYER, store.RECOMPUTED)
        self.assertEqual(found.commands, (provenance.ROAD_COMMAND,))

    def test_b_its_functions_are_declared_by_the_extension_and_a_missing_one_is_refused(self) -> None:
        """T26-a: ``road_operation_defs`` pide la función de recálculo de los **cuatro** tipos y la de reproducción de los tres que se reproducen; sobra o falta una y es ``ValueError``."""
        def never(_request: Any) -> Any:
            raise AssertionError("no se llama")

        recompute = {kind: never for kind in provenance.ROAD_VERSION_TYPES}
        reproduce = {kind: never for kind in provenance.ROAD_REPRODUCIBLE}
        defs = provenance.road_operation_defs(recompute, reproduce)
        self.assertEqual([item.op_type for item in defs], list(provenance.ROAD_VERSION_TYPES))
        self.assertIsNone(next(item for item in defs if item.op_type == provenance.ROAD_LAYER).reproduce)
        with self.assertRaises(ValueError):
            provenance.road_operation_defs({key: value for key, value in recompute.items() if key != provenance.ROAD_LAYER}, reproduce)
        with self.assertRaises(ValueError):
            provenance.road_operation_defs(recompute, {**reproduce, provenance.ROAD_LAYER: never})

    def test_c_the_family_is_one_per_version_a_read_only_layer_with_its_role(self) -> None:
        """RF-008-56, RF-009-05, D-19: la familia ``rax`` es **una por versión** (``des_rax_<vNN>``, sin el nombre de una operación), una capa del GeoPackage con el papel ``road_layer`` y **no
        editable a mano** (se bloquea si se edita en QGIS); la capa propuesta, ``rpl``, sí lo es."""
        family = provenance.FAMILIES_BY_CODE[provenance.ROAD_LAYER_TABLE]
        self.assertEqual((family.code, family.kind, family.role, family.named, family.qgis_editable), ("rax", "vector", provenance.ROAD_LAYER_ROLE, False, False))
        self.assertEqual(provenance.ROAD_LAYER_ROLE, "road_layer")
        self.assertEqual(provenance.dataset_name("rax"), "des_rax")
        self.assertEqual(provenance.dataset_locator("rax", "", "V03"), "des_rax_v03")
        spec = provenance.dataset_spec("rax", "", "V03")
        self.assertEqual((spec.name, spec.locator, spec.qgis_editable), ("des_rax", "des_rax_v03", False))
        with self.assertRaises(ValueError):
            provenance.dataset_name("rax", "una pista")
        self.assertTrue(provenance.FAMILIES_BY_CODE[provenance.ROUTE_LAYER_TABLE].qgis_editable)

    def test_d_the_inputs_are_the_data_of_each_live_road_and_the_settings_the_roads_it_shows(self) -> None:
        """RF-017-27, RF-015-27: la capa consume, de **cada pista viva** por su nombre, su huella (``des_epr_``), su eje por estaciones (``des_rdx_``) y su informe (``des_prp_``): repetir la pista deja la
        capa obsoleta, con su causa; sus ajustes son las pistas que enseña (código y nombre, también la descartada) y se leen de vuelta."""
        inputs = provenance.road_layer_inputs(["pista_a_p1", "ramal"])
        self.assertEqual([(use.item, use.role) for use in inputs], [
            ("des_epr_pista_a_p1", "entity"), ("des_rdx_pista_a_p1", "road_axis"), ("des_prp_pista_a_p1", "entity_report"),
            ("des_epr_ramal", "entity"), ("des_rdx_ramal", "road_axis"), ("des_prp_ramal", "entity_report")])
        self.assertEqual(provenance.road_layer_inputs([]), ())
        settings = provenance.road_layer_settings([("RDW-001", "Pista a P1"), ("RDW-002", "Ramal")])
        self.assertEqual(settings, {"entities": [{"code": "RDW-001", "name": "Pista a P1"}, {"code": "RDW-002", "name": "Ramal"}]})
        self.assertEqual(provenance.settings_entities(settings), (("RDW-001", "Pista a P1"), ("RDW-002", "Ramal")))
        with self.assertRaises(ValueError):
            provenance.road_layer_settings([("RDW-001", "A"), ("RDW-001", "B")])

    def test_e_the_parameters_it_reads_are_the_profile_of_each_road_and_its_class(self) -> None:
        """RF-017-27: la capa dice la clase normativa y el perfil de cada pista, que la pista **no** lee (su clase no cambia ninguna cifra): los lee la capa (``road_layer_params``: el perfil de cada
        pista y la clase de ese perfil), de modo que cambiar la clase de un perfil deja obsoleta la capa, con su causa, y no la pista."""
        keys = provenance.road_layer_params([("RDW-001", "pista_principal"), ("RDW-002", "pista_principal"), ("RDW-003", "acceso_a15")])
        self.assertEqual(keys, ("des.road.rdw_001.profile", "des.roadprofile.pista_principal.class", "des.road.rdw_002.profile", "des.road.rdw_003.profile",
                                "des.roadprofile.acceso_a15.class"))
        self.assertEqual(provenance.road_layer_params([]), ())
        with self.assertRaises(ValueError):
            provenance.road_layer_params([("PLT-001", "pista_principal")])

    def test_f_a_version_has_a_road_operation_only_if_a_live_road_was_done(self) -> None:
        """RF-017-27: ``has_road_operation`` mira si la versión tiene alguna operación ``des.road`` hecha y sin sustituir (la consulta barata que decide si hay capa de ejes que poner al día)."""
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.execute("CREATE TABLE gb_revision (uid TEXT, version_uid TEXT)")
        conn.execute("CREATE TABLE gb_operation (uid TEXT, revision_uid TEXT, op_type TEXT, status TEXT, superseded_by TEXT)")
        conn.execute("INSERT INTO gb_revision VALUES ('r1', 'v1'), ('r2', 'v2')")
        self.assertFalse(provenance.has_road_operation(conn, "v1"))
        conn.executemany("INSERT INTO gb_operation VALUES (?, ?, ?, ?, ?)", [
            ("o1", "r1", provenance.PLATFORM, "done", None), ("o2", "r1", provenance.ROAD, "done", "o9"), ("o3", "r1", provenance.ROAD, "failed", None),
            ("o4", "r2", provenance.ROAD, "done", None)])
        self.assertFalse(provenance.has_road_operation(conn, "v1"), "sustituida, fallida o de otra: no cuenta")
        self.assertTrue(provenance.has_road_operation(conn, "v2"))


# ---------------------------------------------------------------------------------------------
# El estilo
# ---------------------------------------------------------------------------------------------


def qml_of(conn: sqlite3.Connection, table: str = TABLE) -> str:
    (found,) = conn.execute("SELECT styleQML FROM layer_styles WHERE f_table_name = ? AND useAsDefault", (table,)).fetchone()
    return str(found)


class RoadLayerStyleTest(unittest.TestCase):
    """RF-017-27, RF-012-20, RF-008-56 (T26 (b)): el estilo por clase de la capa de ejes, escrito por el mismo mecanismo que el de ``des_enl_``."""

    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        base.create_base(self.conn, cfx.CRS)
        cstyles.write_styles(self.conn, [next(iter(cstore.CONSTRAINT_LAYERS.values()))])  # crea ``layer_styles``, como la primera operación de la 012

    def write(self, *rows: Any) -> None:
        road_layer.write_road_layer(self.conn, TABLE, rows, srs_id=25830)

    def rules(self, qml: str) -> list[tuple[str, str]]:
        found = ET.fromstring(qml.split("\n", 1)[1])
        return [(rule.get("label", ""), rule.get("filter", "")) for rule in found.iter("rule")]

    def test_a_the_layer_is_one_of_the_version_layers_and_has_its_fields_and_colours(self) -> None:
        """RF-012-20, RF-017-27: ``des_rax_<vNN>`` es una capa de versión con estilo (``VersionLayer.ROADS``) y las demás tablas no; el contrato del estilo son el código, el nombre, la clase, el estado y
        el perfil."""
        self.assertEqual(cstyles.version_layer("des_rax_v01"), cstyles.VersionLayer.ROADS)
        self.assertEqual(cstyles.version_layer("des_rax_v12"), cstyles.VersionLayer.ROADS)
        self.assertEqual(cstyles.version_layer("des_enl_v01"), cstyles.VersionLayer.ENTITIES)
        self.assertIsNone(cstyles.version_layer("des_rax"))
        self.assertIsNone(cstyles.version_layer("des_rpl_v01"))
        self.assertEqual(cstyles.ROAD_FIELDS, ("code", "name", "class_name", "state", "profile"))
        self.assertEqual(cstyles.ROAD_LAYER, "des_rax")

    def test_b_one_rule_per_class_and_state_plus_other_class_each_road_in_one_rule(self) -> None:
        """RF-017-27: el estilo por defecto es un renderizador por reglas con **categorías por el campo de la clase**: de cada clase, la normal, la descartada (atenuada) y la del apoyo retirado
        (marcada), y «otra clase» para la que el estilo no conoce; **solo líneas**, con todos los campos de solo lectura y la nota de que no se edita a mano."""
        row = cstyles.style_for(TABLE, ("fid", *road_layer.COLUMN_NAMES), classes=("Principal", "Secundaria"))
        self.assertEqual(row.name, cstyles.ROAD_STYLE_NAME)
        self.assertLessEqual(len(row.name), 30)
        rules = self.rules(row.qml)
        self.assertEqual(len(rules), 9)
        labels = [label for label, _filter in rules]
        self.assertEqual(labels[:3], ["Principal", "Principal descartada", "Principal con el apoyo retirado"])
        self.assertEqual(labels[3:6], ["Secundaria", "Secundaria descartada", "Secundaria con el apoyo retirado"])
        self.assertEqual(labels[6:], [cstyles.ROAD_OTHER_LABEL, f"{cstyles.ROAD_OTHER_LABEL} descartada", f"{cstyles.ROAD_OTHER_LABEL} con el apoyo retirado"])
        self.assertTrue(all("class_name" in condition for _label, condition in rules))
        self.assertIn("&quot;class_name&quot; = 'Principal'", row.qml)
        root = ET.fromstring(row.qml.split("\n", 1)[1])
        self.assertEqual(root.get("styleCategories"), "Symbology|Forms|Notes")
        self.assertEqual({symbol.get("type") for symbol in root.iter("symbol")}, {"line"})
        self.assertEqual({field.get("name"): field.get("editable") for field in root.iter("field")}, {name: "0" for name in ("fid", *road_layer.COLUMN_NAMES)})
        self.assertIn("no se edita a mano", root.find("userNotes").get("value"))  # type: ignore[union-attr]
        keys = [rule.get("key") for rule in root.iter("rule")]
        self.assertEqual(len(set(keys)), len(keys), "las claves de las reglas son únicas")
        self.assertEqual(cstyles.style_for(TABLE, ("fid", *road_layer.COLUMN_NAMES), classes=("Secundaria", "Principal")), row, "las clases salen por orden")

    def test_c_a_class_with_quotes_is_escaped_and_no_classes_still_gives_a_valid_style(self) -> None:
        """RF-017-27: una clase con comillas, «&» o «<» se escribe escapada y no rompe el documento; sin ninguna clase (una capa vacía) queda solo «otra clase», que lo pinta todo."""
        row = cstyles.style_for(TABLE, ("fid", *road_layer.COLUMN_NAMES), classes=("Pista de «servicio» <3> & \"más\" l'una",))
        root = ET.fromstring(row.qml.split("\n", 1)[1])
        self.assertEqual(len(list(root.iter("rule"))), 6)
        empty = ET.fromstring(cstyles.style_for(TABLE, None, classes=()).qml.split("\n", 1)[1])
        self.assertEqual([rule.get("label") for rule in empty.iter("rule")][:1], [cstyles.ROAD_OTHER_LABEL])
        self.assertEqual(len(list(empty.iter("rule"))), 3)
        self.assertEqual({field.get("name") for field in empty.iter("field")}, {"fid", *cstyles.ROAD_FIELDS})

    def test_d_inserting_reads_the_classes_of_the_table_and_writes_the_default_style_once(self) -> None:
        """RF-017-27, RF-012-20: ``insert_version_styles`` escribe la fila por defecto de la capa **con las clases que tiene la tabla** (y sus columnas de verdad como campos de solo lectura); repetirla
        sin cambios no la duplica ni la toca."""
        self.write(make_row(class_name="Principal"), make_row("RDW-002", "Ramal", class_name="Secundaria", points=line(725_100.0)))
        self.assertEqual(cstyles.insert_version_styles(self.conn, [TABLE]), (TABLE,))
        first = qml_of(self.conn)
        self.assertEqual([label for label, _f in self.rules(first)][::3][:2], ["Principal", "Secundaria"])
        before = self.conn.execute("SELECT id, update_time FROM layer_styles WHERE f_table_name = ?", (TABLE,)).fetchall()
        self.assertEqual(cstyles.insert_version_styles(self.conn, [TABLE]), (), "sin cambios, nada que escribir")
        self.assertEqual(self.conn.execute("SELECT id, update_time FROM layer_styles WHERE f_table_name = ?", (TABLE,)).fetchall(), before)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM layer_styles WHERE f_table_name = ?", (TABLE,)).fetchone(), (1,))

    def test_e_a_new_class_rewrites_the_style_it_wrote_but_not_the_one_saved_by_qgis(self) -> None:
        """RF-017-27, RF-012-20 («lo que guardó QGIS se respeta»): si aparece una clase nueva, **el estilo que escribió Geoblender** se rehace con ella (sigue siendo una sola fila por defecto); el que
        guardó una persona desde QGIS (con otro nombre) no se toca, nunca."""
        self.write(make_row(class_name="Principal"))
        cstyles.insert_version_styles(self.conn, [TABLE])
        self.write(make_row(class_name="Principal"), make_row("RDW-002", "Ramal", class_name="Secundaria", points=line(725_100.0)))
        self.assertEqual(cstyles.insert_version_styles(self.conn, [TABLE]), (TABLE,))
        self.assertIn("&quot;class_name&quot; = 'Secundaria'", qml_of(self.conn))
        self.assertEqual(self.conn.execute("SELECT count(*) FROM layer_styles WHERE f_table_name = ?", (TABLE,)).fetchone(), (1,))
        self.conn.execute("UPDATE layer_styles SET styleName = 'Mi estilo', styleQML = '<qgis>mío</qgis>' WHERE f_table_name = ?", (TABLE,))
        self.write(make_row(class_name="Terciaria"))
        self.assertEqual(cstyles.insert_version_styles(self.conn, [TABLE]), ())
        self.assertEqual(qml_of(self.conn), "<qgis>mío</qgis>")

    def test_f_the_style_of_the_entities_layer_and_the_project_layers_do_not_change(self) -> None:
        """RF-015-27, RF-012-20: añadir la capa de ejes no cambia el estilo de la capa de entidades ni el de las del proyecto (la 015 y la 012 sin editar): sus reglas siguen siendo las de siempre."""
        entities_style = cstyles.style_for("des_enl_v01")
        self.assertEqual(len(self.rules(entities_style.qml)), 27)
        self.assertEqual(cstyles.ENTITY_STYLE_NAME, entities_style.name)
        project = cstyles.style_for(next(iter(cstore.CONSTRAINT_LAYERS.values())))
        self.assertEqual(len(self.rules(project.qml)), 12)
        with self.assertRaises(ValueError):
            cstyles.style_for("des_rpl_v01")


class WriterTest(unittest.TestCase):
    """RF-017-27: ``DesignWriter`` ofrece la capa de ejes como salida de ``des.road_layer``."""

    def test_a_the_writer_method_exists_and_the_layer_is_a_declared_output_of_the_operation(self) -> None:
        """RF-017-27: ``DesignWriter.road_layer_steps`` prepara la capa de ejes (solo la acepta ``des.road_layer``) y la familia ``rax`` es una de las salidas de su tipo."""
        self.assertTrue(callable(store.DesignWriter.road_layer_steps))
        self.assertIn(provenance.ROAD_LAYER_TABLE, provenance.OPERATION_TYPES_BY_NAME[provenance.ROAD_LAYER].outputs)
        self.assertNotIn(provenance.ROAD_LAYER_TABLE, provenance.OPERATION_TYPES_BY_NAME[provenance.ROAD].outputs)
        self.assertIsNotNone(contract)


if __name__ == "__main__":
    unittest.main()
