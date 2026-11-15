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

import unittest
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender
from tests.unit.design import test_after_entity_change as chain_test
from tests.unit.design import test_declare_operation as decl
from tests.unit.design import test_entity_supports as sup
from tests.unit.design import test_platform_operation as ops
from tests.unit.design import test_platform_prepare as prep

access = import_geoblender("gis.masks.access")
base = import_geoblender("core.gpkg.base")
core_params = import_geoblender("core.params")
cstyles = import_geoblender("core.constraints.styles")
design_params = import_geoblender("design.params")
design_store = import_geoblender("design.store")
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


# ---------------------------------------------------------------------------------------------
# Si falla
# ---------------------------------------------------------------------------------------------


# ---------------------------------------------------------------------------------------------
# La exportación a GeoTIFF
# ---------------------------------------------------------------------------------------------


# ---------------------------------------------------------------------------------------------
# El estado de la capa nunca dice «al día» cuando no lo está (T43; hallazgo E-4 / C-11)
# ---------------------------------------------------------------------------------------------

WORKSHOP = prep.WORKSHOP
GUARD = design_params.entity_key("PLT-001", "guard_m")
BY = "Samuel (IMGA)"
WHY = "Prueba de la T43"


def returned(work: Any) -> Any:
    """Lo que devuelve el generador ``work`` al acabar (``StopIteration.value``), tras dar todos sus pasos."""
    while True:
        try:
            next(work)
        except StopIteration as stop:
            return stop.value


if __name__ == "__main__":
    unittest.main()
