# SPDX-License-Identifier: GPL-3.0-or-later
"""«Proponer el trazado», **sin proyecto** (spec 017, T27; HU-017-1 y HU-017-4; RF-017-28, RF-017-27 y RF-015-02; plan 017 §5.2.3 «des.road_propose», §5.4 A1 a A5, §5.7 P-8 y P-14; D-19): la operación
``des.road_propose`` da, con A1 a A5 y **sin** A6 a A9, la ruta con su rasante como **una capa de líneas con Z del proyecto, editable en QGIS** (``des_rpl_<nombre>_<vNN>``, una tabla de proyecto normal
sin el bloqueo de las salidas), que **no es una entidad** y no encadena. Con el proyecto (crear, que ninguna superficie cambie, la capa editable y su hash como entrada de una pista «eje 3D», recalcular y
reproducir) es de ``milestone_road_propose``; con QGIS real, ``tests/referencia/core/test_ref_road_layer_qgis.py``.

- **Lo que se pide y lo que anota** (:class:`ProposeSettingsTest`): los ajustes son la petición entera (la propuesta no tiene parámetros de entidad), solo «trazar», y la vuelven a pedir igual; los
  parámetros que lee son los del perfil.
- **La capa** (:class:`RouteLayerTableTest`): ``LINESTRING`` con la rasante en su Z, editable, con el nombre de la propuesta; la escritura entera y determinista, la lectura bit a bit y lo que lee de ella
  una pista «eje 3D» (T23-a).
- **El cálculo** (:class:`ProposeComputeTest`): A1 a A5 sobre la rampa del 4 % de CE-017-01, sin superficie ni sección ni borde, con las dos cifras del plan.
- **Las listas cerradas** (:class:`ProposeListsTest`): el tipo no es una entidad, se repite y se reproduce, y su familia es la única editable a mano.
"""

from __future__ import annotations

import sqlite3
import unittest
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.unit.design.test_road_prepare import RAMP, request

base = import_geoblender("core.gpkg.base")
cstyles = import_geoblender("core.constraints.styles")
entities = import_geoblender("design.entities")
preview = import_geoblender("design.preview")
provenance = import_geoblender("design.provenance")
road_layer = import_geoblender("design.road_layer")
road_model = import_geoblender("design.road_model")
road_store = import_geoblender("design.road_store")
store = import_geoblender("design.store")

TABLE = "des_rpl_trazado_a_v01"
DESIGN_PROFILE_KEYS = 13  # los trece valores del perfil que cambian el resultado (la clase normativa no)


def line(size: int = 5) -> np.ndarray:
    """Una línea de ``size`` estaciones con coordenadas absolutas (x, y) y una rasante que sube 0,4 m por estación."""
    return np.array([[725_000.0 + 10.0 * number, 4_400_000.0 + 0.25 * number, 104.0 + 0.4 * number] for number in range(size)], dtype=np.float64)


class ProposeSettingsTest(unittest.TestCase):
    """RF-017-28, RF-015-02, P-14: los ajustes y los parámetros de ``des.road_propose``."""

    def test_a_the_settings_are_the_whole_request_and_ask_for_the_same_again(self) -> None:
        """RF-017-28, RF-015-02: una propuesta no es una entidad y no tiene parámetros de entidad: sus ajustes llevan **toda** la petición (el nombre, la capa y su campo de nombres, el perfil, la partida,
        el origen y el destino, las cotas y los parámetros de la ruta) y la petición que salen de ellos es la misma, también con un destino por cota y con el eje de otra pista como origen."""
        cases = (
            request("Trazado A"),
            request("Trazado B", destination=None, dest_level_m=rd.PIT_FLOOR_M, dest_tol_m=0.5, dest_zone=f"{rd.ZONES_LAYER}:Zona del fondo", start_level_m=141.0),
            request("Trazado C", origin="RDW-001@100,5", destination="Destino del ramal", surface="entity:RDW-001", search_budget=1234),
        )
        for asked in cases:
            with self.subTest(asked.name):
                settings = provenance.propose_settings(asked)
                self.assertEqual(provenance.propose_request(settings), asked)
                self.assertNotIn("code", settings)

    def test_b_only_trace_is_proposed_and_the_other_modes_are_a_programme_error(self) -> None:
        """P-14, RF-017-28: la propuesta usa la ruta (A1 a A5): los modos «sobre un eje» y «eje 3D» no buscan ninguna, así que no se proponen (``ValueError``, un error del programa)."""
        for mode in ("on_axis", "axis_3d"):
            with self.subTest(mode), self.assertRaises(ValueError):
                provenance.propose_settings(request("Otra", mode=mode, layer=rd.AXES_LAYER))
        settings = provenance.propose_settings(request("Trazado A"))
        settings["mode"] = "axis_3d"
        with self.assertRaises(ValueError):
            provenance.propose_request(settings)
        with self.assertRaises(ValueError):
            provenance.propose_request({"name": "x"})

    def test_c_the_parameters_it_reads_are_the_ones_of_its_profile_and_no_entity_ones(self) -> None:
        """RF-017-28, RF-015-02: lo que la operación lee como parámetros son los valores del perfil de pista que cambian su resultado (sin su clase normativa) y **ninguno de una entidad**
        (``des.road.{e}.*``): empezar la operación no crea la fila de ningún parámetro de entidad (trampa de la T04 de la 015)."""
        keys = provenance.propose_params("pista_principal")
        self.assertEqual(len(keys), DESIGN_PROFILE_KEYS + 1)
        self.assertTrue(all(key.startswith("des.roadprofile.pista_principal.") for key in keys))
        self.assertNotIn("des.roadprofile.pista_principal.class", keys)
        self.assertEqual(keys, provenance.propose_params("pista_principal"))
        with self.assertRaises(ValueError):
            provenance.propose_params("Pista Principal")


class RouteLayerTableTest(unittest.TestCase):
    """RF-017-28, P-8, RF-017-18: la capa propuesta ``des_rpl_<nombre>_<vNN>``, sin proyecto."""

    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        base.create_base(self.conn, cfx.CRS)

    def test_a_the_table_is_named_by_proposal_and_version_and_has_the_line_with_its_name(self) -> None:
        """RF-017-28, P-8: la tabla se llama ``des_rpl_<nombre>_<vNN>`` (una por propuesta; ``rpl`` es una familia con nombre); lleva **solo** el nombre de la línea (el resto de lo que dice la propuesta,
        sus cifras, son de la operación: una cifra de la tabla quedaría mal en cuanto se edite la línea en QGIS) y su ``LINESTRING`` es **con Z**."""
        self.assertEqual(road_layer.route_layer_table("V01", "Trazado A"), TABLE)
        self.assertEqual(road_layer.route_layer_table("V12", "Ñandú 2"), "des_rpl_nandu_2_v12")
        self.assertEqual(road_layer.ROUTE_COLUMN_NAMES, ("name",))
        self.assertEqual(set(road_layer.ROUTE_COLUMN_TITLES), set(road_layer.ROUTE_COLUMN_NAMES))
        road_layer.write_route_layer(self.conn, TABLE, [road_layer.RouteLayerRow("Trazado A", line())], srs_id=cfx.CRS.epsg)
        found = self.conn.execute("SELECT geometry_type_name, z, m, srs_id FROM gpkg_geometry_columns WHERE table_name = ?", (TABLE,)).fetchone()
        self.assertEqual(found, ("LINESTRING", 1, 0, cfx.CRS.epsg))
        with self.assertRaises(ValueError):
            road_layer.route_layer_table("1", "Trazado A")

    def test_b_the_line_comes_back_bit_for_bit_with_the_grade_in_its_z_and_the_same_rows_give_the_same_bytes(self) -> None:
        """RF-017-28: la línea se lee **bit a bit** (x e y absolutas en float64 y la rasante en la Z) y escribir la misma capa otra vez deja las mismas filas y los mismos bytes: la operación es la única
        dueña de la tabla al crearla y la reescribe entera, con los ``fid`` desde 1."""
        row = road_layer.RouteLayerRow("Trazado A", line())
        road_layer.write_route_layer(self.conn, TABLE, [row], srs_id=cfx.CRS.epsg)
        first = self.conn.execute(f'SELECT fid, geom, name FROM "{TABLE}"').fetchall()
        road_layer.write_route_layer(self.conn, TABLE, [row])
        self.assertEqual(self.conn.execute(f'SELECT fid, geom, name FROM "{TABLE}"').fetchall(), first)
        (found,) = road_layer.read_route_layer(self.conn, TABLE)
        self.assertEqual((found.name, found.fid, found.layer), ("Trazado A", 1, TABLE))
        self.assertTrue(np.array_equal(found.points, line()))
        self.assertFalse(found.points.flags.writeable)
        self.assertEqual(road_layer.read_route_layer(self.conn, "des_rpl_no_existe_v01"), ())

    def test_c_it_is_not_a_version_layer_and_has_no_style_or_block_of_its_own(self) -> None:
        """RF-017-28, P-8, D-19: la capa propuesta **no** es una capa de versión de las que Geoblender estila y bloquea (``version_layer`` no la conoce: ni ``des_decl_``, ni ``des_enl_``, ni
        ``des_rax_``) y su familia es la única **editable a mano**: el dato que registra la operación lo dice."""
        self.assertIsNone(cstyles.version_layer(TABLE))
        spec = provenance.dataset_spec(provenance.ROUTE_LAYER_TABLE, "Trazado A", "V01")
        self.assertEqual((spec.name, spec.locator, spec.kind, spec.role, spec.qgis_editable), ("des_rpl_trazado_a", TABLE, "vector", "route_layer", True))
        others = [family.code for family in provenance.FAMILIES_BY_CODE.values() if family.qgis_editable]
        self.assertEqual(others, [provenance.ROUTE_LAYER_TABLE])

    def test_d_a_road_in_3d_axis_mode_reads_the_line_with_its_z_and_picks_it_by_name(self) -> None:
        """RF-017-02, RF-017-18, T23-a: la capa propuesta es de las que una pista «eje 3D» lee: ``read_lines_3d`` da la línea con su Z (la rasante) y se elige por su nombre o su ``fid``, sin
        que la pista corrija nada de la línea."""
        road_layer.write_route_layer(self.conn, TABLE, [road_layer.RouteLayerRow("Trazado A", line()), road_layer.RouteLayerRow("Trazado B", line(4) + 1.0)], srs_id=cfx.CRS.epsg)
        lines = road_store.read_lines_3d(self.conn, TABLE)
        asked = road_model.RoadRequest("Pista 3D", road_model.LayerFields("des_rpl_trazado_a", "name"), "axis_3d", "pista_principal", RAMP, feature="Trazado B")
        found, fid = road_store.line_3d(lines, asked, "RDW-001")
        self.assertEqual(fid, 2)
        self.assertTrue(np.array_equal(found, line(4) + 1.0))

    def test_e_the_rows_are_checked_and_a_bad_one_writes_nothing(self) -> None:
        """RF-017-28 (errores del programa): una fila sin nombre, con una línea que no son al menos dos estaciones (x, y, z) finitas o repetida se rechaza, y no escribe nada."""
        for name, points in (("", line()), ("Trazado A", line()[:1]), ("Trazado A", np.array([[1.0, 2.0], [3.0, 4.0]])), ("Trazado A", np.array([[1.0, 2.0, 3.0], [np.nan, 4.0, 5.0]]))):
            with self.subTest(name=name, shape=np.shape(points)), self.assertRaises(ValueError):
                road_layer.RouteLayerRow(name, points)
        row = road_layer.RouteLayerRow("Trazado A", line())
        with self.assertRaises(ValueError):
            road_layer.write_route_layer(self.conn, TABLE, [row, row], srs_id=cfx.CRS.epsg)
        with self.assertRaises(TypeError):
            road_layer.write_route_layer(self.conn, TABLE, [("Trazado A", line())], srs_id=cfx.CRS.epsg)  # type: ignore[list-item]
        self.assertIsNone(self.conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (TABLE,)).fetchone())


class ProposeComputeTest(unittest.TestCase):
    """RF-017-28, RF-017-09 a 18, P-14: A1 a A5 sin A6 a A9, sobre la rampa del 4 % (CE-017-01)."""

    @classmethod
    def setUpClass(cls) -> None:
        grid = rd.grid_of(rd.COARSE_STEP_M)
        cls.job = rd.route_job(grid, rd.ramp_terrain(grid), rd.absolute([rd.RAMP_ORIGIN], grid)[0].tolist(), rd.absolute([rd.RAMP_DESTINATION], grid)[0].tolist(), profile=rd.PROFILE)
        steps = road_store.propose_compute_steps(cls.job, surface=RAMP)
        cls.stages: list[Any] = []
        while True:
            try:
                cls.stages.append(next(steps))
            except StopIteration as stop:
                cls.outcome = stop.value
                break

    def test_a_the_route_and_the_grade_line_are_the_ones_of_the_ramp_and_nothing_is_engraved(self) -> None:
        """RF-017-28, CE-017-01, P-14: la ruta de la rampa del 4 % (200 m de largo y ≤ 2,8 % más larga que la recta: D-22) con su rasante, que sigue el terreno (4 % < pd): **sin** sección, huella ni
        borde (A6 a A9: la propuesta no toca ninguna superficie); las estaciones del eje tienen su terreno y su rasante."""
        outcome = self.outcome
        self.assertEqual((outcome.name, self.job.mode.value), ("Pista de prueba", "trace"))
        self.assertGreaterEqual(outcome.axis.length_m, rd.RAMP_LENGTH_M)
        self.assertLessEqual(outcome.axis.length_m, rd.RAMP_LENGTH_M * (1.0 + rd.DETOUR_BOUND_PCT / 100.0))
        self.assertEqual(outcome.levels.shape, outcome.terrain.shape)
        self.assertEqual(outcome.levels.shape[0], outcome.axis.points.shape[0])
        self.assertFalse(hasattr(outcome, "engraved") or hasattr(outcome, "surface") or hasattr(outcome, "footprint"))
        self.assertAlmostEqual(float(outcome.levels[-1] - outcome.levels[0]), rd.RAMP_DROP_M, delta=0.35)

    def test_b_the_two_figures_of_the_plan_and_no_other(self) -> None:
        """RF-017-28, plan 017 §5.2.3: las cifras de la propuesta son ``des.road_length_m`` y la pendiente máxima (``des.road_gradient_max_pct``: el plan la llama ``grade``, que el glosario de la 014 prohíbe
        en ``design/``), con el ámbito del **nombre de la operación** (no es una entidad) y la longitud igual a la del eje."""
        figures = {item.key: item for item in self.outcome.figures}
        self.assertEqual(tuple(figures), ("des.road_length_m", "des.road_gradient_max_pct"))
        self.assertAlmostEqual(figures["des.road_length_m"].value, self.outcome.axis.length_m, delta=1e-9)
        self.assertAlmostEqual(figures["des.road_gradient_max_pct"].value, rd.RAMP_SLOPE_PCT, delta=0.5)
        self.assertEqual({tuple(item.scope.items()) for item in figures.values()}, {((provenance.FIGURE_SCOPE_KEY, "pista_de_prueba"),)})

    def test_c_the_rows_of_the_layer_are_one_line_with_the_grade_in_its_z(self) -> None:
        """RF-017-28: la capa tiene **una** fila con el nombre de la propuesta y, por vértice, la x y la y absolutas del eje por estaciones y la rasante en la Z (bit a bit, float64)."""
        (row,) = road_store.propose_layer_rows(self.outcome)
        self.assertEqual(row.name, self.outcome.name)
        self.assertTrue(np.array_equal(row.points[:, :2], self.outcome.axis.points))
        self.assertTrue(np.array_equal(row.points[:, 2], self.outcome.levels))

    def test_d_cancelling_leaves_nothing_and_the_stages_come_in_order(self) -> None:
        """RF-015-29 (principio 7): el cálculo es por pasos sin proyecto (no escribe nada y cerrarlo, Esc, no deja nada) y dice sus etapas en orden: la ruta, el eje y la rasante, y las cifras."""
        steps = road_store.propose_compute_steps(self.job, surface=RAMP)
        next(steps)
        steps.close()
        done = [stage.done for stage in self.stages if hasattr(stage, "done")]
        self.assertEqual(done, sorted(done))

    def test_e_the_summary_of_a_proposal_gives_the_largest_deviation_of_the_axis(self) -> None:
        """RF-017-13, RF-017-28 (T44, S-3): el resumen de «Proponer el trazado…» da la **desviación máxima del eje** frente a la ruta (``axis_deviation_m``, la de ``Axis.deviation_m``), como el de la pista;
        no es una cifra nueva de las dos del plan (no se registra)."""
        summary = road_store.propose_summary(self.outcome, version="V01", profile=self.job.profile)
        self.assertEqual(summary.axis_deviation_m, self.outcome.axis.deviation_m)
        self.assertAlmostEqual(summary.axis_deviation_m, 2.8284271247, delta=1e-9, msg="la ruta de la rampa, simplificada con su tolerancia, se aparta 2,83 m de la ruta")
        self.assertEqual(tuple(item.key for item in self.outcome.figures), ("des.road_length_m", "des.road_gradient_max_pct"))


class ProposeAskTest(unittest.TestCase):
    """RF-017-26, RF-017-28 (T44, D-1): la vista previa de «Proponer el trazado…» es de **una propuesta** (``RoadAsk(propose=True)``): no es una entidad, así que lleva su petición y nunca el código de una pista
    de la versión."""

    def test_a_the_ask_of_a_proposal_is_a_request_and_by_default_a_road(self) -> None:
        """RF-017-26, RF-017-28: ``RoadAsk(request)`` sigue siendo la vista previa de una pista que se prepara (``propose`` falso); con ``propose=True`` es la de la propuesta, con o sin lo que hizo «Calcular»;
        una propuesta no es una pista **de la versión** (su código) y no se pide así: ``ValueError``."""
        asked = request("Trazado A")
        self.assertFalse(preview.RoadAsk(request=asked).propose)
        proposal = preview.RoadAsk(request=asked, propose=True)
        self.assertTrue(proposal.propose and proposal.request is asked)
        self.assertTrue(preview.RoadAsk(request=asked, prepared=object(), outcome=object(), propose=True).propose)
        with self.assertRaises(ValueError):
            preview.RoadAsk(code="RDW-001", propose=True)


class ProposeListsTest(unittest.TestCase):
    """RF-017-28, RF-015-02, P-8: el tipo de operación y su lugar en las listas cerradas."""

    def test_a_it_is_a_version_operation_that_repeats_and_reproduces_and_is_not_an_entity(self) -> None:
        """RF-017-28, RF-015-02, P-8: ``des.road_propose`` es de la versión, se repite y se reproduce, deja **solo** la capa propuesta, lleva las dos cifras y **no es una entidad** (no está entre las
        de ``ENTITY_OP_NAMES``: no encadena ni declara)."""
        found = provenance.OPERATION_TYPES_BY_NAME[provenance.ROAD_PROPOSE]
        self.assertEqual((found.outputs, found.scope, found.reproducible), ((provenance.ROUTE_LAYER_TABLE,), "version", True))
        self.assertEqual(tuple(item.key for item in found.figures), ("des.road_length_m", "des.road_gradient_max_pct"))
        self.assertIn(provenance.ROAD_PROPOSE, store.RECOMPUTED)
        self.assertNotIn(provenance.ROAD_PROPOSE, provenance.ENTITY_OP_NAMES)
        self.assertFalse(hasattr(store, "_ROAD_TASKS"), "la propuesta ya tiene su cálculo: no queda ninguna tarea por dar")

    def test_b_the_writer_prepares_the_layer_of_a_proposal(self) -> None:
        """RF-017-28: ``DesignWriter.route_layer_steps`` existe (la capa propuesta se escribe en la misma transacción de la operación) y rechaza al llamar lo que no es una fila de la capa."""
        self.assertTrue(callable(getattr(store.DesignWriter, "route_layer_steps", None)))
        self.assertTrue(callable(entities.registry))


if __name__ == "__main__":
    unittest.main()
