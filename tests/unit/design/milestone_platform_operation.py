# SPDX-License-Identifier: GPL-3.0-or-later
"""Pruebas de hito de «test_platform_operation» (spec 015, T48; plan 015 §7.4): las clases que pesan,
movidas sin cambiar una aserción. El «verde» deja en ``test_platform_operation`` las más ligeras de cada
requisito; las de aquí las ejecuta el paso «hito» de ``tools/check.py --completo`` (la publicación
lo pide siempre).
"""

from __future__ import annotations

import json
import re
from typing import Any, ClassVar
from unittest import mock

import numpy as np

from tests.support import entity_fixtures as efx
from tests.support import quarry_fixtures as qfx
from tests.support import res_fixtures
from tests.support.versions_fixtures import change_counter, files, freeze_rows
from tests.unit.design import test_platform_prepare as prep
from tests.unit.design.test_platform_operation import (
    CELL_M2,
    CreateCase,
    EDGE_HOLE_DATASET,
    EPR,
    GRID,
    LOADING,
    ObsoleteCase,
    OperationCase,
    PRP,
    PRP_TABLE,
    PSF,
    PSF2,
    RecomputeCase,
    START,
    TOWER,
    WORKSHOP,
    codes,
    core_params,
    design_params,
    design_store,
    entities_module,
    entity_store,
    figures_mod,
    finish,
    freeze,
    geotiff_reader,
    gis,
    messages,
    only,
    operations,
    platform,
    preview,
    provenance,
    recompute_function,
    recompute_mod,
    reproduce_mod,
    timeutil,
)


class ReproduceTest(RecomputeCase):
    """RF-015-02, RF-009-11, RF-009-19: P1 (línea), P2 (de la superficie de P1) y P3 (un polígono con su eje
    enlazado, que parte de otro terreno y se apoya en la superficie de P1) creadas en V01; la cota inicial de
    P1 se cambia en la versión (249 m, no los 250 de su capa) y las tres se recalculan; congeladas en
    V01.r1 (las operaciones de ``uids`` son las del recálculo)."""

    NAME = "Explanada con eje"
    revision: ClassVar[str]
    uids: ClassVar[tuple[str, ...]]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())
        cls.made(prep.request(WORKSHOP, start="entity:PLT-001"))
        cls.made(prep.polygon_request(cls.NAME, start=EDGE_HOLE_DATASET, support="entity:PLT-001"))
        cls.change(design_params.entity_key("PLT-001", "start_level_m"), 249.0)
        cls.clock.advance(minutes=1)
        again = finish(recompute_mod.recompute_steps(cls.project))
        assert [result.status for result in again.results] == [recompute_mod.UnitStatus.DONE] * 3
        registry = entities_module.registry(cls.project, cls.v1.uid)
        cls.uids = tuple(str(registry.get(code).operation_uid)
                         for code in ("PLT-001", "PLT-002", "PLT-003"))
        cls.clock.advance(minutes=1)
        frozen = finish(freeze.freeze_steps(cls.project, cls.v1.uid, reason="Entrega de la prueba"))
        cls.revision = str(frozen.frozen.uid)
        cls.clock.advance(minutes=1)

    def reproduce(self) -> Any:
        """La reproducción de V01.r1, comprobando que **no escribió** nada en el proyecto (los ficheros y el
        contador de cambios de la base, sin la caché donde reproduce)."""
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        report = finish(reproduce_mod.reproduce_steps(self.project, self.revision))
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)),
                          change_counter(self.root)), before, "reproducir no escribe en el proyecto")
        return report

    def assert_same(self, report: Any) -> None:
        """Las tres plataformas reprodujeron sus tres salidas y sus cifras, todas iguales."""
        mine = [check for check in report.outputs if check.operation_uid in self.uids]
        self.assertEqual(sorted((check.operation_uid, check.role) for check in mine),
                         sorted((uid, role) for uid in self.uids
                                for role in ("entity", "entity_report", "entity_surface")))
        self.assertTrue(all(check.same for check in mine), [c for c in mine if not c.same])
        for uid in self.uids:
            found = [check for check in report.figures if check.operation_uid == uid]
            self.assertEqual({check.key for check in found},
                             {key for key, _scope in self.figures_of(uid)})
            self.assertGreaterEqual(len(found), 9)
            self.assertTrue(all(check.same for check in found), [c for c in found if not c.same])
        self.assertFalse(report.not_reproducible)
        self.assertTrue(report.matches)

    def test_d1_reproducing_the_frozen_revision_gives_the_same_without_writing(self) -> None:
        """RF-015-02, RF-009-11: reproducir V01.r1 —sin proyecto, desde la capa (y la de los ejes), la
        partida, el apoyo, las máscaras y los parámetros congelados— da, de cada plataforma, la superficie,
        la tabla y el informe con el **mismo hash** que registró su operación (la de P2 parte de la
        superficie de P1; la de P3, de otro terreno, con el apoyo ``entity:PLT-001`` y un polígono con su eje
        enlazado) y las mismas cifras, sin escribir nada en el proyecto."""
        self.assert_same(self.reproduce())

    def test_e2_changing_and_recomputing_after_freezing_leaves_the_frozen_revision_as_it_was(self) -> None:
        """RF-015-16, RF-009-19, RF-009-11, RF-008-26: congelada V01.r1, cambiar el alcance de P1 deja
        obsoletas (en curso, en la revisión abierta, D-23) las tres operaciones y «Recalcular lo obsoleto» las
        repite en orden de dependencia (P1 primero) **registrando las nuevas en la revisión abierta**; lo
        congelado no cambia (la revisión sigue congelada, sus elementos son los mismos, las operaciones
        sustituidas quedan en ella como historia, no se marca nada de ella) y V01.r1 se reproduce otra vez
        igual, con los hash de cuando se congeló (aunque lo vivo ya sea otro)."""
        reach = design_params.entity_key("PLT-001", "reach_m")
        items = self.query("SELECT * FROM gb_revision_item WHERE revision_uid = ? ORDER BY fid",
                           self.revision)
        self.assertTrue(items)
        frozen = {uid: self.hashes_of(uid) for uid in self.uids}
        self.change(reach, 25.0)
        self.assertEqual(self.plan_units(), [(self.uids[0],), (self.uids[1],), (self.uids[2],)])
        self.clock.advance(minutes=1)
        outcome = finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual([result.status for result in outcome.results],
                         [recompute_mod.UnitStatus.DONE] * 3)
        (opened,) = self.query("SELECT uid FROM gb_revision WHERE version_uid = ? AND state = 'open'",
                               self.v1.uid)[0]
        made = [result.operations[0] for result in outcome.results]
        self.assertEqual(self.query("SELECT supersedes_uid, revision_uid FROM gb_operation "
                                    "WHERE uid IN (?, ?, ?) ORDER BY fid", *made),
                         [(old, opened) for old in self.uids])
        self.assertEqual(self.query("SELECT revision_uid FROM gb_operation WHERE uid IN (?, ?, ?) "
                                    "ORDER BY fid", *self.uids), [(self.revision,)] * 3)
        self.assertEqual(self.query("SELECT state FROM gb_revision WHERE uid = ?", self.revision),
                         [("frozen",)])
        self.assertEqual(self.query("SELECT * FROM gb_revision_item WHERE revision_uid = ? "
                                    "ORDER BY fid", self.revision), items)
        self.assertEqual({uid: self.hashes_of(uid) for uid in self.uids}, frozen)
        self.assertNotEqual(self.hashes_of(made[0])[PSF], frozen[self.uids[0]][PSF], "lo vivo cambió")
        self.assertEqual(self.recompute_plan(), [])
        self.assert_same(self.reproduce())


class ConfirmedCounterSlopeTest(RecomputeCase):
    """RF-015-23, RF-015-02, RF-008-26 (T15; decisión de la sesión principal, revisable): la contrapendiente
    que la persona confirmó al crear queda en los ajustes de la operación (cuánto, en qué abscisa, quién y
    cuándo) y un recálculo la reutiliza mientras la nueva no pase de la confirmada más la tolerancia; si
    pasa, vuelve a pedirla. La «Plataforma de la torre» (cota inicial de la capa, 215 m) creada con su
    contrapendiente confirmada y recalculada por el orden de los nombres de las pruebas: (f1) lo que se
    anota, (f2) la que se reutiliza y (f3) la que se vuelve a pedir."""

    KEY = "counterslope_confirmed"
    LEVEL = design_params.entity_key("PLT-001", "start_level_m")
    TOLERANCE_M = 0.1
    """La tolerancia de contrapendiente por defecto (D-8)."""
    plain_worst: ClassVar[tuple[float, float]]
    first: ClassVar[str]
    created_on: ClassVar[str]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        plain = cls.calculate_in(prep.request(TOWER))
        cls.plain_worst = cls.worst(plain)
        plain.discard()
        cls.clock.advance(minutes=1)
        cls.first = cls.calculate_in(prep.request(TOWER),
                                     confirm_counterslope=True).create().handle.uid
        cls.created_on = timeutil.format_utc(cls.clock.now())

    @staticmethod
    def worst(calculation: Any) -> tuple[float, float]:
        """La contrapendiente de su peor tramo y su abscisa."""
        profile = calculation.outcome.profile
        index = profile.worst
        assert index is not None
        return float(profile.rise_m[index]), float(profile.chainage_m[index])

    def settings_of(self, uid: str) -> dict[str, Any]:
        ((settings,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", uid)
        return dict(json.loads(settings))

    def rise_with(self, level: float) -> float:
        """Cambia la cota inicial de la torre en la versión a ``level`` y da lo que sube su
        contrapendiente así (calculada sin crear)."""
        self.change(self.LEVEL, level)
        calculation = self.calculate_in(prep.request(TOWER), code="PLT-001",
                                        supersedes=self.current("PLT-001"))
        try:
            return self.worst(calculation)[0]
        finally:
            calculation.discard()  # no deja su temporal

    def test_f1_creating_with_the_confirmation_records_what_was_confirmed(self) -> None:
        """RF-015-23: lo confirmado se anota en los ajustes de la operación al crear: la cuantía y la
        abscisa del peor tramo (los del perfil), quién lo confirmó (quien tiene abierto el proyecto) y
        cuándo; una plataforma sin contrapendiente no lleva nada (los ajustes de siempre)."""
        recorded = self.settings_of(self.first)[self.KEY]
        self.assertEqual(sorted(recorded), ["abscissa_m", "amount_m", "decided_by", "decided_on"])
        self.assertEqual((recorded["amount_m"], recorded["abscissa_m"]), self.plain_worst)
        self.assertGreater(recorded["amount_m"], self.TOLERANCE_M)
        self.assertEqual(recorded["decided_by"], self.project.session.user_host)
        self.assertEqual(recorded["decided_on"], self.created_on)
        self.clock.advance(minutes=1)
        free = self.calculate_in(prep.request(LOADING, start=EDGE_HOLE_DATASET),
                                 confirm_counterslope=True).create()
        self.assertNotIn(self.KEY, self.settings_of(free.handle.uid), "sin contrapendiente, nada")
        self.assertEqual(self.settings_of(free.handle.uid), provenance.platform_settings(
            prep.request(LOADING, start=EDGE_HOLE_DATASET), "PLT-002"))

    def test_f2_a_recompute_reuses_the_confirmation_while_the_counter_slope_does_not_grow(self) -> None:
        """RF-015-23, RF-008-26: recalcular la torre sin cambiar nada, o con un cambio que sube la
        contrapendiente menos que la tolerancia (0,1 m), da una operación nueva que sustituye a la
        anterior **sin pedir la confirmación otra vez** y que lleva la **misma** confirmación (la cuantía
        y el decisor de la primera: no se actualiza a la del recálculo); «Recalcular lo obsoleto» tampoco
        la rechaza."""
        confirmed = self.settings_of(self.first)[self.KEY]
        self.clock.advance(minutes=1)
        handle, work = design_store.recompute_run(self.request_for(self.first))
        stored = finish(work)
        self.assertEqual(stored.handle.uid, handle.uid)
        self.assertEqual(self.query("SELECT status, supersedes_uid FROM gb_operation WHERE uid = ?",
                                    handle.uid), [("done", self.first)])
        self.assertEqual(self.settings_of(handle.uid)[self.KEY], confirmed)
        self.assertEqual(self.current("PLT-001"), handle.uid)
        rise = self.rise_with(214.95)  # 5 cm más baja que la de la capa: sube la contrapendiente 5 cm
        self.assertGreater(rise, confirmed["amount_m"])
        self.assertLessEqual(rise, confirmed["amount_m"] + self.TOLERANCE_M)
        self.assertEqual(self.stale_causes(handle.uid), {("parameter_changed", self.LEVEL)})
        self.clock.advance(minutes=1)
        outcome = finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual([result.status for result in outcome.results],
                         [recompute_mod.UnitStatus.DONE])
        (newest,) = outcome.results[0].operations
        self.assertEqual(self.settings_of(newest)[self.KEY], confirmed)
        self.assertEqual(self.current("PLT-001"), newest)
        self.assertEqual(self.recompute_plan(), [])

    def test_f3_a_counter_slope_over_the_confirmed_one_is_asked_again(self) -> None:
        """RF-015-23: si la contrapendiente nueva pasa de la confirmada más la tolerancia, el recálculo
        vuelve a pedir la confirmación (falla con ``des.platform_counter_unconfirmed``, la operación
        vigente no cambia y no queda nada más) y quien la quiere vuelve a «Calcular», la confirma y la
        crea con la cuantía nueva: la que se reutilizará desde entonces."""
        current = self.current("PLT-001")
        confirmed = self.settings_of(current)[self.KEY]
        rise = self.rise_with(212.0)
        self.assertGreater(rise, confirmed["amount_m"] + self.TOLERANCE_M,
                           "el caso: crece más que la tolerancia")
        before = self.written()
        self.clock.advance(minutes=1)
        handle, work = design_store.recompute_run(self.request_for(current))
        with self.assertRaises(messages.DesignError) as caught:
            finish(work)
        self.assertEqual(caught.exception.code, "des.platform_counter_unconfirmed")
        self.assertEqual(self.query("SELECT status, supersedes_uid FROM gb_operation WHERE uid = ?",
                                    handle.uid), [("failed", current)])
        self.assertEqual(self.current("PLT-001"), current)
        after = self.written()
        for key in ("datasets", "parameters", "figures", "tables", "files"):
            self.assertEqual(after[key], before[key], key)
        self.clock.advance(minutes=1)
        again = self.calculate_in(prep.request(TOWER), code="PLT-001", supersedes=current)
        self.assertTrue(again.needs_confirmation)
        again.confirm_counterslope()
        self.clock.advance(minutes=1)
        newest = again.create().handle.uid
        renewed = self.settings_of(newest)[self.KEY]
        self.assertEqual(renewed["amount_m"], rise)
        self.assertGreater(renewed["amount_m"], confirmed["amount_m"])
        self.assertEqual(self.current("PLT-001"), newest)
        self.clock.advance(minutes=1)  # y recalcular ya no la pide
        _handle, work = design_store.recompute_run(self.request_for(newest))
        self.assertEqual(finish(work).handle.op_type, "des.platform")


class RecomputeTest(RecomputeCase):
    """RF-015-02, RF-015-04, RF-015-16, RF-008-24, RF-008-26: P1 (la «Plataforma de carga», del terreno) y
    P2 (la «Plataforma de taller», de la superficie de P1) creadas en V01 y recalculadas, por el orden de
    los nombres de las pruebas: (c1) sin cambiar nada, (c2) con un cambio que no toca la superficie y (e1)
    con uno que sí la toca."""

    first: ClassVar[Any]
    second: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.first = cls.made(prep.request())
        cls.second = cls.made(prep.request(WORKSHOP, start="entity:PLT-001"))

    # --- (c) Recalcular -----------------------------------------------------------------------

    def test_c1_recomputing_repeats_the_platform_with_what_it_was(self) -> None:
        """RF-015-02, RF-008-26: recalcular P1 sin que nada cambie da una operación **nueva** que sustituye a
        la anterior (queda como historia) con los mismos ajustes, entradas, cifras y datos (el mismo hash de
        la superficie, de la tabla y del informe, en su mismo sitio); no escribe los parámetros de la entidad
        (ya están en la versión); la entidad sigue al día con la operación nueva y P2, que consumió su
        superficie, no queda obsoleta."""
        old = self.first.handle.uid
        rows, figures, hashes = self.version_rows(), self.figures_of(old), self.hashes_of(old)
        inputs = self.query("SELECT item_uid, role FROM gb_operation_io WHERE operation_uid = ? "
                            "AND direction = 'in' ORDER BY fid", old)
        ((settings,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", old)
        self.assertEqual(sorted(hashes), sorted((PSF, EPR, PRP)))
        self.clock.advance(minutes=1)
        handle, work = design_store.recompute_run(self.request_for(old))
        stored = finish(work)
        self.assertEqual(stored.handle.uid, handle.uid)
        self.assertEqual(self.query("SELECT op_type, status, supersedes_uid FROM gb_operation "
                                    "WHERE uid = ?", handle.uid),
                         [("des.platform", "done", old)])
        self.assertEqual(self.query("SELECT superseded_by FROM gb_operation WHERE uid = ?", old),
                         [(handle.uid,)])
        self.assertEqual(self.hashes_of(handle.uid), hashes)
        self.assertEqual(self.figures_of(handle.uid), figures)
        self.assertEqual(self.query("SELECT settings FROM gb_operation WHERE uid = ?", handle.uid),
                         [(settings,)])
        self.assertEqual(self.query("SELECT item_uid, role FROM gb_operation_io WHERE "
                                    "operation_uid = ? AND direction = 'in' ORDER BY fid",
                                    handle.uid), inputs)
        self.assertEqual(self.version_rows(), rows, "no escribe los parámetros de la entidad")
        self.assertEqual(self.current("PLT-001"), handle.uid)
        self.assertEqual(self.current("PLT-002"), self.second.handle.uid)
        self.assertEqual(self.stale_causes(self.second.handle.uid), set())
        self.assertEqual(self.recompute_plan(), [])
        self.assertFalse([name for name in self.written()["files"] if ".tmp-" in name])

    def test_c2_a_change_that_leaves_the_surface_as_it_was_clears_the_mark_of_the_next(self) -> None:
        """RF-008-26, RF-015-16: la tolerancia de contrapendiente de P1 cambia: P1 queda obsoleta por ese
        parámetro y P2, que consumió su superficie, también (en cascada). «Recalcular lo obsoleto» repite P1,
        cuya superficie sale **igual** (la tolerancia solo está en su informe, que cambia): P2 se queda sin
        causa y **no se recalcula** (sigue siendo su operación) y no queda nada obsoleto."""
        key = design_params.entity_key("PLT-001", "counter_tol_m")
        first, second = self.current("PLT-001"), self.current("PLT-002")
        before = self.hashes_of(first)
        self.change(key, 0.25)
        self.assertEqual(self.stale_causes(first), {("parameter_changed", key)})
        self.assertIn(("parameter_changed", key), self.stale_causes(second))
        self.assertEqual(self.plan_units(), [(first,), (second,)])
        self.clock.advance(minutes=1)
        outcome = finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual([(result.status, len(result.operations)) for result in outcome.results],
                         [(recompute_mod.UnitStatus.DONE, 1)])
        (made,) = outcome.results[0].operations
        after = self.hashes_of(made)
        self.assertEqual(after[PSF], before[PSF], "la superficie es la misma")
        self.assertEqual(after[EPR], before[EPR])
        self.assertNotEqual(after[PRP], before[PRP], "el informe lleva la tolerancia")
        self.assertEqual(self.rows_of(PRP_TABLE)["counter_tolerance_m"][0][:2], (0.25, "m"))
        self.assertEqual(self.current("PLT-001"), made)
        self.assertEqual(self.current("PLT-002"), second, "P2 no se recalculó")
        self.assertEqual(self.stale_causes(second), set())
        self.assertEqual(self.recompute_plan(), [])

    def test_c5_recomputing_uses_the_parameters_of_the_version_and_not_the_layer(self) -> None:
        """RF-015-01, RF-015-02, RF-015-16 (P-3): la cota inicial de la rasante se copió de la capa a la
        entidad al crearla (250 m) y es un parámetro de su versión con su historial: cambiada en la versión
        (248 m), P1 queda obsoleta por ella y recalcular la usa (el informe y la cifra, a 248 m) **aunque la
        capa siga diciendo 250**, que no se toca (el mismo registro y el mismo contenido); la superficie
        baja, la de P2 la sigue y la geometría de origen es la misma."""
        key = design_params.entity_key("PLT-001", "start_level_m")
        first, second = self.current("PLT-001"), self.current("PLT-002")
        layers = self.layers()
        sha = self.hashes_of(first)
        self.change(key, 248.0)
        self.assertEqual(self.stale_causes(first), {("parameter_changed", key)})
        self.clock.advance(minutes=1)
        outcome = finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual([result.status for result in outcome.results],
                         [recompute_mod.UnitStatus.DONE] * 2)
        (new_first,), (new_second,) = (result.operations for result in outcome.results)
        self.assertEqual(self.rows_of(PRP_TABLE)["start_level_m"][0][:2], (248.0, "m"))
        self.assertEqual(self.figures_of(new_first)[("des.plat_start_level_m", figures_mod.scope_json(
            provenance.entity_figure_scope(LOADING, "PLT-001")))], 248.0)
        self.assertEqual(self.layers(), layers, "la capa no se toca (sigue diciendo 250 m)")
        after = self.hashes_of(new_first)
        self.assertNotEqual(after[PSF], sha[PSF])
        self.assertEqual(after[EPR], sha[EPR], "la huella y el eje son los mismos")
        self.assertNotEqual(self.hashes_of(new_second)[PSF2], self.hashes_of(second)[PSF2])
        self.assertEqual(self.recompute_plan(), [])
        self.assertEqual((self.current("PLT-001"), self.current("PLT-002")), (new_first, new_second))
        self.assertNotEqual(first, new_first)

    # --- (e) La cascada de la cadena -------------------------------------------------------------

    def test_e1_changing_the_first_stales_the_next_and_recomputing_goes_in_dependency_order(self) -> None:
        """RF-015-16, RF-008-24, RF-008-26: se vuelve a registrar la operación de P1 (queda **después** de la
        de P2) y se cambia el alcance de P1 (``reach_m``): P1 queda obsoleta por ese parámetro y P2 con la
        misma causa (``parameter_changed`` de la clave de **P1**, no de P2). El plan de «Recalcular lo
        obsoleto» las pone en orden de dependencia, P1 y P2 (no en el de registro, que es P2 y P1), y
        recalculadas cada una sustituye a la suya: P1 usa el alcance nuevo (de su fila de la versión, no de la
        capa), la superficie de P2 sigue a la de P1 fuera de su ventana y nada queda obsoleto."""
        reach = design_params.entity_key("PLT-001", "reach_m")
        self.clock.advance(minutes=1)
        recompute_function(self.request_for(self.current("PLT-001")))
        first, second = self.current("PLT-001"), self.current("PLT-002")
        order = dict(self.query("SELECT uid, fid FROM gb_operation WHERE uid IN (?, ?)",
                                first, second))
        self.assertGreater(order[first], order[second], "P1 se registró después que P2")
        self.assertEqual((self.stale_causes(first), self.stale_causes(second)), (set(), set()))
        surfaces = (self.hashes_of(first)[PSF], self.hashes_of(second)[PSF2])
        self.change(reach, 25.0)
        self.assertEqual(self.stale_causes(first), {("parameter_changed", reach)})
        self.assertIn(("parameter_changed", reach), self.stale_causes(second))
        self.assertNotIn(("parameter_changed", design_params.entity_key("PLT-002", "reach_m")),
                         self.stale_causes(second))
        self.assertEqual(self.plan_units(), [(first,), (second,)])
        self.clock.advance(minutes=1)
        outcome = finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual([result.status for result in outcome.results],
                         [recompute_mod.UnitStatus.DONE] * 2)
        (new_first,), (new_second,) = (result.operations for result in outcome.results)
        self.assertEqual(self.query("SELECT supersedes_uid FROM gb_operation WHERE uid IN (?, ?) "
                                    "ORDER BY fid", new_first, new_second), [(first,), (second,)])
        self.assertEqual((self.current("PLT-001"), self.current("PLT-002")), (new_first, new_second))
        self.assertEqual(self.rows_of(PRP_TABLE)["edge_reach_m"][0][:2], (25.0, "m"))
        self.assertNotEqual(self.hashes_of(new_first)[PSF], surfaces[0])
        self.assertNotEqual(self.hashes_of(new_second)[PSF2], surfaces[1], "P2 sigue a P1")
        ((bounds,),) = self.query(
            f'SELECT bounds FROM "{provenance.dataset_locator("epr", WORKSHOP, "V01")}"')
        row0, row1, col0, col1 = json.loads(bounds)
        outside = np.ones(GRID.shape, dtype=bool)
        outside[row0:row1, col0:col1] = False
        np.testing.assert_array_equal(self.grid_of(PSF2)[outside], self.grid_of(PSF)[outside])
        self.assertEqual(self.recompute_plan(), [])
        self.assertEqual((self.stale_causes(new_first), self.stale_causes(new_second)), (set(), set()))
        entry = entities_module.registry(self.project, self.v1.uid).get("PLT-001")
        self.assertEqual(str(entry.record.state), "current")


class ObsoleteTest(ObsoleteCase):
    """RF-015-03 (RF-015-16, RF-015-05): lo que quedará obsoleto al crear la entidad."""

    def test_a_a_platform_that_protects_makes_the_masks_and_what_used_them_obsolete(self) -> None:
        """RF-015-03, RF-015-10, RF-015-16: al crear una plataforma que protege su huella (con su
        resguardo), quedan obsoletas las máscaras de la versión y lo que las usó (la cantera y su
        transición, por su nombre y su tipo: del grafo de la 008); el resumen lo dice en dos notas, la
        segunda con la cuenta y los nombres."""
        calculation = self.calculate(prep.request(start="gis_dtm_borde", protect=True,
                                                  guard_m=4.0))
        summary = calculation.summary
        self.assertEqual(summary.obsolete[0].kind, preview.ObsoleteKind.MASKS)
        self.assertEqual(summary.obsolete[0].name, "V01")
        consumers = {(item.name, item.op_type, item.uid) for item in summary.obsolete
                     if item.kind is preview.ObsoleteKind.CONSUMER}
        self.assertEqual(consumers, {
            (self.QUARRY, "des.quarry", self.quarry.handle.uid),
            (self.TRANSITION, "des.edge_transition", self.transition.handle.uid)})
        masks = only(summary, "des.entity_obsolete_masks")
        self.assertEqual((masks.values["entity"], masks.values["version"]), (LOADING, "V01"))
        used = only(summary, "des.entity_obsolete_consumers")
        self.assertEqual(used.values["operations"], 2)
        self.assertIn(f"«{self.QUARRY}»", used.text("es"))
        self.assertIn(f"«{self.TRANSITION}»", used.text("es"))
        self.assertEqual(calculation.entity.values["protect"], True)
        self.assertEqual(len(summary.obsolete), 3)

    def test_a_a_platform_that_does_not_protect_makes_nothing_obsolete(self) -> None:
        """RF-015-03: sin proteger, ni las máscaras ni lo que las usó quedan obsoletos y el resumen no
        dice nada de lo obsoleto."""
        summary = self.calculate(prep.request(start="gis_dtm_borde")).summary
        self.assertEqual(summary.obsolete, ())
        self.assertFalse([code for code in codes(summary) if "obsolete" in code])

    def test_a_a_single_consumer_takes_its_singular(self) -> None:
        """RF-015-03 (spec 014, T60): lo que quedaría obsoleto por una sola operación se dice en
        singular, con el número sin escribir: «1 operación», no «1 operaciones»."""
        one = (preview.Obsolete(preview.ObsoleteKind.CONSUMER, self.QUARRY, "des.quarry", "u1"),)
        notices = preview.obsolete_notices(LOADING, "V01", one)
        self.assertEqual([n.code for n in notices], ["des.entity_obsolete_consumers"])
        self.assertIn("Con ellas quedará obsoleta 1 operación", notices[0].text("es"))
        self.assertIn("With them, 1 operation", notices[0].text("en"))

    def test_a_an_insertion_makes_the_successor_and_the_ones_after_it_obsolete(self) -> None:
        """RF-015-03, RF-015-05: una plataforma que se inserta antes de P2 (parte de su misma
        superficie, el terreno) deja obsoletas P2 y las que le siguen (P3 y P4): el resumen las lista;
        P5, sin calcular, no (no tiene nada que quedar obsoleto); y sin ``insert_before`` el mismo
        cálculo se rechaza (de cada superficie parte una sola)."""
        with self.assertRaises(messages.DesignError) as caught:
            finish(self.run_steps(prep.request()))
        self.assertEqual(caught.exception.code, "des.entity_start_taken")
        summary = self.calculate(prep.request(), insert_before="P2").summary
        self.assertEqual([(item.kind, item.name) for item in summary.obsolete],
                         [(preview.ObsoleteKind.SUCCESSOR, "P2"),
                          (preview.ObsoleteKind.SUCCESSOR, "P3"),
                          (preview.ObsoleteKind.SUCCESSOR, "P4")])
        self.assertEqual([item.uid for item in summary.obsolete],
                         [self.chain["P2"], self.chain["P3"], self.chain["P4"]])
        text = only(summary, "des.entity_obsolete_successor")
        self.assertEqual((text.values["entities"], text.values["entity"]), (3, LOADING))
        self.assertNotIn("des.entity_obsolete_masks", codes(summary))

    def test_a_an_insertion_is_checked_like_any_chain(self) -> None:
        """RF-015-04, RF-015-05: ``insert_before`` solo vale con la entidad que parte de la misma
        superficie (P3 parte de la de P2, no del terreno: error del programa) y con una que no existe
        también; sin él, una superficie libre se calcula sin problema y sin nada obsoleto."""
        with self.assertRaises(ValueError):
            finish(self.run_steps(prep.request(), insert_before="P3"))
        with self.assertRaises(ValueError):
            finish(self.run_steps(prep.request(), insert_before="P9"))
        free = self.calculate(prep.request(start=provenance.dataset_name("fin", self.QUARRY)))
        self.assertEqual(free.summary.obsolete, ())

    def test_a_what_depends_on_the_operation_it_replaces(self) -> None:
        """RF-015-03, RF-008-26: si la nueva sustituye a una operación, lo que dependía de ella (lo que
        consume lo que escribió: la transición, de la superficie final de la cantera) queda obsoleto;
        la propia operación no, y una operación de la que nada depende no deja nada. Lo da
        ``platform_obsolete`` sobre el grafo."""
        prepared = self.units(prep.request(start="gis_dtm_borde"))
        found = entity_store.platform_obsolete(self.project, self.v1, prepared, self.masks_v1,
                                               supersedes=self.quarry.handle.uid)
        self.assertEqual([(item.kind, item.name, item.uid) for item in found],
                         [(preview.ObsoleteKind.DEPENDENT, self.TRANSITION,
                           self.transition.handle.uid)])
        notices = preview.obsolete_notices(LOADING, "V01", found)
        self.assertEqual([n.code for n in notices], ["des.entity_obsolete_dependents"])
        self.assertIn("quedará obsoleta 1 operación", notices[0].text("es"))
        self.assertEqual(entity_store.platform_obsolete(
            self.project, self.v1, prepared, self.masks_v1,
            supersedes=self.transition.handle.uid), ())

    def test_a_the_cascade_goes_as_far_as_the_chain_does(self) -> None:
        """RF-015-03, RF-015-16, RF-008-24: sustituir la operación de P2 deja obsoletas la de P3, que
        consumió su superficie, y en cascada la de P4, que consumió la de P3 (no P2 ni P5, que no tiene
        operación ni consumió nada)."""
        prepared = self.units(prep.request(start="gis_dtm_borde"))
        found = entity_store.platform_obsolete(self.project, self.v1, prepared, self.masks_v1,
                                               supersedes=self.chain["P2"])
        self.assertEqual([(item.kind, item.name, item.uid) for item in found],
                         [(preview.ObsoleteKind.DEPENDENT, "P3", self.chain["P3"]),
                          (preview.ObsoleteKind.DEPENDENT, "P4", self.chain["P4"])])
        last = entity_store.platform_obsolete(self.project, self.v1, prepared, self.masks_v1,
                                              supersedes=self.chain["P4"])
        self.assertEqual(last, ())

    def test_a_what_the_replaced_operation_used_is_not_counted_with_the_masks(self) -> None:
        """RF-015-03: si la nueva protege y sustituye la operación de la cantera, que también usó las
        máscaras, la sustituida no cuenta entre lo que queda obsoleto (se rehace, no se invalida); sí la
        transición, que usó las máscaras y, además, dependía de la cantera: una sola vez."""
        prepared = self.units(prep.request(start="gis_dtm_borde", protect=True, guard_m=4.0))
        found = entity_store.platform_obsolete(self.project, self.v1, prepared, self.masks_v1,
                                               supersedes=self.quarry.handle.uid)
        self.assertEqual([(item.kind, item.uid) for item in found],
                         [(preview.ObsoleteKind.MASKS, self.masks_v1.operation_uid),
                          (preview.ObsoleteKind.CONSUMER, self.transition.handle.uid)])

    # --- RF-015-14: el orden de la cantera ----------------------------------------------------

    def test_a_a_platform_over_the_final_surface_above_the_exploitation_warns(self) -> None:
        """RF-015-14: una plataforma «en corte y relleno» a 330 m sobre la superficie final de la
        cantera la sube por encima de la de explotación: el resumen avisa con la cantera, las dos
        superficies, el área y el lugar, y no impide crearla (ni pide confirmación por ello)."""
        final = provenance.dataset_name("fin", self.QUARRY)
        exploitation = provenance.dataset_name("exp", self.QUARRY)
        asked = prep.request("Alta", fields=prep.line_fields(self.HIGH_LAYER), start=final,
                             mode="cut_fill")
        calculation = self.calculate(asked)
        order = only(calculation.summary, "des.entity_quarry_order")
        self.assertEqual((order.values["quarry"], order.values["surface"], order.values["other"]),
                         (self.QUARRY, final, exploitation))
        outcome = calculation.outcome
        self.assertIsNotNone(outcome.order)
        self.assertEqual(order.values["area"], outcome.order.area_m2)
        self.assertGreater(order.values["area"], 0.0)
        other = geotiff_reader.read_geotiff(
            self.root / self.record(exploitation, self.v1).locator).values
        expected = platform.order_check(outcome.result, other, "final", GRID,
                                        outcome.footprint.window)
        self.assertEqual(expected.cells, outcome.order.cells)
        self.assertFalse(calculation.needs_confirmation)

    def test_a_a_surface_that_is_not_of_a_quarry_does_not_warn(self) -> None:
        """RF-015-14: sobre el terreno (que no es de una cantera) no hay otra superficie con la que
        comparar y no se avisa."""
        calculation = self.calculate(prep.request(start="gis_dtm_borde"))
        self.assertIsNone(calculation.outcome.order)
        self.assertNotIn("des.entity_quarry_order", codes(calculation.summary))


class AtomicCreateTest(CreateCase):
    """RF-015-02, RF-015-29: si algo falla a mitad de «Crear», no queda nada: ni operación, ni datos, ni
    tablas, ni cifras, ni parámetros, ni la superficie en su sitio, ni el temporal."""

    def test_b_a_failure_midway_leaves_nothing(self) -> None:
        """Un fallo simulado al abrir la operación (con los parámetros de la entidad ya escritos en la
        transacción), al escribir las tablas (con la superficie ya en su sitio) y al completar (con todo
        hecho menos confirmar) deja el proyecto como antes de calcular, el error sigue y la cuenta queda
        cerrada; calculada y creada otra vez sin el fallo, se registra con el mismo código."""
        clean = self.written()
        failures = (
            ("abrir la operación", mock.patch.object(design_store.OperationStart, "begin",
                                                     side_effect=RuntimeError("fallo de prueba"))),
            ("escribir las tablas", mock.patch.object(design_store.DesignWriter, "_write_table",
                                                      side_effect=RuntimeError("fallo de prueba"))),
            ("completar", mock.patch.object(operations.OperationHandle, "complete",
                                            side_effect=RuntimeError("fallo de prueba"))))
        for step, patched in failures:
            with self.subTest(step=step):
                calculation = self.calculate_in(prep.request())
                self.assertNotEqual(self.written()["files"], clean["files"], "el temporal")
                with patched:
                    with self.assertRaises(RuntimeError) as caught:
                        calculation.create()
                self.assertEqual(str(caught.exception), "fallo de prueba")
                self.assertEqual(self.written(), clean)
                self.assertFalse(calculation.open)
        self.clock.advance(minutes=1)
        stored = self.calculate_in(prep.request()).create()
        entry = entities_module.registry(self.project, self.v1.uid).get("PLT-001")
        self.assertEqual(entry.operation_uid, stored.handle.uid)


class CalculateTest(OperationCase):
    """RF-015-03 y RF-015-29 con proyecto: «Calcular» deja el temporal y el resumen, y nada más."""

    def test_a_calculating_writes_nothing_and_leaves_the_surface_in_a_temporary(self) -> None:
        """RF-015-03, RF-015-29: tras «Calcular», ni el contador de cambios de la base (ninguna
        transacción de escritura), ni las operaciones, los datos o los parámetros se han movido; solo
        hay un fichero más, el temporal de la superficie (``des_psf_…``) con su hash preparado. Lo
        escrito es la partida fuera de lo que mueve la plataforma y su resultado dentro, y en «en
        corte» ninguna celda sube: el corte de las celdas es el de la cuenta."""
        before = self.state()
        calculation = self.calculate(prep.request())
        after = self.state()
        for key in ("counter", "operations", "datasets", "parameters"):
            self.assertEqual(after[key], before[key], key)
        stem = provenance.dataset_locator("psf", LOADING, "V01").rsplit("/", 1)[-1]
        (temporary,) = sorted(set(after["files"]) - set(before["files"]))
        self.assertRegex(temporary, rf"^{re.escape(stem)}\.tmp-[0-9a-f]+$")
        self.assertEqual((calculation.op_type, calculation.name, calculation.version),
                         ("des.platform", LOADING, "V01"))
        self.assertTrue(calculation.open)
        self.assertEqual([spec.name for spec in calculation.specs],
                         [provenance.dataset_name(family, LOADING)
                          for family in ("psf", "epr", "prp")])
        self.assertTrue(all(spec.content is not None for spec in calculation.specs),
                        "las tres salidas llevan ya su hash")
        self.assertEqual(calculation.entity.code, "PLT-001")
        outcome = calculation.outcome
        self.assertIsInstance(outcome, platform.PlatformOutcome)
        self.assertEqual(calculation.message, outcome.message)
        written = geotiff_reader.read_geotiff(self.root / "rasters" / temporary).values
        start = qfx.terrain(GRID)
        expected = start.copy()
        expected[outcome.footprint.window] = outcome.result
        np.testing.assert_array_equal(written, expected)
        self.assertTrue((written <= start).all(), "«en corte» no sube ninguna celda")
        self.assertAlmostEqual(float(np.sum(start - written)) * CELL_M2, outcome.total_cut_m3,
                               delta=1e-9 * outcome.total_cut_m3)
        self.assertEqual({figure.key: figure.value for figure in calculation.figures
                          if figure.key == "des.plat_area_m2"}, {"des.plat_area_m2": 4000.0})
        self.assertEqual(self.units(prep.request()).start.inputs, calculation.entity.start.inputs)

    def test_a_the_steps_advance_with_progress_and_end_with_the_calculation(self) -> None:
        """RF-015-29: «Calcular» da pasos de ``Progress`` (fase, avance y texto) y el último lleva la
        ``Calculation``; con un presupuesto mínimo, muchos; cada fase de lo pesado tiene el suyo."""
        found = list(self.run_steps(prep.request(), budget_s=1e-9))
        self.addCleanup(found[-1].result.discard)
        phases = [step.phase for step in found]
        for phase in ("prepare", "platform_apply", "platform_edge", "store", "calculated"):
            self.assertIn(phase, phases)
        self.assertEqual(phases[-1], "calculated")
        self.assertTrue(all(step.result is None for step in found[:-1]))
        self.assertGreater(len(found), 12)
        self.assertTrue(all(step.message for step in found))

    def test_a_closing_the_steps_midway_leaves_nothing(self) -> None:
        """RF-015-29: cerrar «Calcular» (Esc, desactivar Geoblender) con la superficie ya en su
        temporal borra el temporal y no deja nada: el estado del proyecto es el de antes."""
        before = self.state()
        work = self.run_steps(prep.request(), budget_s=1e-9)
        for step in work:
            if step.phase == "store" and self.temporaries():
                break
        else:
            self.fail("no llegó a escribir el temporal")
        self.assertEqual(len(self.temporaries()), 1)
        work.close()
        self.assertEqual(self.state(), before)

    def test_a_closing_at_the_first_step_leaves_nothing(self) -> None:
        """RF-015-29: cerrar al empezar tampoco deja nada."""
        before = self.state()
        work = self.run_steps(prep.request(), budget_s=1e-9)
        next(work)
        work.close()
        self.assertEqual(self.state(), before)

    def test_a_a_failure_after_the_temporary_leaves_nothing(self) -> None:
        """RF-015-29: si algo falla después de escribir el temporal (aquí, al armar el resumen), el
        error sigue y no queda ni el temporal ni nada en el proyecto."""
        before = self.state()
        with mock.patch.object(entity_store, "platform_obsolete",
                               side_effect=RuntimeError("fallo de prueba")):
            with self.assertRaises(RuntimeError):
                finish(self.run_steps(prep.request(), budget_s=1e-9))
        self.assertEqual(self.state(), before)

    def test_a_the_refusals_come_when_advancing_and_leave_nothing(self) -> None:
        """RF-015-29, RF-015-08, RF-009-21: un rechazo de la preparación (el alcance sin valor, un
        nombre ya usado por otra operación), sin versión o con una que no existe sale al avanzar y no
        deja nada."""
        before = self.state()
        with self.assertRaises(messages.DesignError) as caught:
            finish(self.run_steps(prep.request(reach_m=None)))
        self.assertEqual(caught.exception.code, "des.entity_param_missing")
        for version, code in ((None, "core.version_required"), ("V99", "core.version_unknown")):
            with self.subTest(version=version):
                with self.assertRaises(prep.versions_model.VersionError) as found:
                    finish(self.run_steps(prep.request(), version=version, masks=None))
                self.assertEqual(found.exception.code, code)
        self.assertEqual(self.state(), before)

    def test_a_discarding_deletes_the_temporary_and_a_calculation_is_a_context(self) -> None:
        """RF-015-03: «Cancelar» borra el temporal (y no hace nada la segunda vez); como gestor de
        contexto, al salir sin crear descarta."""
        before = self.state()
        calculation = finish(self.run_steps(prep.request()))
        self.assertEqual(len(self.temporaries()), 1)
        calculation.discard()
        calculation.discard()
        self.assertFalse(calculation.open)
        self.assertEqual(self.state(), before)
        with finish(self.run_steps(prep.request())) as inside:
            self.assertTrue(inside.open)
            self.assertEqual(len(self.temporaries()), 1)
        self.assertEqual(self.state(), before)

    def test_a_the_counter_slope_is_confirmed_on_the_calculation(self) -> None:
        """RF-015-23 (T09, la orden de T15): una plataforma con contrapendiente pide confirmación
        (``needs_confirmation``); confirmarla en la cuenta (``confirm_counterslope``) o pedirla ya
        confirmada (``confirm_counterslope=True``) lo da por hecho, sin recalcular."""
        plain = self.calculate(prep.request(TOWER))
        self.assertTrue(plain.outcome.counter_slope)
        self.assertTrue(plain.needs_confirmation)
        outcome = plain.outcome
        plain.confirm_counterslope()
        self.assertFalse(plain.needs_confirmation)
        self.assertTrue(plain.outcome.confirmed)
        self.assertIs(plain.outcome.footprint, outcome.footprint)
        asked = self.calculate(prep.request(TOWER), confirm_counterslope=True)
        self.assertFalse(asked.needs_confirmation)
        self.assertTrue(self.calculate(prep.request()).outcome.counter_slope is False)


class FrozenConsumersTest(ObsoleteCase):
    """RF-015-16 (RF-009-19): lo que **está en** una revisión congelada no cambia ni se marca (sus elementos),
    pero lo **vigente** de la versión, aunque lo registrara una revisión que luego se congeló, sigue siendo lo
    vigente y el grafo de la 008 lo marca obsoleto en la revisión abierta («en curso», D-23 de la 009): el resumen
    de lo que quedará obsoleto lo cuenta (T27: antes filtraba por ``r.state = 'open'`` y tras congelar daba
    ``[]``, y avisaba de menos)."""

    def test_a_what_is_live_in_a_frozen_revision_is_counted_with_what_will_be_obsolete(self) -> None:
        """RF-015-16, RF-015-03, RF-009-19 (T27; cambia lo que describía la T12: «la cantera y su transición no
        salen»): tras congelar V01, la cantera y su transición siguen siendo las operaciones vigentes de la
        versión —la 008 las marcaría obsoletas si cambiaran las máscaras— y salen entre lo que quedará obsoleto,
        con las máscaras de la versión."""
        with self.project.write_transaction() as conn:
            freeze_rows(conn, self.v1, now=self.clock.now().isoformat(timespec="seconds"),
                        reason="Siguiente")
        calculation = self.calculate(prep.request(start="gis_dtm_borde", protect=True,
                                                  guard_m=4.0))
        found = calculation.summary.obsolete
        self.assertEqual(found[0].kind, preview.ObsoleteKind.MASKS)
        self.assertEqual({(item.kind, item.name, item.uid) for item in found[1:]},
                         {(preview.ObsoleteKind.CONSUMER, self.QUARRY, self.quarry.handle.uid),
                          (preview.ObsoleteKind.CONSUMER, self.TRANSITION, self.transition.handle.uid)})
        used = only(calculation.summary, "des.entity_obsolete_consumers")
        self.assertEqual(used.values["operations"], 2)

    def test_b_what_depends_on_an_entity_after_freezing_is_still_counted(self) -> None:
        """RF-015-16, RF-015-03, RF-008-24 (T27): congelada V01, sustituir la operación de una entidad (P2) sigue
        dejando obsoletas las que consumieron su superficie, P3 y, en cascada, P4, que están en la revisión
        congelada y son lo vigente (antes de congelar daba ese mismo resultado: ``test_a_the_cascade_goes_as_far_
        as_the_chain_does``)."""
        prepared = self.units(prep.request(start="gis_dtm_borde"))
        found = entity_store.platform_obsolete(self.project, self.v1, prepared, self.masks_v1,
                                               supersedes=self.chain["P2"])
        self.assertEqual([(item.kind, item.name, item.uid) for item in found],
                         [(preview.ObsoleteKind.DEPENDENT, "P3", self.chain["P3"]),
                          (preview.ObsoleteKind.DEPENDENT, "P4", self.chain["P4"])])


class RecomputeRefusalTest(RecomputeCase):
    """RF-015-02, RF-013-17 (``des.input_changed``): lo que impide registrar un recálculo, con P1 creada."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())

    def test_c3_a_dataset_that_changes_before_it_starts_is_not_registered(self) -> None:
        """RF-013-04, RF-013-17: si la superficie de partida cambia entre que se prepara el recálculo y que la
        operación nueva empieza, el resultado no le corresponde: ``des.input_changed`` al empezar (con el
        dato), la operación nueva queda fallida, la anterior sigue vigente sin sustituir y no queda ningún
        temporal."""
        old = self.current("PLT-001")
        real = design_store.OperationStart.begin
        shifted = gis.Raster(GRID, qfx.terrain(GRID) + 1.0, efx.CRS, efx.VERTICAL)

        def racing(start: Any, project: Any, **options: Any) -> Any:
            self.clock.advance(minutes=1)
            res_fixtures.write_grids(self.project, [(START.removeprefix("gis_dtm_"), shifted)],
                                     message="La partida cambia justo antes de empezar")
            return real(start, project, **options)

        self.clock.advance(minutes=1)
        with mock.patch.object(design_store.OperationStart, "begin", racing):
            with self.assertRaises(messages.DesignError) as caught:
                design_store.recompute_run(self.request_for(old))
        self.assertEqual(caught.exception.code, "des.input_changed")
        self.assertIn(START, caught.exception.text)
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE supersedes_uid = ?", old),
                         [("failed",)])
        self.assertEqual(self.query("SELECT superseded_by FROM gb_operation WHERE uid = ?", old),
                         [(None,)])
        self.assertEqual(self.current("PLT-001"), old)
        self.assertFalse([name for name in self.written()["files"] if ".tmp-" in name])

    def test_c3_a_parameter_that_changes_before_it_starts_is_not_registered(self) -> None:
        """RF-013-17, RF-015-16: si el alcance de P1 cambia entre que se prepara el recálculo y que la
        operación nueva empieza (y anota los valores que lee), el cálculo no le corresponde: al avanzar,
        ``des.input_changed`` con el parámetro, la operación nueva queda fallida y la anterior, vigente, sin
        sustituir."""
        old = self.current("PLT-001")
        reach = design_params.entity_key("PLT-001", "reach_m")
        real = design_store.OperationStart.begin

        def racing(start: Any, project: Any, **options: Any) -> Any:
            self.change(reach, 26.0)  # cambia justo antes de empezar
            return real(start, project, **options)

        self.clock.advance(minutes=1)
        with mock.patch.object(design_store.OperationStart, "begin", racing):
            handle, work = design_store.recompute_run(self.request_for(old))
        with self.assertRaises(messages.DesignError) as caught:
            finish(work)
        self.assertEqual(caught.exception.code, "des.input_changed")
        self.assertIn(reach, caught.exception.text)
        self.assertEqual(self.query("SELECT status, supersedes_uid FROM gb_operation WHERE uid = ?",
                                    handle.uid), [("failed", old)])
        self.assertEqual(self.query("SELECT superseded_by FROM gb_operation WHERE uid = ?", old),
                         [(None,)])
        self.assertEqual(self.current("PLT-001"), old)
        self.assertFalse([name for name in self.written()["files"] if ".tmp-" in name])


class ChangedMeanwhileTest(CreateCase):
    """RF-015-02, RF-013-04 (``des.input_changed``): lo que cambia entre «Calcular» y «Crear» (nada se
    registra, así que cada prueba puede calcular la misma plataforma)."""

    def test_b_an_input_that_changed_meanwhile_is_not_registered(self) -> None:
        """RF-015-02, RF-013-04 (``des.input_changed``): si la superficie de partida cambia entre «Calcular» y
        «Crear», el resultado ya no le corresponde: se rechaza **al abrir la operación, ya con los
        parámetros de la entidad escritos**, y todo se deshace."""
        clean = self.written()
        calculation = self.calculate_in(prep.request())
        shifted = gis.Raster(GRID, qfx.terrain(GRID) + 1.0, efx.CRS, efx.VERTICAL)
        self.clock.advance(minutes=1)
        res_fixtures.write_grids(self.project, [(START.removeprefix("gis_dtm_"), shifted)],
                                 message="La partida cambia mientras se calcula")
        changed = self.written()
        self.assertNotEqual(changed["datasets"], clean["datasets"], "la partida cambió")
        self.assertEqual(changed["parameters"], clean["parameters"])
        with self.assertRaises(messages.DesignError) as caught:
            calculation.create()
        self.assertEqual(caught.exception.code, "des.input_changed")
        self.assertIn(START, caught.exception.text)
        self.assertEqual(self.written(), self.settled(changed))
        self.assertFalse(calculation.open)

    def test_b_a_parameter_that_changed_meanwhile_is_not_registered(self) -> None:
        """RF-015-02 (``des.input_changed``): lo mismo con un parámetro del proyecto que lee el cálculo
        (el umbral de aviso de magnitud): se rechaza antes de escribir nada y el temporal se borra."""
        clean = self.written()
        calculation = self.calculate_in(prep.request())
        self.clock.advance(minutes=1)
        key = design_params.WARNING_RATIO
        with self.project.write_transaction() as conn:
            store = core_params.ParameterStore(self.project)
            store.ensure_default(conn, key, geoblender_version="0.1.0")
            store.change(conn, key, value=3.0, reason="Prueba de la T13", source="Prueba",
                         source_kind="person", decided_by=prep.USER)
        changed = self.written()
        self.assertNotEqual(changed["parameters"], clean["parameters"], "el parámetro cambió")
        with self.assertRaises(messages.DesignError) as caught:
            calculation.create()
        self.assertEqual(caught.exception.code, "des.input_changed")
        self.assertIn(key, caught.exception.text)
        self.assertEqual(self.written(), self.settled(changed))
        self.assertFalse(calculation.open)
