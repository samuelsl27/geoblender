# SPDX-License-Identifier: GPL-3.0-or-later
"""La capa de entidades con los tipos de la 016 y el GeoTIFF de la base, el terreno sin acopios y el espesor (spec 016, T34;
HU-016-1, HU-016-4; RF-016-24, RF-016-09, RF-015-27, RF-016-01; plan 016 §5.1 y §5.7 P-5; ADR-0031 §3), **sin proyecto**: lo que se
puede comprobar con datos hechos a mano y se ejecuta con el «verde». Con proyecto (la capa que refleja crear, repetir, descartar y
«apoyo retirado», soltar el apoyo de lo que se apoya en un acopio, el fallo de la regeneración y el GeoTIFF de verdad), en
``milestone_stockpile_layer_export.py`` (P-13: la rejilla de 2 m con proyecto).

- :class:`LayerFormatTest` (RF-015-27, RF-016-09): **una fila por acopio** (su código es la referencia ``STK-001#m07``), las cifras
  de los tipos nuevos (``volume_m3``, ``thickness_max_m``, ``cutoff_m3``) y la capa de una versión que escribió la 015 (sin ellas),
  que la primera escritura de la 016 completa sin perder nada.
- :class:`LayerRowsTest` (RF-015-27): de lo que sabe la capa de cada tipo de entidad salen sus filas con **sus** cifras, a mano.
- :class:`LayerInputsTest` (RF-015-27, RF-008-26): la capa consume la tabla de acopios de cada detección viva.
- :class:`ExportPureTest` (RF-016-24, RF-016-09, RF-016-01): el terreno sin acopios se compone entero con la superficie de la que parte
  la detección, el espesor se resta de dos superficies y nunca es negativo, y los metadatos dicen qué es cada rejilla.
"""

from __future__ import annotations

import sqlite3
import unittest
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender

base = import_geoblender("core.gpkg.base")
entities = import_geoblender("design.entities")
entity_layer = import_geoblender("design.entity_layer")
entity_store = import_geoblender("design.entity_store")
export = import_geoblender("design.export")
provenance = import_geoblender("design.provenance")
operations = import_geoblender("core.provenance.operations")

TABLE = "des_enl_v01"
GRID = qfx.grid_of(qfx.COARSE_STEP_M)
CELL_M2 = GRID.dx * GRID.dy
KIND, STATE = entities.EntityKind, entities.EntityState


def square(west: float, south: float, side: float) -> tuple[tuple[np.ndarray, ...], ...]:
    """El contorno (cerrado) de un cuadrado: una parte con su anillo exterior."""
    ring = np.array([[west, south], [west + side, south], [west + side, south + side], [west, south + side], [west, south]],
                    dtype=np.float64)
    return ((ring,),)


def row(code: str, name: str, kind: str, **changes: Any) -> Any:
    """Una fila de la capa de prueba (un cuadrado de 10 m de lado)."""
    values: dict[str, Any] = {"code": code, "name": name, "kind": kind, "state": "current", "start": None, "supports": "",
                              "chain": "", "parts": square(725_000.0, 4_400_000.0, 10.0)}
    return entity_layer.EntityLayerRow(**{**values, **changes})


class LayerFormatTest(unittest.TestCase):
    """RF-015-27, RF-016-09 (T34): la fila de un acopio y las cifras nuevas, sin proyecto."""

    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        base.create_base(self.conn, cfx.CRS)

    def test_a_a_stockpile_is_a_row_of_its_own_whose_code_is_the_reference_of_its_mark(self) -> None:
        """RF-015-27, RF-016-14 (P-1): una fila de la capa acepta como código la referencia de un acopio (``STK-001#m07``, la que
        usa ``des.supported_m3``) además del código de una entidad; lo que no es ni lo uno ni lo otro se rechaza (un error del
        programa); las cifras de los tipos nuevos van después de las cinco de la plataforma y la tabla las titula."""
        self.assertEqual(entity_layer.FIGURE_COLUMNS[:5], ("area_m2", "cut_m3", "fill_m3", "edge_cut_m3", "edge_fill_m3"))
        self.assertEqual(entity_layer.FIGURE_COLUMNS[5:], ("volume_m3", "thickness_max_m", "cutoff_m3"))
        self.assertEqual(entity_layer.COLUMN_NAMES, ("code", "name", "kind", "state", "start", "supports", "chain",
                                                     *entity_layer.FIGURE_COLUMNS))
        self.assertEqual(set(entity_layer.COLUMN_TITLES), set(entity_layer.COLUMN_NAMES))
        found = row("STK-001#m07", "Acopio 7", "stockpile", volume_m3=193_008.0, thickness_max_m=12.0)
        self.assertEqual((found.code, found.kind, found.volume_m3, found.thickness_max_m, found.cutoff_m3),
                         ("STK-001#m07", KIND.STOCKPILE, 193_008.0, 12.0, None))
        for bad in ("m07", "STK-001#", "stk-001#m07", "STK#m07", "#m07", ""):
            with self.subTest(code=bad), self.assertRaises(ValueError):
                row(bad, "Acopio", "stockpile")

    def test_b_the_rows_of_a_detection_are_written_by_code_and_read_back_with_their_figures(self) -> None:
        """RF-015-27, RF-016-09: tres acopios de una detección y una plataforma se escriben ordenados por código (los acopios de una
        detección, juntos), con ``fid`` desde 1, y se leen con cada cifra tal como se escribió (las que no tienen, sin valor);
        escribir las mismas filas en otro orden da los mismos bytes."""
        rows = (row("STK-001#m02", "Acopio 2", "stockpile", area_m2=40.0, volume_m3=120.0, thickness_max_m=3.5,
                    parts=square(725_020.0, 4_400_000.0, 10.0)),
                row("PLT-001", "Carga", "platform", area_m2=100.0, cut_m3=12.5, fill_m3=1.0, edge_cut_m3=3.0, edge_fill_m3=1.5),
                row("STK-001#m01", "Acopio 1", "stockpile", area_m2=36.0, volume_m3=90.0, thickness_max_m=2.0, state="discarded",
                    parts=square(725_040.0, 4_400_000.0, 10.0)))
        fids = entity_layer.write_entity_layer(self.conn, TABLE, rows, srs_id=25830)
        self.assertEqual(fids, (1, 2, 3))
        found = entity_layer.read_entity_layer(self.conn, TABLE)
        self.assertEqual([item.code for item in found], ["PLT-001", "STK-001#m01", "STK-001#m02"])
        self.assertEqual([(item.kind, item.state) for item in found],
                         [(KIND.PLATFORM, STATE.CURRENT), (KIND.STOCKPILE, STATE.DISCARDED), (KIND.STOCKPILE, STATE.CURRENT)])
        figures = [{column: getattr(item, column) for column in entity_layer.FIGURE_COLUMNS} for item in found]
        self.assertEqual(figures[0], {"area_m2": 100.0, "cut_m3": 12.5, "fill_m3": 1.0, "edge_cut_m3": 3.0, "edge_fill_m3": 1.5,
                                      "volume_m3": None, "thickness_max_m": None, "cutoff_m3": None})
        self.assertEqual(figures[2], {"area_m2": 40.0, "cut_m3": None, "fill_m3": None, "edge_cut_m3": None, "edge_fill_m3": None,
                                      "volume_m3": 120.0, "thickness_max_m": 3.5, "cutoff_m3": None})
        first = self.conn.execute(f'SELECT * FROM "{TABLE}" ORDER BY fid').fetchall()
        entity_layer.write_entity_layer(self.conn, TABLE, tuple(reversed(rows)))
        self.assertEqual(self.conn.execute(f'SELECT * FROM "{TABLE}" ORDER BY fid').fetchall(), first)

    def test_c_a_layer_written_by_the_015_is_completed_with_the_new_columns_and_read_without_them(self) -> None:
        """RF-015-27 (T34): la capa de una versión que escribió la 015 no tiene las tres cifras nuevas; **se lee** sin ellas (sin
        valor) y la **primera escritura** de la 016 las añade (con su título) y deja las filas que escribe, sin perder las columnas
        que había ni el registro de la capa en el GeoPackage."""
        old = tuple(column for column in entity_layer.COLUMNS if column.name not in entity_layer.FIGURE_COLUMNS[5:])
        self.assertEqual(len(old), 12)
        base.create_feature_table(self.conn, TABLE, "MULTIPOLYGON", 25830, False, old, "Entidades de diseño V01", "de la 015")
        base.set_column_titles(self.conn, TABLE, {name: entity_layer.COLUMN_TITLES[name] for name in
                                                  (column.name for column in old)})
        blob = entity_layer.encode_geometry("MULTIPOLYGON", [list(part) for part in square(725_000.0, 4_400_000.0, 10.0)],
                                            25830, False)
        self.conn.execute(f'INSERT INTO "{TABLE}" (geom, code, name, kind, state, start, supports, chain, area_m2) '
                          "VALUES (?, 'PLT-001', 'Carga', 'platform', 'current', NULL, '', '', 100.0)", (blob,))
        (before,) = entity_layer.read_entity_layer(self.conn, TABLE)
        self.assertEqual((before.code, before.area_m2, before.volume_m3, before.cutoff_m3), ("PLT-001", 100.0, None, None))
        entity_layer.write_entity_layer(self.conn, TABLE, [row("STK-001#m01", "Acopio 1", "stockpile", volume_m3=90.0)])
        columns = [str(item[1]) for item in self.conn.execute(f'PRAGMA table_info("{TABLE}")')]
        self.assertEqual(columns, ["fid", "geom", *entity_layer.COLUMN_NAMES])
        titles = dict(self.conn.execute("SELECT column_name, title FROM gpkg_data_columns WHERE table_name = ?", (TABLE,)).fetchall())
        self.assertEqual(titles, dict(entity_layer.COLUMN_TITLES))
        (after,) = entity_layer.read_entity_layer(self.conn, TABLE)
        self.assertEqual((after.code, after.volume_m3), ("STK-001#m01", 90.0))
        self.assertEqual(self.conn.execute("SELECT count(*) FROM gpkg_geometry_columns WHERE table_name = ?", (TABLE,)).fetchone(), (1,))


def source(code: str, name: str, kind: str, figures: dict[str, float], **changes: Any) -> Any:
    """Lo que la capa sabe de una entidad (un cuadrado de 5 × 5 celdas en la esquina de la rejilla de 2 m)."""
    values: dict[str, Any] = {"code": code, "name": name, "calc_name": name, "kind": KIND(kind), "state": STATE.CURRENT,
                              "start": None, "runs": tuple((r, 10, 15) for r in range(10, 15)), "supports": "", "chain": "",
                              "figures": figures}
    return entity_store.LayerSource(**{**values, **changes})


class LayerRowsTest(unittest.TestCase):
    """RF-015-27, RF-016-09 (T34): de lo que sabe la capa de cada tipo salen sus filas, con **sus** cifras."""

    @staticmethod
    def rows(*sources: Any) -> dict[str, Any]:
        work = entity_store.entity_layer_rows_steps(sources, GRID)
        while True:
            try:
                next(work)
            except StopIteration as stop:
                return {item.code: item for item in stop.value}

    def test_a_each_kind_fills_its_own_figure_columns_and_leaves_the_others_empty(self) -> None:
        """RF-015-27, RF-016-09: la plataforma, las cinco de la 015; el acopio, su área, su volumen y su espesor máximo; la retirada, lo
        retirado y la mayor pared; el contrafuerte, su área, su volumen, su altura máxima y el pie cortado; el cuerpo, su volumen y su
        espesor máximo; ninguna llena una columna que no es suya, aunque la operación tenga la cifra."""
        found = self.rows(
            source("PLT-001", "Carga", "platform", {"des.plat_area_m2": 100.0, "des.plat_cut_m3": 12.5, "des.plat_fill_m3": 1.0,
                                                    "des.edge_cut_m3": 3.0, "des.edge_fill_m3": 1.5, "des.rmv_removed_m3": 999.0}),
            source("RMV-001", "Retirada", "removal", {"des.rmv_removed_m3": 400.0, "des.rmv_wall_max_m": 2.5,
                                                     "des.rmv_kept_m3": 7.0, "des.rmv_resting_m3": 8.0}),
            source("BTR-001", "Contrafuerte", "buttress", {"des.btr_area_m2": 80.0, "des.btr_volume_m3": 300.0,
                                                          "des.btr_height_max_m": 6.0, "des.btr_cutoff_m3": 11.0,
                                                          "des.btr_cutoff_m2": 9.0}),
            source("BDY-001", "Cuerpo", "body", {"des.bdy_volume_m3": 50.0, "des.bdy_thickness_max_m": 1.2, "des.bdy_far_m3": 3.0}),
            source("STK-001#m07", "Acopio 7", "stockpile", {"des.stk_area_m2": 37_808.0, "des.stk_volume_m3": 193_008.0,
                                                           "des.stk_thickness_max_m": 12.0, "des.stk_plane_tilt_deg": 3.0}))
        figures = {code: {column: getattr(item, column) for column in entity_layer.FIGURE_COLUMNS if getattr(item, column) is not None}
                   for code, item in found.items()}
        self.assertEqual(figures["PLT-001"], {"area_m2": 100.0, "cut_m3": 12.5, "fill_m3": 1.0, "edge_cut_m3": 3.0,
                                              "edge_fill_m3": 1.5})
        self.assertEqual(figures["RMV-001"], {"volume_m3": 400.0, "thickness_max_m": 2.5})
        self.assertEqual(figures["BTR-001"], {"area_m2": 80.0, "volume_m3": 300.0, "thickness_max_m": 6.0, "cutoff_m3": 11.0})
        self.assertEqual(figures["BDY-001"], {"volume_m3": 50.0, "thickness_max_m": 1.2})
        self.assertEqual(figures["STK-001#m07"], {"area_m2": 37_808.0, "volume_m3": 193_008.0, "thickness_max_m": 12.0})
        self.assertEqual(list(found), ["BDY-001", "BTR-001", "PLT-001", "RMV-001", "STK-001#m07"], "por código de entidad")

    def test_b_the_rows_of_one_detection_come_together_in_the_order_of_their_keys_and_each_has_its_own_outline(self) -> None:
        """RF-015-27, RF-016-09: dos detecciones con dos acopios cada una salen **una fila por acopio**, juntas y por clave, cada una
        con **su** contorno (el de las celdas de su huella: el cuadrado de 5 × 5 celdas de 2 m = 100 m²), el estado de su detección,
        sin partida, cadena ni apoyo."""
        found = self.rows(
            source("STK-002#m1", "Otro 1", "stockpile", {}, state=STATE.STALE),
            source("STK-001#m2", "Acopio 2", "stockpile", {}, runs=tuple((r, 30, 35) for r in range(10, 15))),
            source("STK-001#m1", "Acopio 1", "stockpile", {}),
            source("STK-002#m2", "Otro 2", "stockpile", {}, state=STATE.STALE))
        self.assertEqual(list(found), ["STK-001#m1", "STK-001#m2", "STK-002#m1", "STK-002#m2"])
        self.assertEqual([item.state for item in found.values()], [STATE.CURRENT] * 2 + [STATE.STALE] * 2)
        for item in found.values():
            (part,) = item.parts
            (ring,) = part
            area = 0.5 * abs(float(np.dot(ring[:-1, 0], ring[1:, 1]) - np.dot(ring[1:, 0], ring[:-1, 1])))
            self.assertAlmostEqual(area, 25 * CELL_M2, places=9)
            self.assertEqual((item.start, item.chain, item.supports), (None, "", ""))
        west = [float(found[code].parts[0][0][:, 0].min()) for code in ("STK-001#m1", "STK-001#m2")]
        self.assertAlmostEqual(west[1] - west[0], 20 * GRID.dx, places=9, msg="su huella, no la de otro acopio")


class LayerInputsTest(unittest.TestCase):
    """RF-015-27, RF-008-26 (T34): lo que consume la capa."""

    def test_a_the_layer_consumes_the_table_of_stockpiles_of_each_live_detection(self) -> None:
        """RF-015-27, RF-008-26: de cada entidad viva, su huella y su informe y, de cada detección de acopios viva, su tabla de
        acopios (papel ``stockpiles``), **una vez** por detección aunque tenga varios acopios; con ella, repetir la detección
        deja la capa obsoleta con su causa. Sin detecciones, lo de siempre."""
        self.assertEqual(provenance.entity_layer_inputs(["Carga"]), (
            operations.Use("des_epr_carga", "entity"), operations.Use("des_prp_carga", "entity_report")))
        found = provenance.entity_layer_inputs(["Carga"], ["Acopios", "Acopios"])
        self.assertEqual(found, (operations.Use("des_epr_carga", "entity"), operations.Use("des_prp_carga", "entity_report"),
                                 operations.Use("des_stk_acopios", "stockpiles")))
        self.assertEqual(provenance.entity_layer_inputs([], ["Acopios"]), (operations.Use("des_stk_acopios", "stockpiles"),))

    def test_b_a_version_with_only_a_detection_or_a_buttress_has_entity_operations(self) -> None:
        """RF-015-27: la marca de la capa mira las operaciones de **los cinco tipos** (hasta la 016 solo la plataforma: una versión
        con solo un contrafuerte o una detección no tenía capa que poner al día)."""
        self.assertEqual(provenance.ENTITY_OP_NAMES, ("des.platform", "des.stockpile_detect", "des.stockpile_removal",
                                                     "des.buttress", "des.body"))
        self.assertTrue(set(provenance.ENTITY_OP_NAMES) >= {type_.op_type for type_ in provenance.ENTITY_OPERATION_TYPES
                                                            if type_.op_type != provenance.DECLARE_CONSTRAINTS
                                                            and type_.op_type != provenance.ENTITY_LAYER})
        for kind in KIND:
            self.assertIn(entities.entity_type(kind).op_type, provenance.ENTITY_OP_NAMES)


class ExportPureTest(unittest.TestCase):
    """RF-016-24, RF-016-09, RF-016-01 (T34): lo que se compone y se resta al exportar, con arrays hechos a mano."""

    def test_a_the_ground_without_stockpiles_is_the_stored_one_in_the_footprints_and_the_start_surface_outside(self) -> None:
        """RF-016-09, RF-016-24, P-5: ``compose_ground`` da el terreno de las huellas donde lo hay y la superficie de la que parte la
        detección en el resto, **celda a celda, hecho a mano**; donde ninguno tiene dato, sin dato; el resultado es nuevo (no
        modifica ninguna de las dos); formas distintas se rechazan."""
        nan = np.nan
        ground = np.array([[nan, 100.5, nan], [nan, 101.0, 99.0]])
        surface = np.array([[110.0, 102.0, nan], [111.0, 103.0, 104.0]])
        found = export.compose_ground(ground, surface)
        np.testing.assert_array_equal(found, np.array([[110.0, 100.5, nan], [111.0, 101.0, 99.0]]))
        np.testing.assert_array_equal(ground, np.array([[nan, 100.5, nan], [nan, 101.0, 99.0]]))
        with self.assertRaises(ValueError):
            export.compose_ground(ground, surface[:1])

    def test_b_the_thickness_is_the_difference_of_two_surfaces_never_negative_and_without_data_where_one_is_missing(self) -> None:
        """RF-016-01, RF-016-24 (error 26): ``thickness_between(arriba, abajo)`` es ``arriba − abajo`` donde las dos tienen dato, **0
        donde la de arriba queda por debajo** (nunca un espesor negativo) y sin dato donde falta alguna, a mano."""
        nan = np.nan
        top = np.array([[105.0, 100.0, nan], [103.5, 99.0, 101.0]])
        bottom = np.array([[100.0, 101.0, 100.0], [103.0, nan, 100.25]])
        found = export.thickness_between(top, bottom)
        np.testing.assert_array_equal(found, np.array([[5.0, 0.0, nan], [0.5, nan, 0.75]]))
        self.assertFalse(np.any(found[np.isfinite(found)] < 0.0))
        with self.assertRaises(ValueError):
            export.thickness_between(top, bottom[:, :2])

    def test_c_the_grids_of_the_016_are_exportable_and_the_metadata_says_what_each_one_is(self) -> None:
        """RF-016-24: la base y el espesor de los acopios de un material, el terreno sin acopios y el espesor de un cuerpo son rejillas
        exportables (de cotas, en m); el terreno dice que va **compuesto**, el espesor que se resta, qué es, y el de una detección
        del proyecto, ``proyecto`` como versión; una parte que no existe se rechaza."""
        self.assertEqual(export.SUPPORTED_GRIDS, ("stb", "stt", "stg", "bdt"))
        self.assertTrue(set(export.SUPPORTED_GRIDS) <= set(export.GRIDS))
        base_items = export.metadata_items("stb", "Acopios mineral", "V01")
        self.assertEqual(base_items, {"UNIDAD": "m", "TIPO": "Base de los acopios de un material", "DATO": "des_stb_acopios_mineral",
                                      "VERSION": "V01"})
        self.assertEqual(export.metadata_items("stt", "Acopios mineral", "V01")["TIPO"], "Espesor de los acopios de un material")
        ground = export.metadata_items("stg", "Acopios", export.PROJECT_VERSION)
        self.assertEqual((ground["DATO"], ground["VERSION"]), ("des_stg_acopios", "proyecto"))
        self.assertIn("compuesto", ground["TIPO"])
        self.assertEqual(export.metadata_items("bdt", "Cuerpo", "V02")["TIPO"], "Espesor de un cuerpo apoyado")
        thickness = export.metadata_items("psf", "Contrafuerte", "V01", export.PART_THICKNESS)
        self.assertEqual((thickness["UNIDAD"], thickness["DATO"]), ("m", "des_psf_contrafuerte"))
        self.assertIn("Espesor", thickness["TIPO"])
        with self.assertRaises(ValueError):
            export.metadata_items("psf", "Contrafuerte", "V01", "volumen")
        with self.assertRaises(ValueError):
            export.metadata_items("stk", "Acopios", "V01")  # la tabla de acopios no es una rejilla


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
