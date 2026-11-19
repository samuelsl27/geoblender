# SPDX-License-Identifier: GPL-3.0-or-later
"""Hito H2 de los acopios en Blender (spec 016, T22; HU-016-2; CE-016-03 y CE-016-04 con las órdenes reales, E2 y E3 sin pantalla; RF-016-11,
RF-016-13 a RF-016-16, RF-015-15, RF-015-17; plan 016 §5.4 A6 a A9, §5.7 P-9, §7.1 y §7.5; hallazgo de la T20 (b)): lo que
``tests/unit/design/milestone_stockpile_ce.py`` hace con las funciones del dominio, **de punta a punta con la orden real**
(``geoblender.des_remove_stockpile``, ``geoblender.des_create_platform``, **«Recalcular lo obsoleto»**, ``geoblender.core_recompute_stale``, el
modal con su plan) en ``blender -b`` y sin pantalla.

El proyecto de ``test_removal_ops`` (ventana de 60 × 60 m con celdas de 2 m, V01 y V02; un levantamiento con dos montones de 4 m de altura, a 16 y 44
m, y una capa de marcas) con **una detección de la versión**: con la del proyecto (``test_removal_ops``) la retirada no deja «apoyo retirado» a lo
que se apoyaba (hallazgo de la T20 (b)), así que la detección se hace sobre la superficie de V01 que deja ``PLT-001`` «Terreno de V01» (una
plataforma «en corte» en una esquina, por encima del terreno: no corta nada) y de ella parte ``PLT-002`` «Sobre acopio», el relleno de la 015 «en
corte y relleno» a 108 m, que cubre el Acopio 2. Las pruebas, **en el orden de sus letras** sobre el mismo estado; las cuentas, a mano (los ficheros
leídos con bucles de numpy, no el código que se prueba).

**CE-016-04 con el contrafuerte real** (T27 (b); :class:`StockpileButtressCETest`): la misma cadena con ``geoblender.des_add_buttress`` (la zona
de coronación, la marca del Acopio 2; el perfil ``EXPL_10_60_6`` escrito en el proyecto; coronación a 115 m; **protege por defecto**) en lugar del
relleno de la 015: se apoya en el acopio, **una sola lista** antes de retirarlo, «apoyo retirado» tras crear la retirada y «Recalcular lo
obsoleto» sin recalcularlo; con el contrafuerte **después** de la retirada, solo obsoleto.

**E3 con la orden real** (T41; :class:`StockpileCETest` ``test_f`` y :class:`StockpileAsPlatformCETest`): el Acopio 1 retirado «como plataforma»
con ``des_remove_stockpile`` (``as_platform``: el borde y el alcance del diálogo) deja la huella entera en el plano de su base y el eje de borde a
borde, y el Acopio 2, desde la superficie del relleno, pide confirmar lo apoyado y deja a «Sobre acopio» con el apoyo retirado; lo que sigue a la
orden (la capa de entidades) ya está hecho sin otra orden.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import json
import math
import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.blender import test_platform_ops as platform_ops
from tests.blender import test_removal_ops as rem_ops
from tests.support import blender_ext

TERRAIN = ("Terreno", ((52.0, 52.0), (58.0, 52.0)), 4.0, 130.0, 0.0)
"""«Terreno de V01»: una plataforma en un rincón (el eje y el ancho de su capa), a 130 m: por encima del terreno de allí (100 a 102 m)."""
AFTER = ("Después", ((38.0, 30.0), (50.0, 30.0)), 8.0, 110.0, 0.0)
"""El relleno que se hace **después** de la retirada: sobre el mismo sitio que ``PLT-002`` y 2 m más alto."""
TERRAIN_NAME, OVER_NAME, REMOVAL_NAME, AFTER_NAME = "Terreno de V01", rem_ops.OVER[0], "Retirada del acopio 2", "Después de la retirada"
ANGLE = "35"
PROFILE = "EXPL_10_60_6"
BUTTRESS_NAME, AFTER_NAME = "Contrafuerte del Acopio 2", "Contrafuerte después de la retirada"
MAX_TICKS = 400
CELL_M2 = platform_ops.CELL_M2
THICKNESS_M = 0.02
"""El espesor mínimo de la 012 (``res.verify.min_thickness_m``)."""
PLANE_PCT = 100.0 * math.hypot(0.01, 0.03)
"""La pendiente del plano del levantamiento (``100 + 0,03·y + 0,01·x``), en %."""
TIMER = SimpleNamespace(type="TIMER", value="NOTHING")


def _module(name: str) -> Any:
    return platform_ops._module(name)


def _close(found: float, expected: float, relative: float = 1e-9) -> bool:
    return abs(found - expected) <= relative * abs(expected)


class StockpileCETest(rem_ops.RemoveStockpileTest):
    """La extensión habilitada una vez y el proyecto de los acopios con la detección de la versión."""

    @classmethod
    def setUpClass(cls) -> None:
        with mock.patch.object(platform_ops, "FEATURES", (*platform_ops.FEATURES, TERRAIN, rem_ops.OVER, AFTER)):
            super(rem_ops.RemoveStockpileTest, cls).setUpClass()
        cls.survey_name = cls.write_grid("Levantamiento", rem_ops.survey())
        cls.write_marks()
        cls.platform(name=TERRAIN_NAME, feature=TERRAIN[0], start=cls.survey_name, mode="CUT", reach="4")
        cls.detect()
        cls.platform(name=OVER_NAME, feature=OVER_NAME, start="entity:PLT-001", mode="CUT_FILL")
        cls.refresh()

    @classmethod
    def platform(cls, **values: Any) -> None:
        """«Calcula» y «crea» una plataforma (``des_create_platform``) en la versión activa."""
        cls.refresh()
        form = {"layer": platform_ops.LAYER, "edge_angle": "35", "reach": "10", "in_steps": False, **values}
        assert bpy.ops.geoblender.des_create_platform("EXEC_DEFAULT", **form) == {"FINISHED"}
        assert bpy.ops.geoblender.des_create_platform("EXEC_DEFAULT", confirm=True, in_steps=False) == {"FINISHED"}
        cls.refresh()

    @classmethod
    def detect(cls) -> None:
        """«Calcula» y «crea» la detección ``Acopios`` (las dos marcas, sin candidatos, con 3 m de margen) sobre la superficie de **V01** que deja
        ``PLT-001``: la detección es de la versión (D-15)."""
        steps, model = _module("design.steps"), _module("design.model")
        surface = cls.dprov.dataset_name("psf", TERRAIN_NAME)
        request = model.StockpileRequest("Acopios", model.StockpileFields(rem_ops.MARKS_LAYER, name_field="nombre"), surface,
                                         candidates=False, margin_m=3.0)
        found = None
        for step in steps.stockpile_run(cls.project, request, version=cls.v01.uid):
            found = step.result or found
        assert found is not None
        found.create()

    # --- Ayudas -------------------------------------------------------------------------------

    def form(self, **values: Any) -> dict[str, Any]:  # type: ignore[override]
        """Lo pedido en el diálogo de la retirada: el Acopio 2 desde la superficie de «Sobre acopio», con la transición a 35°."""
        return {"name": REMOVAL_NAME, "stockpile": "STK-001#Acopio 2", "start": "entity:PLT-002", "transition_angle": ANGLE,
                "in_steps": False, **values}

    def surface(self, name: str) -> np.ndarray:
        return np.asarray(self.surfaces.read_surface(self.project, name, version_uid=self.v01.uid).values)

    def footprint(self, key: str) -> tuple[np.ndarray, np.ndarray]:
        """Las celdas de la huella del acopio ``key`` de la detección de V01 (de los tramos de su fila de ``des_stk_``)."""
        found = _module("design.stockpile_store").read_detection_table(
            self.project, "stk", "Acopios", version_uid=self.v01.uid)
        (row,) = [item for item in found if item["key"] == key]
        return self.entities.runs_cells(tuple(tuple(run) for run in json.loads(row["footprint"])))

    def base_name(self) -> str:
        ((name,),) = self.rows("SELECT name FROM gb_dataset WHERE name LIKE 'des!_stb!_%' ESCAPE '!' AND status = 'current'")
        return str(name)

    def tick(self) -> bool:
        """Un paso de cada cola de pasos del recálculo (``des``, las máscaras de ``gis`` y la verificación de ``res``: sus temporizadores no corren en
        ``blender -b``, se avanzan a mano); si queda algo pendiente."""
        gis_ops, res_ops = _module("bl.ops.gis"), _module("bl.ops.res")
        pending = bool(self.des_ops.pending_runs() or gis_ops.pending_mask_runs() or res_ops.pending_runs())
        self.des_ops.des_tick()
        gis_ops.masks_tick()
        res_ops.res_tick()
        return pending

    def recompute(self) -> Any:
        """Lanza «Recalcular lo obsoleto» y lo lleva hasta el final (el modal, con la cola de ``des`` avanzada a mano), sin pedir confirmación; el
        operador, con su ``result`` y lo que dijo (``report_log``)."""
        with mock.patch.object(self.des_ops, "_ask_confirmation") as ask, \
                mock.patch.object(_module("bl.ops.incorporation"), "status_text"):
            self.assertEqual(bpy.ops.geoblender.core_recompute_stale("EXEC_DEFAULT"), {"RUNNING_MODAL"})
            found = [op for op in bpy.context.window.modal_operators
                     if isinstance(op, self.session.GEOBLENDER_OT_core_recompute_stale) and getattr(op, "_steps", None) is not None]
            self.assertEqual(len(found), 1)
            operator = found[0]
            self.addCleanup(lambda: operator._steps is None or operator.cancel(bpy.context))
            for _ in range(MAX_TICKS):
                state = operator.modal(bpy.context, TIMER)
                self.tick()
                if state != {"RUNNING_MODAL"}:
                    ask.assert_not_called()
                    return operator
        self.fail("el recálculo no termina")

    def states(self) -> dict[str, str]:
        return {entry.record.code: str(entry.record.state) for entry in self.entities.registry(self.project, self.v01.uid)}

    def change(self, key: str, value: object) -> None:
        with self.project.write_transaction() as conn:
            _module("core.params").ParameterStore(self.project).change(
                conn, key, value=value, version=self.v01.uid, reason="Prueba del hito H2")

    def hand_resting(self) -> float:
        """A mano, **de los ficheros**: lo que el relleno sube sobre el Acopio 2 —``Σ (relleno − máx(partida, acopio))·4 m²`` en las celdas de su huella que
        pasan del espesor mínimo—, con la superficie de partida (la de ``PLT-001``) y la del acopio con que se detectó."""
        rows, cols = self.footprint("Acopio 2")
        top = self.surface(self.dprov.dataset_name("psf", OVER_NAME))[rows, cols]
        start = self.surface(self.dprov.dataset_name("psf", TERRAIN_NAME))[rows, cols]
        ground = self.surface(self.dprov.dataset_name("stp", "Acopios"))[rows, cols]
        thick = top - np.maximum(start, ground)
        return math.fsum(float(value) for value in thick[thick > THICKNESS_M]) * CELL_M2

    # --- CE-016-04: lo apoyado, una sola lista antes de calcular ---------------------------------

    def test_a_what_rests_on_the_stockpile_is_one_list_before_calculating_and_is_not_removed_without_confirming_it(self) -> None:
        """CE-016-04, RF-016-14, RF-015-17 (error 59; E2, las órdenes reales): con la detección **de la versión** y el relleno de la 015 sobre el
        Acopio 2, retirarlo da **una sola lista** antes de calcular —«Sobre acopio», con su tipo y su volumen **a mano** (de los ficheros) a ≤ 10⁻⁹
        relativo— en el diálogo y en el resumen, en ámbar; calcular **no escribe nada**; «Crear» sin la confirmación expresa se rechaza, no
        escribe nada y deja el cálculo abierto."""
        self.refresh()
        self.assertEqual(self.entities.registry(self.project, self.v01.uid).get("STK-001").record.state.value, "current")
        self.assertEqual(self.states(), {"STK-001": "current", "PLT-001": "current", "PLT-002": "current"})
        before = self.state()
        given, context, _dialog, _said = self.fake_dialog(name=REMOVAL_NAME, stockpile="STK-001#Acopio 2", start="entity:PLT-002",
                                                          properties=SimpleNamespace(is_property_set=lambda name: name in ("stockpile", "start")))
        self.cls.invoke(given, context, None)
        self.des_ops._refresh_resting(given, None)
        lines = self.panels.resting_lines()
        self.assertEqual(len(lines), 2)
        self.assertRegex(lines[0][0], rf"^{OVER_NAME} \(Plataforma\): \d+ m³ apoyados$")
        self.assertTrue(lines[0][1], "lo apoyado, en ámbar")
        held = self.calculate()
        self.assertTrue(held.needs_resting_confirmation)
        (row,) = held.entity.resting
        self.assertEqual((row.name, row.op_type, row.entity), (OVER_NAME, "des.platform", "PLT-002"))
        self.assertTrue(_close(row.volume_m3, self.hand_resting()), (row.volume_m3, self.hand_resting()))
        self.assertEqual(row, _module("design.supported_store").resting_preview(
            self.project, self.v01.uid, "STK-001#Acopio 2", "entity:PLT-002")[0], "la del diálogo es la que calcula la orden")
        summary = [(line.name, bool(line.alert)) for line in self.view.summary]
        self.assertEqual(summary[4], (row.text("es"), True))
        self.assertEqual(self.state()[:4], before[:4], "calcular no escribe")
        with self.assertRaises(RuntimeError) as caught:
            self.create()
        self.assertIn("confirmación expresa", str(caught.exception))
        self.assertIs(self.des_ops.calculation(), held)
        self.assertTrue(held.open)
        self.assertEqual(self.state()[:4], before[:4])

    def test_b_creating_with_the_confirmation_leaves_what_rested_with_its_support_removed_and_the_figures_add_up(self) -> None:
        """CE-016-03, CE-016-04, RF-016-11, RF-016-13, RF-016-14, P-9 (error 47 y 59): con la confirmación se crea; queda anotada en los ajustes de la
        operación (los m³, quién y cuándo) y **«Sobre acopio» queda en «apoyo retirado»** —con su causa— sin que se haya descartado nada; la
        superficie nueva **no baja de la base** en ninguna celda de la huella y retirado + apoyado + transición + no retirado es **lo que había sobre
        la base** (de los ficheros) a ≤ 10⁻⁹ relativo."""
        self.refresh()
        self.calculate()
        self.assertEqual(self.create(confirm_resting=True), {"FINISHED"})
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.states(), {"STK-001": "current", "PLT-001": "current", "PLT-002": "support_removed", "RMV-001": "current"})
        why = self.entities.stale_reason(self.project, self.v01.uid, "PLT-002")
        self.assertTrue(why.startswith("Apoyo retirado: "), why)
        for wanted in ("Acopio 2", REMOVAL_NAME):
            self.assertIn(wanted, why)
        self.assertEqual(self.rows("SELECT count(*) FROM gb_dataset WHERE status = 'discarded'"), [(0,)], "nada se descartó")
        confirmed = self.settings_of(REMOVAL_NAME)["removal_confirmed"]["resting"]
        self.assertTrue(_close(confirmed["volume_m3"], self.hand_resting()))
        self.assertEqual(confirmed["decided_by"], self.project.session.user_host)
        ((uid,),) = self.rows("SELECT uid FROM gb_operation WHERE op_type = ? AND status = 'done'", rem_ops.REMOVAL_TYPE)
        figures = dict(self.rows("SELECT key, value FROM gb_figure WHERE operation_uid = ?", uid))
        rows, cols = self.footprint("Acopio 2")
        result = self.surface(self.dprov.dataset_name("psf", REMOVAL_NAME))[rows, cols]
        start = self.surface(self.dprov.dataset_name("psf", OVER_NAME))[rows, cols]
        base = self.surface(self.base_name())[rows, cols]
        self.assertTrue(np.all(result >= np.minimum(start, base) - 1e-9), "ninguna celda de la huella baja de su base")
        above = math.fsum(float(value) for value in np.maximum(start - base, 0.0)) * CELL_M2
        total = math.fsum(figures[key] for key in ("des.rmv_removed_m3", "des.rmv_resting_m3", "des.rmv_transition_m3", "des.rmv_kept_m3"))
        self.assertTrue(_close(total, above), (total, above))
        self.assertGreater(figures["des.rmv_resting_m3"], 0.0)
        self.assertEqual(figures["des.rmv_wall_max_m"], 0.0, "la transición no deja pared")

    def test_c_a_fill_made_after_the_removal_is_only_stale(self) -> None:
        """CE-016-04, RF-015-17 (la orden real): un relleno **después** de la retirada (parte de la superficie de ``RMV-001``), sobre el mismo
        sitio, **no pierde su apoyo** y, si cambia, **solo queda obsoleto**, no «apoyo retirado»; lo apoyado que perdió su apoyo sigue en la lista."""
        self.platform(name=AFTER_NAME, feature=AFTER[0], start="entity:RMV-001", mode="CUT_FILL")
        self.assertEqual(self.states()["PLT-003"], "current")
        self.change("des.platform.plt_003.start_level_m", 111.0)
        self.assertEqual(self.states()["PLT-003"], "stale")
        self.assertEqual(self.states()["PLT-002"], "support_removed")
        self.assertTrue(self.entities.stale_reason(self.project, self.v01.uid, "PLT-003").startswith("Obsoleto"))
        self.assertEqual([item.entity for item in self.entities.retired_supports(self.project, self.v01.uid)], ["PLT-002"])

    def test_d_recompute_stale_does_not_remake_it_and_this_is_how_it_reads(self) -> None:
        """CE-016-04, RF-015-17, RF-016-14, P-9 (error 59; la nota de la T39; la orden real): con «Sobre acopio» obsoleta además de sin apoyo,
        «Recalcular lo obsoleto» **no la recalcula** —no escribe operaciones ni datos— y la unidad sale **``FAILED``** (no ``REFUSED``) con el
        motivo «espera una decisión»; **lo que se lee** en el resumen del modal es la línea «Operaciones recalculadas: 0» y **una línea de aviso
        (``WARNING``, no de error) por unidad que no se recalculó**: no hay un contador de «fallidas»."""
        self.change("des.platform.plt_002.start_level_m", 109.0)
        self.assertEqual(self.states()["PLT-002"], "support_removed")
        before = {uid for (uid,) in self.rows("SELECT uid FROM gb_operation")}
        platforms = self.rows("SELECT count(*) FROM gb_operation WHERE op_type = 'des.platform'")
        surfaces = self.rows("SELECT count(*) FROM gb_dataset WHERE name LIKE 'des!_psf!_%' ESCAPE '!' AND status = 'current'")
        operator = self.recompute()
        written = [op_type for op_type, uid in self.rows("SELECT op_type, uid FROM gb_operation ORDER BY fid") if uid not in before]
        self.assertNotIn("des.platform", written, "ni «Sobre acopio» ni nada de lo que depende de ella se recalcula")
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation WHERE op_type = 'des.platform'"), platforms)
        self.assertLessEqual(len(written), 1, "solo lo que sigue a la orden (la capa de entidades) pone algo al día")
        self.assertEqual(self.rows("SELECT count(*) FROM gb_dataset WHERE name LIKE 'des!_psf!_%' ESCAPE '!' AND status = 'current'"), surfaces)
        results = operator.result.results
        self.assertEqual([str(result.status) for result in results], ["failed"], [(str(item.status), item.text()) for item in results])
        (result,) = results
        self.assertEqual(result.code, "core.recompute_failed")
        for wanted in ("Sobre acopio", "Acopio 2", REMOVAL_NAME, "espera una decisión"):
            self.assertIn(wanted, result.text())
        self.assertEqual(self.states()["PLT-002"], "support_removed")
        log = list(operator.report_log)
        self.assertEqual(log[0], "Operaciones recalculadas: 0")
        self.assertEqual(len(log), 2, log)
        self.assertIn("espera una decisión", log[1])
        type(self).recompute_log = log

    def test_e_with_the_start_of_another_version_the_notice_names_that_surface(self) -> None:
        """CE-016-04, RF-016-14: con la superficie de partida **de otra versión** (el resultado de «Sobre acopio» de V01 visto desde V02), todo lo
        que tiene por encima de la superficie del acopio va a esa superficie **por su nombre**: una fila sin operación, con su volumen a mano, y el
        aviso nombra esa superficie."""
        removal = _module("design.removal")
        rows, cols = self.footprint("Acopio 2")
        ground = self.surface(self.dprov.dataset_name("stp", "Acopios"))[rows, cols]
        base = self.surface(self.base_name())[rows, cols]
        item = removal.RemovedStockpile("Acopio 2", "Acopio 2", rows.astype(np.int64) * platform_ops.CELLS + cols, base, ground)
        over = self.dprov.dataset_name("psf", OVER_NAME)
        found = removal.resting_on(self.project, self.v02.uid, item, over, detected_on=self.dprov.dataset_name("psf", TERRAIN_NAME))
        (row,) = found
        self.assertEqual((row.name, row.op_type, row.entity, row.operation_uid, row.surface), (over, None, None, None, over))
        self.assertTrue(_close(row.volume_m3, self.hand_resting()))
        (notice,) = removal.resting_notices("Acopio 2", found)
        self.assertIn(over, notice.text("es"))

    # --- CE-016-03 / E3: retirado «como plataforma» ----------------------------------------------

    def check_in_the_plane_and_edge_to_edge(self, held: Any, key: str) -> tuple[np.ndarray, np.ndarray]:
        """A mano, **de los ficheros** (E3, A9): la plataforma calculada ``held`` que retira el acopio ``key`` tiene **la huella entera —las celdas de
        la detección— en el plano de su base** (``100 + 0,03·y + 0,01·x``) a ≤ 10⁻⁹ m, con su pendiente (``100·√(0,01² + 0,03²)`` %) y **el eje de borde a
        borde** por el centro de la huella, en la dirección de máxima pendiente, a ≤ 10⁻⁹ relativo (y 10⁻⁶ m). Devuelve las filas y las columnas de la
        huella."""
        outcome = held.outcome
        window = outcome.footprint.window
        rows, cols = np.nonzero(outcome.footprint.cells)
        rows, cols = rows + window[0].start, cols + window[1].start
        wanted_rows, wanted_cols = self.footprint(key)
        self.assertEqual(sorted(zip(rows.tolist(), cols.tolist(), strict=True)), sorted(zip(wanted_rows.tolist(), wanted_cols.tolist(), strict=True)))
        x, y = platform_ops.centers()
        plane = 100.0 + 0.03 * y + 0.01 * x
        got = outcome.result[rows - window[0].start, cols - window[1].start]
        self.assertLessEqual(float(np.max(np.abs(got - plane[rows, cols]))), 1e-9, "la huella entera, en el plano de su base")
        self.assertTrue(_close(outcome.footprint.gradient_pct, PLANE_PCT), (outcome.footprint.gradient_pct, PLANE_PCT))
        norm = math.hypot(0.01, 0.03)
        ux, uy = 0.01 / norm, 0.03 / norm
        xs, ys = x[rows, cols], y[rows, cols]
        xc, yc = math.fsum(xs.tolist()) / len(xs), math.fsum(ys.tolist()) / len(ys)
        step_m = platform_ops.STEP_M
        projections = [(cx - xc) * ux + (cy - yc) * uy for px, py in zip(xs.tolist(), ys.tolist(), strict=True)
                       for cx in (px - step_m / 2, px + step_m / 2) for cy in (py - step_m / 2, py + step_m / 2)]
        (start, end) = outcome.footprint.axis.vertices
        for (vx, vy), t in ((start, min(projections)), (end, max(projections))):
            self.assertLessEqual(abs((vx - platform_ops.WEST) - (xc + t * ux)), 1e-6)
            self.assertLessEqual(abs((vy - platform_ops.SOUTH) - (yc + t * uy)), 1e-6)
        return rows, cols

    def test_f_removed_as_a_platform_the_whole_footprint_is_in_the_plane_and_the_axis_runs_from_edge_to_edge(self) -> None:
        """CE-016-03, RF-016-16, RF-015-27, A9, E3 (T41: **la orden real**, ``des_remove_stockpile`` con «como plataforma»): el Acopio 1 retirado
        «como plataforma» deja **la huella entera en el plano de su base** (``100 + 0,03·y + 0,01·x``) a ≤ 10⁻⁹ m, con su pendiente
        (``100·√(0,01² + 0,03²)`` %) y **el eje de borde a borde** por el centro de la huella, en la dirección de máxima pendiente, a ≤ 10⁻⁹
        relativo del cálculo a mano; «Crear» registra una operación ``des.platform`` sin ninguna capa con las cifras de la plataforma y de la
        retirada (la huella entera: transición 0) y **lo que sigue a la orden ya está hecho** —sin fallos: la capa de entidades tiene su fila—."""
        self.refresh()
        held = self.calculate(name="Acopio 1 como plataforma", stockpile="STK-001#Acopio 1", start="entity:PLT-003", as_platform=True,
                              edge_angle="35", reach="10")
        self.assertEqual((held.op_type, held.entity.code), ("des.platform", "PLT-004"))
        rows, cols = self.check_in_the_plane_and_edge_to_edge(held, "Acopio 1")
        self.assertEqual(held.entity.resting, (), "nada se apoya en el Acopio 1")
        self.assertFalse(held.needs_resting_confirmation)
        self.assertEqual(self.create(), {"FINISHED"})
        self.assertIsNone(self.des_ops.calculation())
        ((uid,),) = self.rows("SELECT uid FROM gb_operation WHERE op_type = 'des.platform' AND status = 'done' AND settings LIKE ?",
                              "%Acopio 1 como plataforma%")
        self.assertFalse([role for (role,) in self.rows(
            "SELECT role FROM gb_operation_io WHERE operation_uid = ? AND direction = 'in'", uid) if role in ("entity_layer", "entity_axis_layer")])
        figures = dict(self.rows("SELECT key, value FROM gb_figure WHERE operation_uid = ?", uid))
        self.assertEqual((figures["des.rmv_transition_m3"], figures["des.rmv_kept_m3"]), (0.0, 0.0))
        self.assertTrue(_close(figures["des.plat_area_m2"], len(rows) * CELL_M2))
        self.assertIn(self.states()["PLT-004"], ("current", "stale"), "la plataforma creada, calculada (obsoleta solo porque lo está la superficie de la que parte)")
        self.assertIn("PLT-004", self.layer_rows(), "lo que sigue a la orden ya está hecho: la capa de entidades tiene su fila")
        last = None
        for last in _module("design.entity_store").after_entity_change(self.project, self.v01.uid):
            pass
        self.assertIsNone(last.result.failure, None if last.result.failure is None else last.result.failure.reason)
        self.assertIsNone(last.result.layer_failure)

    def test_z_disabling_geoblender_leaves_no_temporary(self) -> None:
        """Principio 8: tras todo lo anterior, desactivar Geoblender no deja ningún temporal."""
        blender_ext.release()
        self.assertFalse(any(".tmp" in name for name in self.names()))


for _name in dir(rem_ops.RemoveStockpileTest):  # sus pruebas son suyas: aquí solo los ayudantes
    if _name.startswith("test"):
        setattr(StockpileCETest, _name, None)
del _name


class StockpileButtressCETest(StockpileCETest):
    """CE-016-04 con **el contrafuerte real** y E2, **con las órdenes reales** (``geoblender.des_add_buttress``,
    ``geoblender.des_remove_stockpile``, **«Recalcular lo obsoleto»**; T27 (b)): la misma cadena que :class:`StockpileCETest` con
    ``des_add_buttress`` en lugar del relleno ``PLT-002``. El proyecto es el mismo (la detección **de la versión**, ``STK-001``, sobre la
    superficie de «Terreno de V01»); el contrafuerte ``BTR-001`` tiene por zona de coronación **la marca del Acopio 2** (la capa de marcas es
    una capa de polígonos), coronación a 115 m (el ancla de ``EXPL_10_60_6``, 125 m, menos un banco) y **protege por defecto**: lo que sigue a
    crearlo declara su zona «sin corte» y deja obsoleto lo que usó las máscaras de antes, que «Recalcular lo obsoleto» pone al día."""

    @classmethod
    def setUpClass(cls) -> None:
        with mock.patch.object(platform_ops, "FEATURES", (*platform_ops.FEATURES, TERRAIN)):
            super(rem_ops.RemoveStockpileTest, cls).setUpClass()
        cls.survey_name = cls.write_grid("Levantamiento", rem_ops.survey())
        cls.write_marks()
        cls.platform(name=TERRAIN_NAME, feature=TERRAIN[0], start=cls.survey_name, mode="CUT", reach="4")
        cls.detect()
        assert bpy.ops.geoblender.des_save_bench_profile(
            name=PROFILE, kind="ADOPTADO", source="Plan de la prueba del contrafuerte", decided_by=platform_ops.PERSON,
            reason=platform_ops.REASON, scope="PROJECT", height="10", face="60", berm="6", anchor="125") == {"FINISHED"}
        cls.refresh()

    @classmethod
    def refresh(cls) -> None:
        """Las listas de los diálogos (también las del contrafuerte), leídas de nuevo (un guion no abre el diálogo que las lee)."""
        super().refresh()
        if getattr(cls, "survey_name", None) is not None:
            cls.panels.refresh_buttress_choices(cls.project)

    # --- Ayudas -------------------------------------------------------------------------------

    def form(self, **values: Any) -> dict[str, Any]:  # type: ignore[override]
        """Lo pedido en el diálogo de la retirada: el Acopio 2 desde la superficie del contrafuerte, con la transición a 35°."""
        return {"name": REMOVAL_NAME, "stockpile": "STK-001#Acopio 2", "start": "entity:BTR-001", "transition_angle": ANGLE, "in_steps": False,
                **values}

    def buttress(self, **values: Any) -> None:
        """«Calcula» y «crea» un contrafuerte con la orden real (el de la marca del Acopio 2 desde ``PLT-001``, protegiendo con 3 m de
        resguardo), con lo que sigue a crearlo."""
        self.refresh()
        form = {"name": BUTTRESS_NAME, "layer": rem_ops.MARKS_LAYER, "feature": "Acopio 2", "start": "entity:PLT-001", "profile": PROFILE,
                "crown": "115", "guard": "3", "in_steps": False, **values}
        self.assertEqual(bpy.ops.geoblender.des_add_buttress("EXEC_DEFAULT", **form), {"FINISHED"})
        self.assertEqual(bpy.ops.geoblender.des_add_buttress("EXEC_DEFAULT", confirm=True, in_steps=False), {"FINISHED"})
        self.refresh()

    def supported(self, code: str) -> dict[tuple[str, str | None], float]:
        """Las cifras ``des.supported_m3`` de la operación vigente de la entidad ``code``, por ``(entidad, clave del acopio)``."""
        entry = self.entities.registry(self.project, self.v01.uid).get(code)
        found: dict[tuple[str, str | None], float] = {}
        for scope, value in self.rows("SELECT scope, value FROM gb_figure WHERE operation_uid = ? AND key = 'des.supported_m3' ORDER BY fid",
                                      entry.operation_uid):
            where = json.loads(scope)
            found[(where["entity"], where.get("stockpile"))] = value
        return found

    def hand_resting(self) -> float:  # type: ignore[override]
        """A mano, **de los ficheros**: lo que el contrafuerte sube sobre el Acopio 2 —``Σ (contrafuerte − máx(partida, acopio))·4 m²`` en las
        celdas de su huella que pasan del espesor mínimo—, con la superficie de partida (la de ``PLT-001``) y la del acopio con que se detectó."""
        rows, cols = self.footprint("Acopio 2")
        top = self.surface(self.dprov.dataset_name("psf", BUTTRESS_NAME))[rows, cols]
        start = self.surface(self.dprov.dataset_name("psf", TERRAIN_NAME))[rows, cols]
        ground = self.surface(self.dprov.dataset_name("stp", "Acopios"))[rows, cols]
        thick = top - np.maximum(start, ground)
        return math.fsum(float(value) for value in thick[thick > THICKNESS_M]) * CELL_M2

    # --- CE-016-04: el contrafuerte real ---------------------------------------------------------

    def test_a_a_buttress_made_with_the_order_rests_on_the_stockpile_and_recompute_settles_what_protecting_leaves_stale(self) -> None:
        """RF-016-17, RF-016-14, RF-015-10, RF-015-16, D-1, CE-016-04 (E2, la orden real): ``des_add_buttress`` (la zona de coronación del
        Acopio 2, a 115 m, **protegiendo**) crea ``BTR-001`` y lo que sigue **declara «sin corte» sobre la zona de coronación** (la marca,
        no su huella); como la restricción cambia las máscaras, lo que las usó queda obsoleto (la detección, el terreno y el propio
        contrafuerte: lo esperado, como con una plataforma que protege) y **«Recalcular lo obsoleto» lo pone al día** (la detección y el
        contrafuerte de nuevo, con el mismo resultado); el contrafuerte **se apoya en el acopio** con **una sola cifra** cuyo valor es el
        cálculo a mano, de los ficheros, a ≤ 10⁻⁹ relativo."""
        self.refresh()
        self.assertEqual(self.states(), {"STK-001": "current", "PLT-001": "current"})
        self.buttress()
        self.assertEqual(self.states()["BTR-001"], "stale", "protege: su restricción cambia las máscaras que usó")
        (declared,) = [item for item in self.declared() if item.entity_code == "BTR-001"]
        ring = declared.parts[0][0]
        left, bottom = float(ring[:, 0].min()) - platform_ops.WEST, float(ring[:, 1].min()) - platform_ops.SOUTH
        right, top = float(ring[:, 0].max()) - platform_ops.WEST, float(ring[:, 1].max()) - platform_ops.SOUTH
        self.assertEqual((left, bottom, right, top), rem_ops.MARKS[1][1], "«sin corte» sobre la zona de coronación")
        self.assertEqual(declared.buffer_out_m, 3.0)
        operator = self.recompute()
        self.assertEqual(self.states(), {"STK-001": "current", "PLT-001": "current", "BTR-001": "current"}, list(operator.report_log))
        found = self.supported("BTR-001")
        self.assertIn(("STK-001", "Acopio 2"), found, "se apoya en el acopio, por su clave")
        self.assertEqual(sorted(found, key=str), [("PLT-001", None), ("STK-001", "Acopio 2")], "y en el terreno de la plataforma que lo parte")
        self.assertTrue(_close(found[("STK-001", "Acopio 2")], self.hand_resting()), (found, self.hand_resting()))
        self.assertGreater(found[("STK-001", "Acopio 2")], 0.0)

    def test_b_what_rests_on_the_stockpile_is_one_list_before_calculating_and_the_buttress_is_not_removed_without_confirming_it(self) -> None:
        """CE-016-04, RF-016-14, RF-015-17 (error 59; E2, las órdenes reales): retirar el Acopio 2 desde la superficie del contrafuerte da **una
        sola lista** antes de calcular —el contrafuerte, con su tipo y su volumen **a mano** (de los ficheros) a ≤ 10⁻⁹ relativo— en el diálogo y
        en el resumen, en ámbar; calcular **no escribe nada**; «Crear» sin la confirmación expresa se rechaza, no escribe nada y deja el cálculo
        abierto."""
        self.refresh()
        before = self.state()
        given, context, _dialog, _said = self.fake_dialog(name=REMOVAL_NAME, stockpile="STK-001#Acopio 2", start="entity:BTR-001",
                                                          properties=SimpleNamespace(is_property_set=lambda name: name in ("stockpile", "start")))
        self.cls.invoke(given, context, None)
        self.des_ops._refresh_resting(given, None)
        lines = self.panels.resting_lines()
        self.assertEqual(len(lines), 2)
        self.assertRegex(lines[0][0], rf"^{BUTTRESS_NAME} \(Contrafuerte\): \d+ m³ apoyados$")
        self.assertTrue(lines[0][1], "lo apoyado, en ámbar")
        held = self.calculate()
        self.assertTrue(held.needs_resting_confirmation)
        (row,) = held.entity.resting
        self.assertEqual((row.name, row.op_type, row.entity), (BUTTRESS_NAME, "des.buttress", "BTR-001"))
        self.assertTrue(_close(row.volume_m3, self.hand_resting()), (row.volume_m3, self.hand_resting()))
        self.assertEqual(row, _module("design.supported_store").resting_preview(
            self.project, self.v01.uid, "STK-001#Acopio 2", "entity:BTR-001")[0], "la del diálogo es la que calcula la orden")
        summary = [(line.name, bool(line.alert)) for line in self.view.summary]
        self.assertEqual([text for text, _alert in summary].count(row.text("es")), 1, "una sola vez")
        self.assertEqual(self.state()[:4], before[:4], "calcular no escribe")
        with self.assertRaises(RuntimeError) as caught:
            self.create()
        self.assertIn("confirmación expresa", str(caught.exception))
        self.assertIs(self.des_ops.calculation(), held)
        self.assertTrue(held.open)
        self.assertEqual(self.state()[:4], before[:4])

    def test_c_creating_the_removal_with_the_confirmation_leaves_the_buttress_with_its_support_removed(self) -> None:
        """CE-016-04, RF-016-11, RF-016-14, P-9 (error 59; E2): con la confirmación se crea; queda anotada en los ajustes de la operación (los
        m³, quién y cuándo) y **el contrafuerte queda en «apoyo retirado»** —con su causa— sin que se haya descartado nada; la detección, el
        terreno y la retirada, al día."""
        self.refresh()
        self.calculate()
        self.assertEqual(self.create(confirm_resting=True), {"FINISHED"})
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.states(), {"STK-001": "current", "PLT-001": "current", "BTR-001": "support_removed", "RMV-001": "current"})
        why = self.entities.stale_reason(self.project, self.v01.uid, "BTR-001")
        self.assertTrue(why.startswith("Apoyo retirado: "), why)
        for wanted in ("Acopio 2", REMOVAL_NAME):
            self.assertIn(wanted, why)
        self.assertEqual(self.rows("SELECT count(*) FROM gb_dataset WHERE status = 'discarded'"), [(0,)], "nada se descartó")
        confirmed = self.settings_of(REMOVAL_NAME)["removal_confirmed"]["resting"]
        self.assertTrue(_close(confirmed["volume_m3"], self.hand_resting()))
        self.assertEqual(confirmed["decided_by"], self.project.session.user_host)
        self.assertEqual([item.entity for item in self.entities.retired_supports(self.project, self.v01.uid)], ["BTR-001"])

    def test_d_a_buttress_made_after_the_removal_is_only_stale(self) -> None:
        """CE-016-04, RF-015-17 (la orden real): un contrafuerte **después** de la retirada (parte de la superficie de ``RMV-001``; sin
        proteger: no hace falta el resguardo), sobre el mismo sitio, **no pierde su apoyo** y, si cambia, **solo queda obsoleto**, no «apoyo
        retirado»; lo apoyado que perdió su apoyo sigue en la lista."""
        self.buttress(name=AFTER_NAME, start="entity:RMV-001", protect=False, guard="")
        self.assertEqual(self.states()["BTR-002"], "current")
        self.change("des.buttress.btr_002.crown_m", 125.0)
        self.assertEqual(self.states()["BTR-002"], "stale")
        self.assertEqual(self.states()["BTR-001"], "support_removed")
        self.assertTrue(self.entities.stale_reason(self.project, self.v01.uid, "BTR-002").startswith("Obsoleto"))
        self.assertEqual([item.entity for item in self.entities.retired_supports(self.project, self.v01.uid)], ["BTR-001"])

    def test_e_recompute_stale_does_not_remake_the_buttress_and_this_is_how_it_reads(self) -> None:
        """CE-016-04, RF-015-17, RF-016-14, P-9 (error 59; la nota de la T39; la orden real): con el contrafuerte obsoleto además de sin apoyo,
        «Recalcular lo obsoleto» **no lo recalcula** —no escribe operaciones ni datos de contrafuerte— y la unidad sale **``FAILED``** (no
        ``REFUSED``) con el motivo «espera una decisión»; **lo que se lee** en el resumen del modal es la línea «Operaciones recalculadas: n» y
        **una línea de aviso por unidad que no se recalculó**: no hay un contador de «fallidas». Como el contrafuerte **protege** (D-1), su
        parámetro está en lo que declara y cambiarlo cambia las máscaras: lo que las usó (el terreno, la detección…) también está obsoleto y **sí
        se recalcula** (las demás unidades salen hechas, y una sola, la del contrafuerte, fallida)."""
        self.change("des.buttress.btr_001.crown_m", 125.0)
        self.assertEqual(self.states()["BTR-001"], "support_removed")
        before = {uid for (uid,) in self.rows("SELECT uid FROM gb_operation")}
        buttresses = self.rows("SELECT count(*) FROM gb_operation WHERE op_type = 'des.buttress'")
        operator = self.recompute()
        written = [op_type for op_type, uid in self.rows("SELECT op_type, uid FROM gb_operation ORDER BY fid") if uid not in before]
        self.assertNotIn("des.buttress", written, "ni el contrafuerte ni nada de lo que depende de él se recalcula")
        self.assertEqual(self.rows("SELECT count(*) FROM gb_operation WHERE op_type = 'des.buttress'"), buttresses)
        self.assertNotIn("des.stockpile_removal", written, "ni la retirada, que parte de su superficie")
        results = operator.result.results
        failed = [result for result in results if str(result.status) == "failed"]
        self.assertEqual(len(failed), 1, [(str(item.status), item.text()) for item in results])
        self.assertEqual([str(result.status) for result in results if result not in failed], ["done"] * (len(results) - 1),
                         "las demás unidades —lo que usó las máscaras que cambió la declaración del contrafuerte— sí se recalculan")
        (result,) = failed
        self.assertEqual(result.code, "core.recompute_failed")
        for wanted in (BUTTRESS_NAME, "Acopio 2", REMOVAL_NAME, "espera una decisión"):
            self.assertIn(wanted, result.text())
        self.assertEqual(self.states()["BTR-001"], "support_removed")
        log = list(operator.report_log)
        self.assertEqual(log[0], f"Operaciones recalculadas: {len(results) - 1}")
        self.assertEqual(len(log), 2, log)
        self.assertIn("espera una decisión", log[1])

    def test_y_nothing_is_left_half_done(self) -> None:
        """Principio 8: tras todo lo anterior, ningún temporal."""
        self.assertFalse(any(".tmp" in name for name in self.names()))

    def declared(self) -> tuple[Any, ...]:
        """Las restricciones que declaran las entidades de V01."""
        declared = _module("core.constraints.declared")
        with self.project.read() as conn:
            return tuple(declared.read_in_version(conn, self.v01.uid))

    def test_z_disabling_geoblender_with_the_buttress_leaves_no_temporary(self) -> None:
        """Principio 8: desactivar Geoblender no deja ningún temporal."""
        blender_ext.release()
        self.assertIsNone(getattr(bpy.types, "GEOBLENDER_OT_des_add_buttress", None))
        self.assertFalse(any(".tmp" in name for name in self.names()))


for _name in dir(StockpileCETest):  # sus pruebas son suyas: aquí solo los ayudantes
    if _name.startswith("test") and _name not in StockpileButtressCETest.__dict__:
        setattr(StockpileButtressCETest, _name, None)
del _name


class StockpileAsPlatformCETest(StockpileCETest):
    """E3 con **lo apoyado** y **la orden real** (T41; ``des_remove_stockpile`` con «como plataforma»; RF-016-16, RF-016-14, RF-015-17, P-9): el
    proyecto de :class:`StockpileCETest` (la detección **de la versión** y el relleno ``PLT-002`` sobre el Acopio 2) con el Acopio 2 retirado
    «como plataforma» desde la superficie de ese relleno: lo apoyado se confirma, la plataforma deja la huella en el plano de su base y a «Sobre
    acopio» le queda el apoyo retirado."""

    PLATFORM_NAME = "Acopio 2 como plataforma"

    def platform_form(self, **values: Any) -> dict[str, Any]:
        """Lo pedido en el diálogo: el Acopio 2 como plataforma desde la superficie de «Sobre acopio», con el borde a 35° y 10 m."""
        return {"name": self.PLATFORM_NAME, "stockpile": "STK-001#Acopio 2", "start": "entity:PLT-002", "as_platform": True, "edge_angle": "35",
                "reach": "10", "in_steps": False, **values}

    def test_a_removing_a_stockpile_as_a_platform_asks_for_what_rests_on_it_and_leaves_its_support_removed(self) -> None:
        """CE-016-04, RF-016-14, RF-016-16, RF-015-17, P-9 (error 59; E3 con lo apoyado; la orden real): retirar el Acopio 2 **como plataforma** desde
        la superficie del relleno da **una sola lista** de lo apoyado (el relleno, con su volumen **a mano**, de los ficheros, a ≤ 10⁻⁹ relativo);
        calcular **no escribe nada**; «Crear» sin la confirmación expresa se rechaza y deja el cálculo abierto; con ella se crea, queda anotada en
        los ajustes de la operación (los m³, quién y cuándo) y **«Sobre acopio» queda en «apoyo retirado»** —con su causa— sin que se haya
        descartado nada; la huella entera queda **en el plano de su base**, con el eje **de borde a borde**, y la capa de entidades tiene su fila."""
        self.refresh()
        before = self.state()
        held = self.calculate(**self.platform_form())
        self.assertEqual((held.op_type, held.name, held.entity.code), ("des.platform", self.PLATFORM_NAME, "PLT-003"))
        self.assertTrue(held.needs_resting_confirmation)
        (row,) = held.entity.resting
        self.assertEqual((row.name, row.op_type, row.entity), (OVER_NAME, "des.platform", "PLT-002"))
        self.assertTrue(_close(row.volume_m3, self.hand_resting()), (row.volume_m3, self.hand_resting()))
        self.assertEqual(self.state()[:4], before[:4], "calcular no escribe")
        self.assertEqual(row, _module("design.supported_store").resting_preview(
            self.project, self.v01.uid, "STK-001#Acopio 2", "entity:PLT-002")[0], "la del diálogo es la que calcula la orden")
        rows, cols = self.check_in_the_plane_and_edge_to_edge(held, "Acopio 2")
        with self.assertRaises(RuntimeError) as caught:  # sin la confirmación expresa
            self.create()
        self.assertIn("confirmación expresa", str(caught.exception))
        self.assertIs(self.des_ops.calculation(), held)
        self.assertTrue(held.open)
        self.assertEqual(self.state()[:4], before[:4])

        self.assertEqual(self.create(confirm_resting=True), {"FINISHED"})
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.states()["PLT-002"], "support_removed", "«Sobre acopio» pierde su apoyo")
        self.assertEqual({code: state for code, state in self.states().items() if code != "PLT-003"},
                         {"STK-001": "current", "PLT-001": "current", "PLT-002": "support_removed"})
        why = self.entities.stale_reason(self.project, self.v01.uid, "PLT-002")
        self.assertTrue(why.startswith("Apoyo retirado: "), why)
        for wanted in ("Acopio 2", self.PLATFORM_NAME):
            self.assertIn(wanted, why)
        self.assertEqual(self.rows("SELECT count(*) FROM gb_dataset WHERE status = 'discarded'"), [(0,)], "nada se descartó")
        ((uid, settings),) = self.rows("SELECT uid, settings FROM gb_operation WHERE op_type = 'des.platform' AND status = 'done' "
                                       "AND settings LIKE ?", f"%{self.PLATFORM_NAME}%")
        confirmed = json.loads(settings)["removal_confirmed"]["resting"]
        self.assertTrue(_close(confirmed["volume_m3"], self.hand_resting()))
        self.assertEqual(confirmed["decided_by"], self.project.session.user_host)
        self.assertRegex(confirmed["decided_on"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
        figures = dict(self.rows("SELECT key, value FROM gb_figure WHERE operation_uid = ?", uid))
        self.assertTrue(_close(figures["des.rmv_resting_m3"], self.hand_resting()))
        self.assertEqual((figures["des.rmv_transition_m3"], figures["des.rmv_transition_m2"]), (0.0, 0.0), "la huella entera queda en el plano")
        self.assertTrue(_close(figures["des.plat_area_m2"], len(rows) * CELL_M2))
        self.assertIn("PLT-003", self.layer_rows(), "lo que sigue a la orden ya está hecho: la capa de entidades tiene su fila")
        self.assertEqual(str(self.layer_rows()["PLT-002"].state), "support_removed", "y enseña el apoyo retirado")

    def test_z_disabling_geoblender_leaves_no_temporary(self) -> None:
        """Principio 8: tras todo lo anterior, desactivar Geoblender no deja ningún temporal."""
        blender_ext.release()
        self.assertFalse(any(".tmp" in name for name in self.names()))


for _name in dir(StockpileCETest):  # sus pruebas son suyas: aquí solo los ayudantes
    if _name.startswith("test") and _name not in StockpileAsPlatformCETest.__dict__:
        setattr(StockpileAsPlatformCETest, _name, None)
del _name


if __name__ == "__main__":
    unittest.main()
