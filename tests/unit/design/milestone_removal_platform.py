# SPDX-License-Identifier: GPL-3.0-or-later
"""Retirar un acopio «como plataforma», con proyecto (spec 016, T21; HU-016-2; RF-016-16, RF-016-14, RF-015-02, RF-015-16, RF-009-11; plan 016
§5.4 A9, §5.7 P-3 y P-9, §5.8 H-5). Va al paso «hito» de ``check.py --completo`` (P-13: la rejilla de 2 m con proyecto); el cálculo
puro, con las cuentas a mano, está en ``test_removal_platform.py``, en el «verde».

La cantera de los acopios de 2 m con la detección ``Acopios`` (``STK-001``, V01), **en orden** (``test_a`` a ``test_h``): el Acopio 1 retirado
como plataforma (``PLT-001``), las dos plataformas «sobre el acopio» de la 015 encadenadas tras ella (``PLT-002``, sobre el Acopio 4, y ``PLT-003``,
sobre el 3) y el Acopio 4 retirado como plataforma tras ellas (``PLT-004``), con lo que se le apoyaba (``PLT-002``) confirmado, y que la deja en «apoyo
retirado»; después, recalcular, reproducir y la detección obsoleta.

- **Calcular** no escribe nada; la huella son las celdas del acopio, en el plano de su base; la cota y la pendiente, las de ese plano.
- **Crear** es **una** operación ``des.platform`` que consume el acopio (su tabla, su base y la superficie con que se detectó: tres entradas
  ``removed_stockpile``) y no una capa, lee su parámetro ``stockpile`` y escribe la superficie, la huella con su eje, el informe y las cifras de la
  plataforma y de la retirada (``des.rmv_*``); lo que sigue a la orden (la declaración y la capa de entidades) no falla con la detección en la versión.
- **Lo que se apoyaba** (RF-016-14): una sola lista antes de calcular, sin confirmarla no se crea y, creada, deja «apoyo retirado» a lo que se
  apoyaba en el acopio, que «Recalcular lo obsoleto» no rehace (P-9).
"""

from __future__ import annotations

import json
import math
from typing import Any, ClassVar

import numpy as np

from tests.support import quarry_fixtures as qfx
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.support.versions_fixtures import change_counter, files
from tests.unit.design import milestone_stockpile_supports as sup
from tests.unit.design import test_platform_operation as platform_ops
from tests.unit.design import test_removal_operation as rem
from tests.unit.design import test_stockpile_operation as ops

design_params = import_geoblender("design.params")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
freeze = import_geoblender("core.versions.freeze")
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")
provenance = import_geoblender("design.provenance")
recompute_mod = import_geoblender("core.provenance.recompute")
reproduce_mod = import_geoblender("core.versions.reproduce")
steps = import_geoblender("design.steps")

GRID = sup.GRID
USER = sup.USER
SURVEY = sup.SURVEY
ONE, FOUR = "Acopio 1 como plataforma", "Acopio 4 como plataforma"
EDGE_DEG, REACH_M = 35.0, 12.0
"""El ángulo de borde y el alcance de las plataformas de la prueba (datos de ENTRADA: D-7 y D-20, sin valor por defecto)."""
BASE = provenance.dataset_name("stb", "Acopios mineral")
"""El dato de la base del material de la detección."""


def of_stockpile(name: str, key: str, *, start: str = SURVEY, **changes: Any) -> Any:
    """La petición de retirar el acopio ``key`` de ``STK-001`` como plataforma desde ``start``."""
    options: dict[str, Any] = {"edge_angle_deg": EDGE_DEG, "reach_m": REACH_M, **changes}
    return model.PlatformRequest.of_stockpile(name, f"STK-001#{key}", start, **options)


class AsPlatformTest(rem.RemovalCase):
    """RF-016-16, RF-016-14, RF-015-02, RF-015-16, RF-009-11, **en orden**: la detección ``Acopios`` (``STK-001``, V01), el Acopio 1 como
    plataforma, las dos plataformas de la 015, el Acopio 4 como plataforma y lo que sigue."""

    created: ClassVar[Any]
    revision: ClassVar[str]
    resting_m3: ClassVar[float]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.detect()
        qfx.write_feature_layer(cls.project, cls.clock, sup.axes_layer())
        cls.clock.advance(minutes=1)

    @classmethod
    def calculate_as_platform(cls, request: Any) -> Any:
        """«Calcula» ``request`` en V01 (la ``Calculation``, sin registrar nada)."""
        return platform_ops.finish(steps.platform_run(cls.project, request, masks=cls.masks_v1, version=cls.v1.uid))

    @classmethod
    def make_as_platform(cls, request: Any, *, confirm: bool = False) -> tuple[Any, Any]:
        """«Calcula» y «crea» ``request`` (un minuto después de lo anterior; con la contrapendiente y lo apoyado confirmados si ``confirm``)."""
        cls.clock.advance(minutes=1)
        calculation = cls.calculate_as_platform(request)
        if calculation.needs_confirmation:
            calculation.confirm_counterslope()
        if confirm:
            calculation.confirm_removal(resting=True)
        stored = calculation.create(decided_by=USER)
        cls.clock.advance(minutes=1)
        return calculation, stored

    def hand_removed(self, key: str) -> float:
        """A mano: ``Σ máx(z − base, 0) · 4`` m³ sobre las celdas de la huella del acopio ``key``, con el levantamiento calculado aparte
        (``stockpile_data.survey``) y la base leída de su fichero: lo que retira, si nada se le apoyó y lo baja todo."""
        survey, base = sdata.survey(GRID), self.surface_of(BASE)
        rows, cols = self.cells_of(key)
        return math.fsum(max(float(survey[row, col] - base[row, col]), 0.0) for row, col in zip(rows, cols, strict=True)) * 4.0

    # --- El Acopio 1 como plataforma ---------------------------------------------------------------------------------

    def test_a_calculating_writes_nothing_and_leaves_the_whole_footprint_in_the_plane_of_its_base(self) -> None:
        """RF-016-16, RF-015-03, RF-015-20 (A9): «Calcular» el Acopio 1 como plataforma **no escribe nada** (solo el temporal de su superficie, que
        descartar borra); la huella de la plataforma son **las celdas del acopio** (las de su fila de ``des_stk_``), su superficie en ellas es **el
        plano de su base** (la de su fichero) a ≤ 10⁻⁹ m, su pendiente es la del plano de la detección (la inclinación de 3° del levantamiento) y la
        cota inicial la de su eje; nada se le apoya y la retirada retira lo que había sobre la base a ≤ 10⁻⁹ relativo."""
        before = self.state()
        calculation = self.calculate_as_platform(of_stockpile(ONE, "Acopio 1"))
        self.assertEqual(self.state(), before, "calcular no escribe")
        self.assertEqual(len(self.temporaries()), 1, "solo el temporal de la superficie")
        found = calculation.entity
        self.assertEqual((calculation.op_type, calculation.name, found.code, found.origin.ref), ("des.platform", ONE, "PLT-001", "STK-001#Acopio 1"))
        outcome = calculation.outcome
        window = outcome.footprint.window
        rows, cols = np.nonzero(outcome.footprint.cells)
        np.testing.assert_array_equal((rows + window[0].start) * GRID.ncols + cols + window[1].start, self.footprint_of("Acopio 1"))
        base = self.surface_of(BASE)
        wanted = base.reshape(-1)[self.footprint_of("Acopio 1")]
        self.assertLessEqual(float(np.max(np.abs(outcome.result[outcome.footprint.cells] - wanted))), 1e-9, "la huella, en el plano de su base")
        slope = 100.0 * math.tan(math.radians(sdata.SURVEY_TILT_DEG))
        self.assertLessEqual(abs(outcome.footprint.gradient_pct - slope) / slope, 1e-6)
        (start, end) = outcome.footprint.axis.vertices
        self.assertEqual(outcome.footprint.axis.principal, False)
        self.assertGreater(math.hypot(end[0] - start[0], end[1] - start[1]), 0.0)
        self.assertEqual(found.resting, ())
        self.assertFalse(calculation.needs_resting_confirmation)
        removed = outcome.removal
        self.assertLessEqual(abs(removed.removed_m3 - self.hand_removed("Acopio 1")) / removed.removed_m3, 1e-9, "retirado, a mano")
        self.assertEqual((removed.resting_m3, removed.kept_m3), (0.0, 0.0))
        parts = math.fsum((removed.removed_m3, removed.resting_m3, removed.transition_m3, removed.kept_m3))
        self.assertLessEqual(abs(parts - removed.above_base_m3) / removed.above_base_m3, 1e-9)
        self.assertEqual({item.key for item in calculation.figures if item.key.startswith("des.rmv")},
                         {"des.rmv_removed_m3", "des.rmv_resting_m3", "des.rmv_transition_m3", "des.rmv_kept_m3", "des.rmv_transition_m2"})
        calculation.discard()
        self.assertEqual(self.state(), before)

    def test_b_creating_registers_one_platform_operation_that_consumes_the_stockpile_and_not_a_layer(self) -> None:
        """RF-016-16, RF-015-01, RF-015-02, P-3, H-5 (la huella es un dato producido de la versión): «Crear» registra **una** operación
        ``des.platform`` cuyas entradas son la superficie de partida y, con el papel ``removed_stockpile``, el acopio (su tabla, su base y la
        superficie con que se detectó), **sin ninguna capa**; lee el parámetro ``stockpile`` (y no la capa, la geometría ni la cota y la pendiente,
        que salen del plano) y deja sus parámetros con su origen (el plano del acopio), la superficie, la huella con su eje, el informe y las cifras
        de la plataforma y de la retirada con el ámbito de la entidad; y lo que sigue a la orden **no falla** con la detección en la versión."""
        calculation, stored = self.make_as_platform(of_stockpile(ONE, "Acopio 1"))
        type(self).created = calculation
        uid = str(stored.handle.uid)
        self.assertEqual(self.query("SELECT op_type, scope, status FROM gb_operation WHERE uid = ?", uid), [("des.platform", "version", "done")])
        self.assertEqual(self.operation_of("PLT-001"), uid)
        inputs = self.inputs_of(uid)
        self.assertEqual(inputs[0], ("surface", SURVEY))
        self.assertEqual([item for item in inputs if item[0] == "removed_stockpile"],
                         [("removed_stockpile", sup.TABLE), ("removed_stockpile", BASE), ("removed_stockpile", sup.DETECTED)])
        self.assertFalse([role for role, _name in inputs if role in ("entity_layer", "entity_axis_layer")], "ninguna capa")
        read = {name for (name,) in self.query("SELECT p.key FROM gb_operation_param AS p WHERE p.operation_uid = ?", uid)}
        self.assertIn("des.platform.plt_001.stockpile", read)
        for param in ("layer", "feature", "start_level_m", "gradient_pct"):
            self.assertNotIn(f"des.platform.plt_001.{param}", read, f"{param}: no lo lee (sale del plano)")
        rows = {key: (json.loads(value), source, kind) for key, value, source, kind in self.query(
            "SELECT key, value, source, source_kind FROM gb_parameter WHERE key LIKE 'des.platform.plt_001.%' AND scope = 'version'")}
        self.assertEqual(rows["des.platform.plt_001.stockpile"][0], "STK-001#Acopio 1")
        self.assertTrue(rows["des.platform.plt_001.start_level_m"][1].startswith("plano de la base del acopio «Acopio 1»"))
        self.assertEqual(rows["des.platform.plt_001.start_level_m"][2], "algorithm")
        self.assertEqual(rows["des.platform.plt_001.gradient_pct"][0], calculation.outcome.footprint.gradient_pct)
        self.assertEqual((rows["des.platform.plt_001.edge_angle_deg"][0], rows["des.platform.plt_001.reach_m"][0]), (EDGE_DEG, REACH_M))
        surface = provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, ONE)
        self.assertEqual([name for _role, name in self.outputs_of(uid)],
                         [surface, provenance.dataset_name(provenance.ENTITY_TABLE, ONE),
                          provenance.dataset_name(provenance.ENTITY_REPORT_TABLE, ONE)])
        np.testing.assert_array_equal(self.surface_of(surface)[calculation.outcome.footprint.window],
                                      calculation.outcome.result)
        figures = self.figures_by_key(uid)
        self.assertEqual(figures["des.rmv_removed_m3"], calculation.outcome.removal.removed_m3)
        self.assertLessEqual(abs(figures["des.rmv_removed_m3"] - self.hand_removed("Acopio 1")) / figures["des.rmv_removed_m3"], 1e-9)
        self.assertEqual(figures["des.plat_area_m2"], calculation.outcome.footprint.area_m2)
        scopes = {json.loads(scope)["entity"] for (scope,) in self.query(
            "SELECT scope FROM gb_figure WHERE operation_uid = ? AND key LIKE 'des.rmv%'", uid)}
        self.assertEqual(scopes, {"PLT-001"})
        locator = provenance.dataset_locator(provenance.ENTITY_TABLE, ONE, "V01")
        ((code, name, kind, start, layer, fid),) = self.query(f'SELECT code, name, kind, start_surface, layer, source_fid FROM "{locator}"')
        row = next(item for item in self.query(f'SELECT key, layer, source_fid FROM "{provenance.dataset_locator(provenance.STOCKPILES_TABLE, sup.DETECTION, "V01")}"')
                   if item[0] == "Acopio 1")
        self.assertEqual((code, name, kind, start, layer, fid), ("PLT-001", ONE, "platform", SURVEY, row[1], row[2]))
        report = {quantity: value for quantity, value, _unit, _note in self.query(
            f'SELECT quantity, value, unit_code, note FROM "{provenance.dataset_locator(provenance.ENTITY_REPORT_TABLE, ONE, "V01")}"')}
        self.assertEqual(report["rmv_removed_m3"], figures["des.rmv_removed_m3"])
        self.assertEqual(report["rmv_resting_m3"], 0.0)
        entry = entities.registry(self.project, self.v1.uid).get("PLT-001")
        assert entry is not None
        self.assertEqual((entry.record.kind, entry.record.name, entry.record.state), (entities.EntityKind.PLATFORM, ONE, entities.EntityState.CURRENT))
        chain = ops.last(entity_store.after_entity_change(self.project, self.v1.uid))
        self.assertIsNone(chain.failure, None if chain.failure is None else chain.failure.reason)
        self.assertIsNone(chain.layer_failure, None if chain.layer_failure is None else chain.layer_failure.reason)
        shown = [item.code for item in entity_store.layer_sources(self.project, self.v1)]
        self.assertEqual([code for code in shown if not code.startswith("STK-001#")], ["PLT-001"])  # la plataforma y, de la T34, los acopios de la detección
        self.assertEqual(len(shown), 1 + len([code for code in shown if code.startswith("STK-001#")]))
        self.assertEqual(self.temporaries(), [])

    # --- Lo que se apoyaba ---------------------------------------------------------------------------------------------

    def test_c_two_platforms_of_the_015_fill_over_the_acopios_4_and_3_after_it(self) -> None:
        """RF-015-15, RF-015-04 (el marco de las dependencias): «Sobre el acopio 4» (``PLT-002``) parte de la superficie del Acopio 1 retirado
        y «Sobre el acopio 3» (``PLT-003``), de la de aquella; cada una se apoya en **su** acopio por su clave."""
        self.made(sup.over(sup.FOUR, start="entity:PLT-001"))
        self.made(sup.over(sup.THREE, start="entity:PLT-002"))
        uids = {code: self.operation_of(code) for code in ("PLT-001", "PLT-002", "PLT-003")}
        self.assertEqual(list(self.supported_of(uids["PLT-002"])), [("STK-001", "Acopio 4")])
        self.assertEqual(list(self.supported_of(uids["PLT-003"])), [("STK-001", "Acopio 3")])
        type(self).resting_m3 = self.supported_of(uids["PLT-002"])[("STK-001", "Acopio 4")]
        self.assertGreater(self.resting_m3, 0.0)

    def test_d_what_rested_on_the_stockpile_is_one_list_and_is_not_removed_without_confirming_it(self) -> None:
        """RF-016-14, RF-015-17 (error 59): con «Sobre el acopio 4» apoyada sobre el Acopio 4, retirarlo como plataforma da **una sola lista**
        antes de calcular (la plataforma con su volumen, el de su cifra ``des.supported_m3``); «Crear» sin confirmarla se rechaza
        (``des.removal_resting_unconfirmed``) **sin escribir nada y sin cerrar el cálculo**; confirmada, se crea con lo confirmado (quién, cuándo y
        los m³) en los ajustes de la operación, y la plataforma que se apoyaba queda en «apoyo retirado» (P-9) sin descartar nada, la del
        Acopio 3 no."""
        calculation = self.calculate_as_platform(of_stockpile(FOUR, "Acopio 4", start="entity:PLT-003"))
        found = calculation.entity
        self.assertEqual([(row.name, row.entity, row.op_type) for row in found.resting], [(sup.FOUR, "PLT-002", "des.platform")])
        self.assertLessEqual(abs(found.resting[0].volume_m3 - self.resting_m3) / self.resting_m3, 1e-9, "el volumen de la lista, el de su cifra")
        self.assertTrue(calculation.needs_resting_confirmation)
        self.assertGreater(calculation.outcome.removal.resting_m3, 0.0)
        self.assertEqual([notice.code for notice in calculation.summary.notices][:1], ["des.removal_resting"], "el aviso, el primero del resumen")
        before = self.state()
        with self.assertRaises(messages.DesignError) as caught:
            calculation.create(decided_by=USER)
        self.assertEqual(caught.exception.code, "des.removal_resting_unconfirmed")
        self.assertEqual(self.state(), before, "el rechazo no escribe nada")
        self.assertTrue(calculation.open, "y el cálculo sigue abierto")
        calculation.confirm_removal(resting=True)
        if calculation.needs_confirmation:
            calculation.confirm_counterslope()
        self.clock.advance(minutes=1)
        stored = calculation.create(decided_by=USER)
        uid = str(stored.handle.uid)
        (settings,) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", uid)
        confirmed = json.loads(settings[0])["removal_confirmed"]["resting"]
        self.assertEqual((confirmed["decided_by"], confirmed["volume_m3"]), (USER, found.resting[0].volume_m3))
        self.assertTrue(confirmed["decided_on"])
        states = {entry.record.code: entry.record.state for entry in entities.registry(self.project, self.v1.uid)}
        self.assertEqual(states["PLT-002"], entities.EntityState.SUPPORT_REMOVED, "la que se apoyaba en el acopio, «apoyo retirado»")
        self.assertEqual(states["PLT-003"], entities.EntityState.CURRENT, "la del Acopio 3, no")
        self.assertEqual(states["PLT-004"], entities.EntityState.CURRENT)
        retired = entities.removed_supports_of(self.project, self.v1.uid, self.operation_of("PLT-002"))
        self.assertEqual([(item.code, item.stockpile) for item in retired], [("PLT-004", "STK-001#Acopio 4")])
        self.assertEqual(entities.removed_supports_of(self.project, self.v1.uid, self.operation_of("PLT-003")), ())

    def test_e_recalculating_what_is_stale_leaves_the_retired_support_alone_and_reuses_what_was_confirmed(self) -> None:
        """RF-015-16, RF-015-02, RF-016-14, P-9: cambiar el alcance de la plataforma del Acopio 4 la deja obsoleta y «Recalcular lo obsoleto» la
        rehace con **los parámetros vigentes de su entidad** (una operación nueva que sustituye a la anterior, sin parámetros nuevos) y **reutiliza lo
        apoyado que se confirmó al crear** (el mismo decisor y la misma fecha), sin pedirlo otra vez; la que está en «apoyo retirado» **no** se rehace."""
        old, retired_before = self.operation_of("PLT-004"), self.operation_of("PLT-002")
        key = design_params.entity_key("PLT-004", "reach_m")
        before = self.query("SELECT key FROM gb_parameter WHERE key LIKE 'des.platform.plt_004.%' ORDER BY key")
        self.change(key, 10.0)
        self.assertEqual(entities.registry(self.project, self.v1.uid).get("PLT-004").record.state, entities.EntityState.STALE)
        self.clock.advance(minutes=1)
        outcome = ops.finish(recompute_mod.recompute_steps(self.project))
        self.assertTrue(all(result.status == recompute_mod.UnitStatus.DONE for result in outcome.results), outcome.results)
        new = self.operation_of("PLT-004")
        self.assertNotEqual(new, old)
        self.assertEqual(self.query("SELECT supersedes_uid, status FROM gb_operation WHERE uid = ?", new), [(old, "done")])
        self.assertEqual(self.operation_of("PLT-002"), retired_before, "«apoyo retirado» no se rehace en «Recalcular lo obsoleto»")
        self.assertEqual(entities.registry(self.project, self.v1.uid).get("PLT-002").record.state, entities.EntityState.SUPPORT_REMOVED)
        self.assertEqual(entities.registry(self.project, self.v1.uid).get("PLT-004").record.state, entities.EntityState.CURRENT)
        self.assertEqual(self.query("SELECT key FROM gb_parameter WHERE key LIKE 'des.platform.plt_004.%' ORDER BY key"), before,
                         "sin parámetros nuevos")
        (old_settings,) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", old)
        (new_settings,) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", new)
        self.assertEqual(json.loads(new_settings[0])["removal_confirmed"], json.loads(old_settings[0])["removal_confirmed"],
                         "lo confirmado al crear, el mismo decisor y la misma fecha")
        read = {name for (name,) in self.query("SELECT p.key FROM gb_operation_param AS p WHERE p.operation_uid = ?", new)}
        self.assertIn("des.platform.plt_004.stockpile", read)
        self.assertEqual(self.temporaries(), [])

    def test_f_reproducing_the_frozen_revision_gives_the_same_surface_tables_and_figures(self) -> None:
        """RF-009-11, RF-015-02: congelada ``V01.r1``, reproducirla —**sin el proyecto**: desde lo congelado, la superficie de partida, las
        máscaras, el acopio (su tabla, su base y la superficie con que se detectó) y los parámetros— da, de cada plataforma que retira un acopio,
        la misma superficie, la misma huella con su eje, el mismo informe y las mismas cifras de la plataforma y de la retirada; reproducir no
        escribe nada en el proyecto."""
        self.clock.advance(minutes=1)
        frozen = ops.finish(freeze.freeze_steps(self.project, self.v1.uid, reason="Entrega de la prueba"))
        type(self).revision = str(frozen.frozen.uid)
        self.clock.advance(minutes=1)
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        report = ops.finish(reproduce_mod.reproduce_steps(self.project, self.revision))
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root)), before, "reproducir no escribe en el proyecto")
        uids = {self.operation_of(code) for code in ("PLT-001", "PLT-004")}
        mine = [check for check in report.outputs if check.operation_uid in uids]
        self.assertEqual(len(mine), 6, "la superficie, la huella y el informe de cada una")
        self.assertTrue(all(check.same for check in mine), [check for check in mine if not check.same])
        self.assertTrue(all(check.same for check in report.outputs), [check for check in report.outputs if not check.same])
        self.assertTrue(all(check.same for check in report.figures), [check for check in report.figures if not check.same])
        self.assertEqual(len([check for check in report.figures if check.operation_uid in uids and "rmv" in check.key]), 10,
                         "las cinco cifras de la retirada de cada una")
        self.assertEqual({note.op_type for note in report.not_reproducible}, {"des.declare_constraints"},
                         "lo único que no se reproduce es la declaración de ``test_b``, que esta clase de pruebas no registra")

    # --- Los rechazos --------------------------------------------------------------------------------------------------

    def test_g_the_stockpile_must_exist_and_the_detection_must_be_up_to_date(self) -> None:
        """RF-016-12, RF-016-16, RF-015-08: un acopio que no es de ninguna detección (``des.removal_stockpile_unknown``) y con la detección
        **obsoleta** (``des.removal_detection_stale``, nombrando el acopio y lo que cambió) se rechazan sin escribir nada; el borde sin ángulo ni
        alcance, también (``des.entity_param_missing``)."""
        for request, code in ((of_stockpile("Otra", "Nada", start="entity:PLT-004"), "des.removal_stockpile_unknown"),
                              (of_stockpile("Otra", "Acopio 2", start="entity:PLT-004", reach_m=None), "des.entity_param_missing"),
                              (of_stockpile("Otra", "Acopio 2", start="entity:PLT-004", edge_angle_deg=None), "des.entity_param_missing")):
            before = self.state()
            with self.assertRaises(messages.DesignError) as caught:
                self.calculate_as_platform(request)
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(self.state(), before, "el rechazo ha escrito algo")
        self.change(design_params.entity_key("STK-001", "margin_m"), 8.0)
        before = self.state()
        with self.assertRaises(messages.DesignError) as caught:
            self.calculate_as_platform(of_stockpile("Otra", "Acopio 2", start="entity:PLT-004"))
        error = caught.exception
        self.assertEqual(error.code, "des.removal_detection_stale")
        self.assertEqual((error.values["stockpile"], error.values["detection"]), ("Acopio 2", "Acopios"))
        self.assertEqual(self.state(), before)
        self.assertEqual(self.temporaries(), [])
