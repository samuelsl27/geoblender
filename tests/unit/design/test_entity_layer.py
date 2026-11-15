# SPDX-License-Identifier: GPL-3.0-or-later
"""La capa de entidades de una versión y el GeoTIFF de la superficie de una entidad (spec 015, T30; HU-015-1;
RF-015-27, RF-008-56, RF-009-05, RF-013-34; plan 015 §5.2.3, §5.3.2, §5.4 y P-7; ADR-0030 §5; D-13).

``des.entity_layer`` es la operación de la **versión** que pone en ``des_enl_<vNN>`` una fila por cada entidad
**calculada** (el contorno de su huella, el tipo, el nombre, el estado que deduce el grafo, de qué parte, en qué se
apoya, su cadena y sus cifras principales), **no editable a mano** (D-13) y con su estilo por tipo (T22); la
encadena cada orden de entidades tras la declaración y las máscaras, como operación aparte y en su propia
transacción (P-7). Sobre la cantera sintética de la 014 con las capas de plataformas (``tests.support.
entity_fixtures``) y su rejilla gruesa de 2 m, con las funciones reales de recalcular de la plataforma, de la
declaración, de la capa de entidades y de la compilación de las máscaras:

- **El formato** (:class:`LayerTableTest`, sin proyecto): la fila, la tabla, la escritura entera y determinista
  (el mismo orden de filas da los mismos bytes), la lectura y los rechazos.
- **La capa refleja las órdenes** (:class:`LayerTest`, en el orden de las pruebas): (a) crear una entidad la
  pone en la capa con todo lo suyo, contado a mano; (b) su operación (entradas, sin parámetros, salida no
  editable, su estilo); (c) crear otra que se apoya en la primera; (d) cambiar un parámetro y «Recalcular lo
  obsoleto» ponen al día sus cifras; (e) descartar una deja su fila descartada y a la que parte de ella con el
  «apoyo retirado»; (f) las «sin calcular» no salen.
- **Si falla** (:class:`LayerFailureTest`): si la regeneración falla tras cambiar una entidad, la capa queda
  **obsoleta con su causa** (la de la 008) y «Recalcular lo obsoleto» la rehace; tras crear una, el fallo se
  cuenta y la orden siguiente la repara; sin tocar lo demás de la cadena.
- **La exportación** (:class:`LayerExportTest`): la superficie de una entidad se exporta a GeoTIFF como las de la
  013 (RF-013-34): en el CRS del proyecto, con las cotas de la superficie guardada (float32, como el resto de
  entregables), sin escribir en el proyecto ni sobrescribir sin confirmar.
"""

from __future__ import annotations

import json
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import quarry_fixtures as qfx
from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender
from tests.unit.design import test_after_entity_change as chain_test
from tests.unit.design import test_declare_operation as decl
from tests.unit.design import test_entity_supports as sup
from tests.unit.design import test_platform_operation as ops
from tests.unit.design import test_platform_prepare as prep

access = import_geoblender("gis.masks.access")
base = import_geoblender("core.gpkg.base")
cstyles = import_geoblender("core.constraints.styles")
design_params = import_geoblender("design.params")
dataset_registry = import_geoblender("core.datasets.registry")
entities = import_geoblender("design.entities")
entity_layer = import_geoblender("design.entity_layer")
entity_store = import_geoblender("design.entity_store")
export = import_geoblender("design.export")
gis_provenance = import_geoblender("gis.provenance")
paths = import_geoblender("core.paths")
provenance = import_geoblender("design.provenance")
reader = import_geoblender("gis.geotiff.reader")
recompute_mod = import_geoblender("core.provenance.recompute")
versions_model = import_geoblender("core.versions.model")

LAYER = provenance.ENTITY_LAYER
TABLE = "des_enl_v01"
LOADING, OVER, DRAG = prep.LOADING, sup.OVER, sup.DRAG
START = prep.START
EntityState = entities.EntityState
NO_READ_ONLY = paths.ReadOnlyDirs.from_sources(None, [])
GRADIENT = design_params.entity_key("PLT-001", "gradient_pct")
ARROW = " → "
NODATA = -9999.0
EDITOR = decl.EDITOR


def square(west: float, south: float, side: float) -> tuple[tuple[np.ndarray, ...], ...]:
    """El contorno (cerrado, antihorario) de un cuadrado: una parte con su anillo exterior."""
    ring = np.array([[west, south], [west + side, south], [west + side, south + side],
                     [west, south + side], [west, south]], dtype=np.float64)
    return ((ring,),)


def make_row(code: str = "PLT-001", name: str = "Carga", **changes: Any) -> Any:
    """Una fila de la capa de prueba (de un cuadrado de 10 m de lado)."""
    values: dict[str, Any] = {
        "code": code, "name": name, "kind": "platform", "state": "current", "start": START,
        "supports": "", "chain": f"{START}{ARROW}{name}", "parts": square(725_000.0, 4_400_000.0, 10.0),
        "area_m2": 100.0, "cut_m3": 12.5, "fill_m3": 0.0, "edge_cut_m3": 3.0, "edge_fill_m3": 1.5}
    return entity_layer.EntityLayerRow(**{**values, **changes})


# ---------------------------------------------------------------------------------------------
# El formato
# ---------------------------------------------------------------------------------------------


class LayerTableTest(unittest.TestCase):
    """RF-015-27, RF-008-56: la fila y la tabla ``des_enl_<vNN>``, sin proyecto."""

    def setUp(self) -> None:
        import sqlite3

        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        base.create_base(self.conn, cfx.CRS)

    def dump(self) -> list[tuple[Any, ...]]:
        return self.conn.execute(f'SELECT * FROM "{TABLE}" ORDER BY fid').fetchall()

    def test_a_the_columns_are_the_style_contract_plus_the_figures_and_the_table_is_named_by_version(self) -> None:
        """RF-015-27, RF-012-20: la tabla tiene los campos del contrato del estilo (``kind``, ``name``, ``state``,
        ``supports``, ``chain``), el código, de qué parte y las cinco cifras principales, todos con su título en
        español; se llama ``des_enl_<vNN>`` (``enl``, una por versión)."""
        self.assertTrue(set(cstyles.ENTITY_FIELDS) <= set(entity_layer.COLUMN_NAMES))
        self.assertEqual(entity_layer.COLUMN_NAMES, ("code", "name", "kind", "state", "start", "supports", "chain",
                                                     *entity_layer.FIGURE_COLUMNS))
        self.assertEqual(set(entity_layer.COLUMN_TITLES), set(entity_layer.COLUMN_NAMES))
        self.assertEqual(entity_layer.entity_layer_table("V01"), TABLE)
        self.assertEqual(entity_layer.entity_layer_table("V12"), "des_enl_v12")
        self.assertEqual(provenance.dataset_name("enl"), cstyles.ENTITY_LAYER)
        with self.assertRaises(ValueError):
            entity_layer.entity_layer_table("1")

    def test_b_writing_rewrites_the_whole_table_deterministically(self) -> None:
        """RF-015-27: ``write_entity_layer`` crea la capa (``MULTIPOLYGON`` 2D, registrada en ``gpkg_contents`` y
        ``gpkg_geometry_columns``, con los títulos de las columnas), escribe las filas por código con ``fid`` desde
        1 y la **sustituye entera**: otra escritura deja solo sus filas, con los ``fid`` desde 1 otra vez, y las
        mismas filas en otro orden dan los mismos bytes."""
        rows = (make_row("PLT-002", "Taller", parts=square(725_020.0, 4_400_000.0, 10.0)), make_row())
        fids = entity_layer.write_entity_layer(self.conn, TABLE, rows, srs_id=25830)
        self.assertEqual(fids, (1, 2))
        first = self.dump()
        self.assertEqual([row[2] for row in first], ["PLT-001", "PLT-002"], "por código")
        self.assertEqual(self.conn.execute(
            "SELECT data_type, srs_id FROM gpkg_contents WHERE table_name = ?", (TABLE,)).fetchone(),
            ("features", 25830))
        self.assertEqual(self.conn.execute(
            "SELECT geometry_type_name, z, m FROM gpkg_geometry_columns WHERE table_name = ?",
            (TABLE,)).fetchone(), ("MULTIPOLYGON", 0, 0))
        titles = dict(self.conn.execute("SELECT column_name, title FROM gpkg_data_columns WHERE table_name = ?",
                                        (TABLE,)).fetchall())
        self.assertEqual(titles, dict(entity_layer.COLUMN_TITLES))
        entity_layer.write_entity_layer(self.conn, TABLE, reversed(rows), srs_id=25830)
        self.assertEqual(self.dump(), first, "el orden de las filas no cambia los bytes")
        entity_layer.write_entity_layer(self.conn, TABLE, [make_row("PLT-007", "Otra")])
        again = self.dump()
        self.assertEqual([(row[0], row[2]) for row in again], [(1, "PLT-007")])
        entity_layer.write_entity_layer(self.conn, TABLE, [])
        self.assertEqual(self.dump(), [])

    def test_c_reading_gives_back_what_was_written_bit_for_bit(self) -> None:
        """RF-015-27: ``read_entity_layer`` da las filas por ``fid`` con su capa, el estado y el tipo como
        enumerados, las cifras que faltan sin valor y el contorno en float64 idéntico (coordenadas absolutas)."""
        ring = np.array([[725_000.123456789, 4_400_000.000000123], [725_010.5, 4_400_000.0],
                         [725_010.5, 4_400_010.25], [725_000.123456789, 4_400_000.000000123]])
        hole = np.array([[725_002.0, 4_400_002.0], [725_002.0, 4_400_004.0], [725_004.0, 4_400_004.0],
                         [725_002.0, 4_400_002.0]])
        rows = (make_row("PLT-001", "Carga", parts=((ring, hole), square(725_050.0, 4_400_000.0, 2.0)[0]),
                         cut_m3=None, supports="Sobre la carga (Plataforma): 8 000 m³ apoyados"),
                make_row("PLT-002", "Taller", state=EntityState.DISCARDED))
        entity_layer.write_entity_layer(self.conn, TABLE, rows, srs_id=25830)
        found = entity_layer.read_entity_layer(self.conn, TABLE)
        self.assertEqual([(item.code, item.layer, item.fid) for item in found],
                         [("PLT-001", TABLE, 1), ("PLT-002", TABLE, 2)])
        self.assertEqual((found[0].state, found[1].state), (EntityState.CURRENT, EntityState.DISCARDED))
        self.assertEqual(str(found[0].kind), "platform")
        self.assertIsNone(found[0].cut_m3)
        self.assertEqual(found[0].supports, rows[0].supports)
        self.assertEqual(len(found[0].parts), 2)
        for mine, theirs in zip(found[0].parts, rows[0].parts, strict=True):
            self.assertEqual(len(mine), len(theirs))
            for got, expected in zip(mine, theirs, strict=True):
                self.assertEqual(got.tobytes(), expected.tobytes())
        self.assertEqual(entity_layer.read_entity_layer(self.conn, "des_enl_v09"), ())

    def test_d_what_is_not_a_calculated_entity_with_a_footprint_is_a_program_error(self) -> None:
        """RF-015-27 (las «sin calcular» no tienen geometría): una entidad sin calcular, sin contorno o con uno
        que no es un anillo cerrado, un código que no es de una entidad, un nombre en blanco, una cifra que no es
        finita, dos filas con el mismo código o algo que no es una fila, es ``ValueError`` o ``TypeError``: no se
        escribe nada."""
        bad: list[dict[str, Any]] = [
            {"state": EntityState.UNCALCULATED}, {"state": "inventado"}, {"parts": ()},
            {"parts": (((np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]]),),))},
            {"parts": (((np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]),),))},
            {"code": "P1"}, {"name": "  "}, {"area_m2": float("nan")}, {"cut_m3": "mucho"}, {"kind": "balsa"}]
        for changes in bad:
            with self.subTest(changes=list(changes)), self.assertRaises((ValueError, TypeError)):
                make_row(**changes)
        with self.assertRaises(ValueError):
            entity_layer.write_entity_layer(self.conn, TABLE, [make_row(), make_row(name="Otra")], srs_id=25830)
        with self.assertRaises(TypeError):
            entity_layer.write_entity_layer(self.conn, TABLE, ["fila"], srs_id=25830)  # type: ignore[list-item]
        with self.assertRaises(ValueError):
            entity_layer.write_entity_layer(self.conn, TABLE, [make_row()])  # la tabla no existe: falta el SRS
        self.assertEqual(self.conn.execute("SELECT count(*) FROM sqlite_master WHERE name = ?",
                                           (TABLE,)).fetchone(), (0,))
        entity_layer.write_entity_layer(self.conn, TABLE, [make_row()], srs_id=25830)
        with self.assertRaises(ValueError):
            entity_layer.write_entity_layer(self.conn, TABLE, [make_row()], srs_id=4326)
        with self.assertRaises(ValueError):
            entity_layer.write_entity_layer(self.conn, "Tabla mal", [make_row()], srs_id=25830)


# ---------------------------------------------------------------------------------------------
# Con proyecto
# ---------------------------------------------------------------------------------------------


class LayerCase(chain_test.ChainCase):
    """Lo de ``ChainCase`` (las plataformas, la declaración, la capa de entidades y la compilación de las
    máscaras con sus funciones reales) más la capa de ejes de las pruebas de lo que se apoya y los ayudantes de
    la capa de entidades."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.clock.advance(minutes=1)
        qfx.write_feature_layer(cls.project, cls.clock, sup.support_layer())
        cls.clock.advance(minutes=1)

    @classmethod
    def layer_rows(cls, version: Any = None) -> dict[str, Any]:
        """Las filas de la capa de entidades de ``version`` (por defecto V01), por código."""
        target = cls.v1 if version is None else version
        with cls.project.read() as conn:
            return {item.code: item for item in entity_layer.read_entity_layer(
                conn, entity_layer.entity_layer_table(target.code))}

    @classmethod
    def layer_dump(cls) -> list[tuple[Any, ...]]:
        """Todo el contenido de la tabla de la capa de V01, tal cual (bytes de la geometría incluidos)."""
        return cls.query_of(f'SELECT * FROM "{TABLE}" ORDER BY fid')

    @classmethod
    def layer_operations(cls, version: Any = None) -> list[tuple[Any, ...]]:
        """Las operaciones ``des.entity_layer`` de la versión (uid, estado, sustituida por), por orden."""
        target = cls.v1 if version is None else version
        return cls.query_of(
            "SELECT o.uid, o.status, o.superseded_by FROM gb_operation AS o JOIN gb_revision AS r ON "
            "r.uid = o.revision_uid WHERE r.version_uid = ? AND o.op_type = ? ORDER BY o.fid", target.uid, LAYER)

    @classmethod
    def current_layer(cls, version: Any = None) -> str:
        """El uid de la operación de la capa vigente de la versión (hecha y sin sustituir)."""
        found = [uid for uid, status, replaced in cls.layer_operations(version)
                 if status == "done" and replaced is None]
        assert len(found) == 1, found
        return str(found[0])

    @classmethod
    def layer_record(cls, version: Any = None) -> Any:
        """El dato ``des_enl`` de la versión (por defecto V01)."""
        target = cls.v1 if version is None else version
        with cls.project.read() as conn:
            return dataset_registry.get(conn, provenance.dataset_name(provenance.ENTITY_MAP_TABLE),
                                        version_uid=target.uid)

    @classmethod
    def figure(cls, code: str, key: str) -> float:
        """La cifra ``key`` de la operación vigente de la entidad ``code`` de V01."""
        entry = entities.registry(cls.project, cls.v1.uid).get(code)
        assert entry is not None and entry.operation_uid is not None, code
        (value,) = cls.query_of("SELECT value FROM gb_figure WHERE operation_uid = ? AND key = ?",
                                entry.operation_uid, key)[0]
        return float(value)

    @classmethod
    def made_confirmed(cls, asked: Any) -> Any:
        """«Calcula» y «crea» ``asked`` con la contrapendiente que sale confirmada por la persona."""
        cls.clock.advance(minutes=1)
        calculation = cls.calculate_in(asked, masks=None)
        calculation.confirm_counterslope()
        return calculation.create()

    @classmethod
    def made_over(cls) -> Any:
        """«Sobre la carga» (P2): de la superficie de P1, «en corte y relleno»; se apoya en P1."""
        return cls.made(sup.over())

    @classmethod
    def style_rows(cls, table: str) -> list[tuple[Any, ...]]:
        return cls.query_of("SELECT f_table_name, f_geometry_column, styleName, useAsDefault, styleQML "
                            "FROM layer_styles WHERE f_table_name = ? ORDER BY id", table)

    def check_polygon(self, code: str, row: Any) -> None:
        """El contorno de ``row`` es el de la huella de la entidad ``code`` (sus tramos de ``des_epr_``, con
        otra construcción: ``declared_zone_of_runs``) y su área, la de sus celdas a mano."""
        runs = self.entity_runs(code)
        zone = entities.declared_zone_of_runs(runs, self.grid, 0.0)
        self.assertEqual(len(row.parts), len(zone.parts))
        for mine, theirs in zip(row.parts, zone.parts, strict=True):
            self.assertEqual(len(mine), len(theirs))
            for got, expected in zip(mine, theirs, strict=True):
                self.assertEqual(got.tobytes(), expected.tobytes())
        cells = sum(last - first for _row, first, last in runs)
        area = 0.0
        for part in row.parts:
            for ring in part:  # la fórmula del topógrafo: el exterior suma, los huecos restan
                x, y = ring[:, 0], ring[:, 1]
                area += 0.5 * float(np.sum(x[:-1] * y[1:] - x[1:] * y[:-1]))
        self.assertAlmostEqual(area, cells * ops.CELL_M2, delta=1e-9 * cells * ops.CELL_M2)


class LayerTest(LayerCase):
    """RF-015-27, P-7: V01 con P1 («Plataforma de carga», del terreno), P2 («Sobre la carga», de la superficie de
    P1, «en corte y relleno»: se apoya en ella) y P3 («Arrastra el terreno», de la superficie de P2), en el orden
    de las pruebas."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.p1 = cls.made(prep.request())

    # --- (a) Crear -----------------------------------------------------------------------------------

    def test_a_creating_an_entity_puts_it_in_the_layer_with_everything_counted_by_hand(self) -> None:
        """RF-015-27: tras crear P1 y lo que sigue, ``des_enl_v01`` tiene **una** fila, la de P1: su código, su
        nombre, el tipo ``platform``, el estado «al día», de qué parte, **sin apoyo**, su cadena
        («partida → Plataforma de carga»), las cinco cifras de la operación (área, corte y relleno de la huella,
        corte y relleno del borde, de ``gb_figure``) y el contorno de su huella con el área de sus celdas a mano
        (1.000 celdas de 2 m: 4.000 m²)."""
        self.assertEqual(self.layer_operations(), [])
        chain = self.chain()
        self.assertIsNone(chain.failure)
        self.assertEqual((chain.layer, chain.layer_changed, chain.layer_failure), (1, True, None))
        rows = self.layer_rows()
        self.assertEqual(list(rows), ["PLT-001"])
        row = rows["PLT-001"]
        self.assertEqual((row.name, str(row.kind), row.state, row.start, row.supports),
                         (LOADING, "platform", EntityState.CURRENT, START, ""))
        self.assertEqual(row.chain, f"{START}{ARROW}{LOADING}")
        for column, key in (("area_m2", "des.plat_area_m2"), ("cut_m3", "des.plat_cut_m3"),
                            ("fill_m3", "des.plat_fill_m3"), ("edge_cut_m3", "des.edge_cut_m3"),
                            ("edge_fill_m3", "des.edge_fill_m3")):
            self.assertEqual(getattr(row, column), self.figure("PLT-001", key), column)
        self.assertEqual(row.area_m2, 4_000.0)
        self.assertEqual((row.layer, row.fid), (TABLE, 1))
        self.check_polygon("PLT-001", row)
        self.assertEqual(sorted(code for code in self.layer_rows()), ["PLT-001"])

    def test_b_the_operation_records_its_inputs_no_parameters_and_a_data_not_editable_by_hand(self) -> None:
        """RF-015-27, RF-008-56, RF-009-05, P-7: la operación ``des.entity_layer`` de V01, hecha, consume el
        ``des_epr_`` (papel ``entity``) y el ``des_prp_`` (papel ``entity_report``, de donde salen las cifras) de
        las entidades **vivas**, no lee ningún parámetro, deja en sus ajustes las entidades que recoge y escribe
        el dato ``des_enl`` (una capa de polígonos de ``des``, vigente, **no editable a mano**); y como la
        declaración, es una operación y una transacción aparte (la entidad ya estaba creada)."""
        uid = self.current_layer()
        epr, prp = (provenance.dataset_name(family, LOADING) for family in ("epr", "prp"))
        self.assertEqual(self.query(
            "SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'in' ORDER BY io.fid", uid),
            [(epr, "entity"), (prp, "entity_report")])
        self.assertEqual(self.query("SELECT key FROM gb_operation_param WHERE operation_uid = ?", uid), [])
        ((settings, status, message),) = self.query("SELECT settings, status, message FROM gb_operation "
                                                    "WHERE uid = ?", uid)
        self.assertEqual(json.loads(settings), provenance.entity_layer_settings([("PLT-001", LOADING)]))
        self.assertEqual(status, "done")
        self.assertIn("1", message)
        self.assertEqual(self.query(
            "SELECT d.name, d.kind, d.module, d.status, d.locator FROM gb_operation_io AS io JOIN gb_dataset AS d "
            "ON d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'out'", uid),
            [("des_enl", "vector", "des", "current", TABLE)])
        record = self.layer_record()
        self.assertFalse(record.qgis_editable)
        self.assertEqual(str(record.status), "current")
        self.assertEqual(self.query("SELECT role FROM gb_operation_io WHERE operation_uid = ? AND direction = 'out'",
                                    uid), [("entity_map",)])
        self.assertEqual(self.query("SELECT count(*) FROM gb_figure WHERE operation_uid = ?", uid), [(0,)])
        # La declaración y la capa son operaciones distintas, cada una en su revisión abierta.
        self.assertNotEqual(uid, self.current_declaration())

    def test_b_the_style_row_is_written_in_the_same_transaction_with_every_field_read_only(self) -> None:
        """RF-015-27, RF-012-20, RF-009-05: la operación escribe la fila de estilo por defecto de ``des_enl_v01``
        en ``layer_styles`` (la de ``core.constraints.styles``, T22) con **todas** las columnas de la tabla de
        verdad marcadas de solo lectura; repetir la capa no la duplica."""
        rows = self.style_rows(TABLE)
        self.assertEqual([row[:4] for row in rows], [(TABLE, "geom", cstyles.ENTITY_STYLE_NAME, 1)])
        with self.project.read() as conn:
            columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{TABLE}")') if row[1] != "geom"]
        self.assertEqual(columns, ["fid", *entity_layer.COLUMN_NAMES])
        root = ET.fromstring(rows[0][4].split("\n", 1)[1])
        (editable,) = root.iter("editable")
        self.assertEqual({field.get("name"): field.get("editable") for field in editable.iter("field")},
                         dict.fromkeys(columns, "0"))
        self.assertEqual(rows[0][4], cstyles.style_for(TABLE, columns).qml)

    def test_b_repeating_the_chain_changes_nothing_but_the_operation(self) -> None:
        """RF-015-27, P-7: repetir lo que sigue a la orden (sin cambiar nada) da **otra operación** que sustituye
        a la anterior (queda como historia) con los mismos bytes de la capa y el mismo hash, no duplica el
        estilo ni deja nada obsoleto."""
        before, digest, dump = self.current_layer(), self.layer_record().content_sha256, self.layer_dump()
        chain = self.chain()
        self.assertEqual((chain.layer, chain.layer_changed, chain.layer_failure), (1, False, None))
        self.assertNotEqual(self.current_layer(), before)
        self.assertEqual(self.query("SELECT superseded_by FROM gb_operation WHERE uid = ?", before),
                         [(self.current_layer(),)])
        self.assertEqual((self.layer_record().content_sha256, self.layer_dump()), (digest, dump))
        self.assertEqual(len(self.style_rows(TABLE)), 1)
        self.assertEqual(self.recompute_plan(), [])

    # --- (c) Crear otra, que se apoya en la primera -----------------------------------------------------

    def test_c_a_second_entity_that_rests_on_the_first_adds_its_row_with_what_it_rests_on(self) -> None:
        """RF-015-27, RF-015-15, RF-015-04: crear P2 («en corte y relleno» sobre la superficie de P1) la pone en
        la capa con su apoyo —«… (Plataforma): 8 000 m³ apoyados», el de ``entities.dependencies_of``—, y la
        cadena de las dos es la misma: «partida → Plataforma de carga → Sobre la carga»; P1 sigue sin apoyo y
        ya lleva su cadena entera. Las dos están al día."""
        self.made_over()
        chain = self.chain()
        self.assertEqual((chain.layer, chain.layer_changed), (2, True))
        rows = self.layer_rows()
        self.assertEqual(list(rows), ["PLT-001", "PLT-002"])
        first, second = rows["PLT-001"], rows["PLT-002"]
        expected = f"{START}{ARROW}{LOADING}{ARROW}{OVER}"
        self.assertEqual((first.chain, second.chain), (expected, expected))
        self.assertEqual((first.state, second.state), (EntityState.CURRENT, EntityState.CURRENT))
        self.assertEqual(first.supports, "")
        depends = [item for item in entities.dependencies_of(self.project, self.v1.uid, "PLT-002")
                   if "supported_on" in item.roles]
        self.assertEqual([item.name for item in depends], [LOADING])
        self.assertEqual(second.supports, "; ".join(item.text("es") for item in depends))
        self.assertIn(LOADING, second.supports)
        self.assertIn("m³ apoyados", second.supports)
        self.assertEqual((second.start, second.name), (LOADING, OVER), "parte de la superficie de P1: su nombre")
        self.check_polygon("PLT-002", second)
        self.assertEqual(self.recompute_plan(), [])

    # --- (d) Cambiar y recalcular ---------------------------------------------------------------------

    def test_d_changing_a_parameter_leaves_the_layer_stale_and_recomputing_brings_its_figures_up_to_date(self) -> None:
        """RF-015-27, RF-015-16, RF-008-24, RF-008-26: cambiar la pendiente de P1 deja obsoletas P1 y P2 (la
        cascada de la 008) **y la capa**, que las consume, con su causa; «Recalcular lo obsoleto» las rehace en
        orden —las entidades y, tras ellas, la capa (``recompute_entity_layer``)—: no queda nada obsoleto y las
        cifras de P1 y de P2 en la capa son las nuevas (las de ``gb_figure``). Como la salida de P1 cambia
        (las cifras), la capa no se salta aunque sus ``des_epr_`` no cambien."""
        stale_before = self.layer_dump()
        layer = self.current_layer()
        self.change(GRADIENT, 0.5)
        self.assertTrue(self.stale_causes(layer), "la capa consume lo que quedó obsoleto")
        self.assertIn((LAYER,), self.recompute_plan())
        done = self.settle()
        types = [self.query("SELECT op_type FROM gb_operation WHERE uid = ?", uid)[0][0]
                 for result in done for uid in result.operations]
        self.assertEqual(types.count(LAYER), 1, types)
        self.assertEqual(self.recompute_plan(), [])
        self.assertNotEqual(self.current_layer(), layer)
        self.assertNotEqual(self.layer_dump(), stale_before)
        rows = self.layer_rows()
        for code in ("PLT-001", "PLT-002"):
            with self.subTest(code=code):
                row = rows[code]
                self.assertEqual((row.state, row.cut_m3, row.fill_m3),
                                 (EntityState.CURRENT, self.figure(code, "des.plat_cut_m3"),
                                  self.figure(code, "des.plat_fill_m3")))
                self.assertEqual(row.edge_cut_m3, self.figure(code, "des.edge_cut_m3"))
        self.assertEqual(self.stale_causes(self.current_layer()), set())

    # --- (e) «Apoyo retirado» y descartar --------------------------------------------------------------

    def test_e_discarding_leaves_the_row_discarded_and_what_started_from_it_with_the_support_removed(self) -> None:
        """RF-015-27, RF-015-17, D-12: con P3 («Arrastra el terreno», de la superficie de P2) creada, descartar
        P2 la deja en la capa como **descartada** (sigue en el proyecto, con su huella) y deja a P3 con el
        **«apoyo retirado»**; P1 sigue al día. La capa se pone al día **dentro de la propia orden** (la cadena de
        «Descartar»): su contorno y sus cifras siguen siendo los de la entidad."""
        self.made_confirmed(sup.asked(DRAG, start="entity:PLT-002"))
        self.chain()
        before = self.layer_rows()["PLT-002"]
        self.assertEqual(self.layer_rows()["PLT-003"].state, EntityState.CURRENT)
        self.clock.advance(minutes=1)
        done = ops.finish(entity_store.discard_entity_steps(self.project, self.v1.uid, "PLT-002",
                                                            reason="Prueba de la T30", decided_by=EDITOR))
        self.assertEqual((done.chain.layer, done.chain.layer_failure), (3, None))
        rows = self.layer_rows()
        self.assertEqual({code: row.state for code, row in rows.items()},
                         {"PLT-001": EntityState.CURRENT, "PLT-002": EntityState.DISCARDED,
                          "PLT-003": EntityState.SUPPORT_REMOVED})
        self.assertEqual((rows["PLT-002"].area_m2, rows["PLT-002"].cut_m3), (before.area_m2, before.cut_m3))
        self.assertEqual([part[0].tobytes() for part in rows["PLT-002"].parts],
                         [part[0].tobytes() for part in before.parts])
        self.assertEqual(rows["PLT-003"].chain.split(ARROW)[-1], DRAG, "la cadena de la que perdió su apoyo")
        self.assertEqual(self.layer_record().content_sha256, self.query(
            "SELECT content_sha256 FROM gb_dataset WHERE name = 'des_enl' AND status = 'current'")[0][0])
        # La descartada no es entrada de la capa (sus datos están descartados); las vivas, sí.
        inputs = {name for (name,) in self.query(
            "SELECT d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'in'", self.current_layer())}
        self.assertNotIn(provenance.dataset_name("epr", OVER), inputs)
        self.assertIn(provenance.dataset_name("epr", LOADING), inputs)
        self.assertIn(provenance.dataset_name("epr", DRAG), inputs)

    # --- (f) Las «sin calcular» no salen ----------------------------------------------------------------

    def test_f_the_entities_not_calculated_have_no_geometry_and_are_not_in_the_layer(self) -> None:
        """RF-015-27 (las sin calcular no tienen geometría), RF-015-18: traer las entidades de V01 a V02 las
        deja **sin calcular** (parámetros sin operación): la capa de V02 no tiene ninguna fila (existe, vacía), y
        la de V01 no cambia."""
        before = self.layer_dump()
        brought = entity_store.bring_entities(self.project, self.v1, self.v2)
        self.assertTrue(brought.entities)
        listed = entities.registry(self.project, self.v2.uid)
        self.assertTrue(all(entry.record.state is EntityState.UNCALCULATED for entry in listed))
        self.clock.advance(minutes=1)
        stored = ops.finish(entity_store.entity_layer_steps(self.project, self.v2))
        self.assertEqual(stored.records[0].locator, "des_enl_v02")
        self.assertEqual(self.layer_rows(self.v2), {})
        self.assertEqual(self.query_of('SELECT count(*) FROM "des_enl_v02"'), [(0,)])
        self.assertEqual(self.layer_dump(), before)

    def test_g_without_an_editable_version_nothing_is_done(self) -> None:
        """RF-009-21: la capa se rechaza sin versión (``core.version_required``) o con una que no existe
        (``core.version_unknown``) y no escribe nada."""
        before = self.written()
        for version, code in ((None, "core.version_required"), ("V99", "core.version_unknown")):
            with self.subTest(version=version), self.assertRaises(versions_model.VersionError) as caught:
                ops.finish(entity_store.entity_layer_steps(self.project, version))
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(json.dumps(self.written(), default=str), json.dumps(before, default=str))


# ---------------------------------------------------------------------------------------------
# Si falla
# ---------------------------------------------------------------------------------------------


class LayerFailureTest(LayerCase):
    """RF-015-27, P-7: lo que pasa si la capa no se puede regenerar. P1 creada con su capa."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())
        cls.chain()

    def test_a_a_failed_regeneration_leaves_the_layer_stale_with_its_cause_and_recompute_redoes_it(self) -> None:
        """RF-015-27, P-7 (ADR-0030 §5): P1 cambia (su pendiente) y se recalcula **sola** (como una orden de
        entidades que no encadenó): la capa, que la consumía, queda obsoleta con su causa (otro contenido de su
        informe). Lo que sigue a la orden **falla** al escribir la capa (el disco): el fallo va en el resultado
        con su etapa y su aviso, la declaración y las máscaras **sí** se hicieron, la capa sigue como estaba
        —vigente, obsoleta, **con su causa**— y no queda ninguna operación «en curso»; el fallo no es un estado
        escondido: «Recalcular lo obsoleto» la rehace, con las cifras de ahora."""
        old_layer, dump = self.current_layer(), self.layer_dump()
        self.change(GRADIENT, 0.5)
        self.clock.advance(minutes=1)
        p1 = self.current("PLT-001")
        ops.finish(recompute_mod.recompute_steps(self.project, scope=p1))
        self.assertNotEqual(self.current("PLT-001"), p1)
        causes = self.stale_causes(old_layer)
        self.assertTrue(causes, "la capa consume el informe que cambió")
        self.assertIn("dataset_changed", {kind for kind, _name in causes})
        self.assertIn(provenance.dataset_name("prp", LOADING), {name for _kind, name in causes})
        with mock.patch.object(entity_store, "entity_layer_rows_steps", side_effect=OSError("disco lleno")):
            chain = self.chain()
        self.assertIsNone(chain.failure, "la declaración y las máscaras no fallaron")
        self.assertEqual((chain.layer, chain.layer_changed), (None, False))
        self.assertIs(chain.layer_failure.stage, entity_store.ChainStage.LAYER)
        self.assertIsInstance(chain.layer_failure.error, OSError)
        (warning,) = [item for item in chain.notices() if item.severity == "warning"]
        self.assertEqual(warning.code, "des.entity_chain_layer_failed")
        self.assertIn("disco lleno", warning.text("es"))
        self.assertIn("Recalcular lo obsoleto", warning.text("es"))
        self.assertEqual(self.current_layer(), old_layer, "la capa que había sigue vigente")
        self.assertEqual(self.layer_dump(), dump, "sin cambiar nada de lo escrito")
        self.assertEqual(self.stale_causes(old_layer), causes, "y obsoleta, con su causa")
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE op_type = ? ORDER BY fid DESC LIMIT 1",
                                    LAYER), [("failed",)], "el intento queda como historia, fallido")
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation WHERE status = 'running'"), [(0,)])
        self.assertEqual(chain.declared, 0)
        self.assertIs(self.state(), access.MaskState.CURRENT, "la declaración y las máscaras siguen al día")
        self.assertIn((LAYER,), self.recompute_plan())
        self.settle()
        self.assertEqual(self.recompute_plan(), [])
        self.assertNotEqual(self.current_layer(), old_layer)
        row = self.layer_rows()["PLT-001"]
        self.assertEqual((row.state, row.cut_m3, row.fill_m3),
                         (EntityState.CURRENT, self.figure("PLT-001", "des.plat_cut_m3"),
                          self.figure("PLT-001", "des.plat_fill_m3")))

    def test_b_a_failure_after_creating_an_entity_is_told_and_the_next_order_repairs_it(self) -> None:
        """RF-015-27, P-7: crear P2 y fallar la capa (el disco) cuenta el fallo —la entidad está creada— y la capa
        sigue sin P2; la orden siguiente de entidades la pone al día (una entidad nueva no es una entrada de la
        capa de antes: el grafo no la ve obsoleta, y por eso el aviso lo dice)."""
        self.made_over()
        with mock.patch.object(entity_store, "entity_layer_rows_steps", side_effect=OSError("disco lleno")):
            chain = self.chain()
        self.assertIsNotNone(chain.layer_failure)
        self.assertEqual(list(self.layer_rows()), ["PLT-001"])
        self.assertIn("la próxima vez", [item for item in chain.notices() if item.severity == "warning"][0].text("es"))
        repaired = self.chain()
        self.assertEqual((repaired.layer, repaired.layer_failure), (2, None))
        self.assertEqual(list(self.layer_rows()), ["PLT-001", "PLT-002"])

    def test_c_a_refused_layer_leaves_nothing_half_done_when_it_is_closed_midway(self) -> None:
        """RF-015-29, RF-015-27, P-7: cerrar lo que sigue a la orden (Esc) a mitad de la capa no deja la capa a
        medias: la operación queda cancelada, la capa vigente es la de antes y no hay ninguna «en curso»."""
        dump, layer = self.layer_dump(), self.current_layer()
        work = entity_store.after_entity_change(self.project, self.v1, budget_s=1e-9)
        for step in work:
            if step.message.startswith("Capa de entidades"):  # la operación de la capa ya empezó
                break
        else:  # pragma: no cover - lo asegura el presupuesto mínimo
            self.fail("la cadena no llegó a la capa de entidades")
        work.close()
        self.assertEqual(self.layer_dump(), dump)
        self.assertEqual(self.current_layer(), layer)
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation WHERE status = 'running'"), [(0,)])
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE op_type = ? ORDER BY fid DESC LIMIT 1",
                                    LAYER), [("cancelled",)])


# ---------------------------------------------------------------------------------------------
# La exportación a GeoTIFF
# ---------------------------------------------------------------------------------------------


class LayerExportTest(LayerCase):
    """RF-015-27 (como RF-013-34): la superficie de P1 de V01 exportada a GeoTIFF."""

    out: ClassVar[Path]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())
        cls.out = cls.enterClassContext(project_tmp("gb-ex-"))

    def stored(self) -> Any:
        """La superficie guardada de P1 en V01, tal cual (float64, NaN sin dato)."""
        record = self.record(provenance.dataset_name("psf", LOADING), self.v1)
        return reader.read_geotiff(self.root.joinpath(*record.locator.split("/")), max_cells=sys.maxsize)

    def export(self, name: str = "carga.tif", **options: Any) -> Path:
        options.setdefault("read_only", NO_READ_ONLY)
        options.setdefault("version", self.v1.uid)
        return export.export_grid(self.project, provenance.ENTITY_SURFACE_GRID, LOADING, self.out / name,
                                  **options)

    def counts(self) -> tuple[int, ...]:
        return tuple(self.query(f"SELECT count(*) FROM {table}")[0][0]
                     for table in ("gb_operation", "gb_dataset", "gb_event"))

    def test_a_the_surface_of_an_entity_is_an_exportable_grid_found_by_its_name_or_uid(self) -> None:
        """RF-015-27, RF-013-34: ``des_psf_`` es una rejilla exportable (``export.GRIDS``); ``stored_grid`` la
        encuentra por su nombre o por su uid —su familia, el nombre de su operación y su versión— y también desde la
        tabla de la entidad (``des_epr_``, la que enseña la vista); una tabla que no es de una entidad, un dato que
        no existe o descartado, no."""
        self.assertIn(provenance.ENTITY_SURFACE_GRID, export.GRIDS)
        dataset = provenance.dataset_name("psf", LOADING)
        record = self.record(dataset, self.v1)
        for ref in (dataset, record.uid, provenance.dataset_name("epr", LOADING)):
            with self.subTest(ref=ref):
                found = export.stored_grid(self.project, ref, version=self.v1.uid)
                self.assertEqual((found.family, found.name, found.version_code, found.record.uid),
                                 (provenance.ENTITY_SURFACE_GRID, gis_provenance.dataset_slug(LOADING), "V01",
                                  record.uid))
        for ref in (provenance.dataset_name("prp", LOADING), "des_psf_no_existe", "des_epr_no_existe"):
            with self.subTest(ref=ref), self.assertRaises(import_geoblender("design.messages").DesignError) as caught:
                export.stored_grid(self.project, ref, version=self.v1.uid)
            self.assertEqual(caught.exception.code, "des.export_not_grid")

    def test_b_the_geotiff_is_georeferenced_in_the_project_crs_with_the_elevations_of_the_stored_surface(self) -> None:
        """RF-015-27, RF-013-34, RF-006-24: el GeoTIFF se lee de nuevo con ``gis`` con la rejilla de la superficie
        guardada, el CRS del proyecto (EPSG:25830) y su referencia vertical, el «sin dato» −9999 declarado y cada
        cota **igual a la guardada pasada a float32** (0 m de diferencia, y a media unidad de float32 de la de
        float64: el entregable es Float32 como los de la 013); los metadatos dicen su unidad, qué es, el dato y la
        versión."""
        stored = self.stored()
        path = self.export()
        found = reader.read_geotiff(path, max_cells=sys.maxsize)
        self.assertEqual(found.grid, stored.grid)
        self.assertEqual((found.declared_crs.epsg, found.declared_vertical.epsg),
                         (self.project.record.crs_epsg, self.project.record.vcrs_epsg))
        self.assertEqual((found.source_dtype, found.nodata_value), ("float32", NODATA))
        finite = np.isfinite(stored.values)
        self.assertTrue(finite.any())
        expected = np.where(finite, stored.values.astype(np.float32).astype(np.float64), np.nan)
        np.testing.assert_array_equal(found.values, expected)
        self.assertFalse((found.values == NODATA).any())
        half_unit = np.spacing(np.abs(stored.values[finite]).astype(np.float32)) / 2
        self.assertTrue((np.abs(found.values[finite] - stored.values[finite]) <= half_unit).all())
        tiff = import_geoblender("gis.geotiff.tiff")
        geokeys = import_geoblender("gis.geotiff.geokeys")
        with path.open("rb") as stream:
            ifd = tiff.read_first_ifd(stream, path.stat().st_size)
        self.assertEqual(geokeys.parse_gdal_items(ifd.text(tiff.GDAL_METADATA) or ""), {
            "UNIDAD": "m", "TIPO": "Superficie de la entidad",
            "DATO": provenance.dataset_name("psf", LOADING), "VERSION": "V01"})

    def test_c_exporting_writes_nothing_in_the_project_and_never_overwrites_without_asking(self) -> None:
        """RF-015-27, RF-013-34, D-29 de la 011: exportar no es una operación (ni operaciones, ni datos ni eventos
        nuevos, y ningún temporal); sobre un fichero que ya existe se rechaza (``gis.export_target_exists``) y
        queda como estaba, y solo con ``overwrite`` se sustituye, con los mismos bytes."""
        before = self.counts()
        other = self.export("otra.tif")
        self.assertEqual(self.counts(), before)
        original = other.read_bytes()
        gis_messages = import_geoblender("gis.messages")
        with self.assertRaises(gis_messages.GisError) as caught:
            self.export("otra.tif")
        self.assertEqual(caught.exception.code, "gis.export_target_exists")
        self.assertEqual(other.read_bytes(), original)
        self.export("otra.tif", overwrite=True)
        self.assertEqual(other.read_bytes(), original)
        self.assertEqual(sorted(path.name for path in self.out.iterdir()), ["carga.tif", "otra.tif"])
        self.assertEqual(self.counts(), before)


if __name__ == "__main__":
    unittest.main()
