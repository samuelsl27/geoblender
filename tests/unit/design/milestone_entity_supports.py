# SPDX-License-Identifier: GPL-3.0-or-later
"""Pruebas de hito de «test_entity_supports» (spec 015, T48; plan 015 §7.4): las clases que pesan,
movidas sin cambiar una aserción. El «verde» deja en ``test_entity_supports`` las más ligeras de cada
requisito; las de aquí las ejecuta el paso «hito» de ``tools/check.py --completo`` (la publicación
lo pide siempre).
"""

from __future__ import annotations

import json
from typing import Any, ClassVar
from unittest import mock

import numpy as np

from tests.support import quarry_fixtures as qfx
from tests.support.versions_fixtures import change_counter, files
from tests.unit.design import test_fill_only_operation as fill_test
from tests.unit.design import test_platform_prepare as prep
from tests.unit.design.test_entity_supports import (
    BALSA,
    DRAG,
    DesignError,
    EPR1,
    FillOnlyCase,
    OVER,
    OVER_VOLUME_M3,
    PSF1,
    SupportsCase,
    THICKNESS_M,
    ThicknessCase,
    WORKSHOP,
    asked,
    core_params,
    design_params,
    design_store,
    entities,
    entity_store,
    figures_mod,
    finish,
    freeze,
    model,
    over,
    provenance,
    recompute_mod,
    reproduce_mod,
)


class DeclaredSupportsTest(SupportsCase):
    """RF-015-15, D-11: lo que la persona **declara** (``des.platform.{e}.supports``) se registra aunque no apoye
    nada; lo que no existe, es ella misma o sería un ciclo se rechaza sin escribir nada. P1 (la de carga),
    P2 (sobre ella: parte de su superficie) y P3 (el taller, de otro terreno y lejos de las demás)."""

    workshop: ClassVar[Any]
    WORKSHOP_KEY: ClassVar[str] = design_params.entity_key("PLT-003", "supports")

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())
        cls.made(over())
        cls.workshop = cls.made(prep.request(WORKSHOP, start=prep.HOLE_DATASET))

    @classmethod
    def declare(cls, code: str, text: str) -> None:
        """Declara en la versión que la entidad ``code`` se apoya en ``text`` (códigos separados por comas)."""
        cls.clock.advance(minutes=1)
        key = design_params.entity_key(code, "supports")
        store = core_params.ParameterStore(cls.project)
        with cls.project.write_transaction() as conn:
            if store.get(key, version=cls.v1.uid, conn=conn) is None:
                store.create(conn, key, text, kind="ADOPTADO", source="Prueba de la T23",
                             source_kind="person", decided_by="Samuel (IMGA)",
                             reason="Dependencia declarada", version=cls.v1.uid)
            else:
                store.change(conn, key, value=text, version=cls.v1.uid, reason="Prueba de la T23")

    def refused(self, code: str, text: str, target: str, reason: str) -> None:
        """Declarar ``text`` en ``code`` y recalcularla se rechaza (``des.entity_supports_unknown``, con la
        entidad a la que apunta y el motivo) **sin escribir nada**."""
        self.declare(code, text)
        before = self.written()
        uid = self.current(code)
        with self.assertRaises(DesignError) as caught:
            design_store.recompute_run(self.request_for(uid))
        self.assertEqual(caught.exception.code, "des.entity_supports_unknown")
        self.assertEqual(caught.exception.values["target"], target)
        self.assertIn(reason, caught.exception.values["reason"])
        self.assertIn(target, caught.exception.text)
        self.assertEqual(self.written(), before)

    def test_c_a_declared_dependency_is_registered_with_zero_cubic_metres(self) -> None:
        """RF-015-15, D-11, CE-015-01 («detectada y declarada»): el taller declara que se apoya en P1, con la
        que no comparte ni un metro de huella: al recalcularlo se registra la dependencia (la superficie y
        la huella de P1 como entradas) y la cifra **con 0 m³**; lo que estaba declarado lo lee su parámetro y
        queda anotado en los parámetros de la operación (y, desde entonces, cambiarlo la deja obsoleta)."""
        self.declare("PLT-003", "PLT-001")
        self.assertEqual(entity_store.declared_supports(self.project, self.v1, "PLT-003"), ("PLT-001",))
        old = self.current("PLT-003")
        self.assertEqual(self.supports_of(old), [])
        self.assertEqual(self.stale_causes(old), set(), "no leía lo declarado: una fila nueva no la marca")
        self.clock.advance(minutes=1)
        handle, work = design_store.recompute_run(self.request_for(old))
        finish(work)
        self.assertEqual(self.supports_of(handle.uid),
                         [(PSF1, "supported_on"), (EPR1, "support_footprint")])
        self.assertEqual(self.volumes_of(handle.uid), {"PLT-001": 0.0})
        scope = figures_mod.scope_json(provenance.entity_figure_scope(WORKSHOP, "PLT-001"))
        self.assertEqual(self.figures_of(handle.uid)[("des.supported_m3", scope)], 0.0)
        read = [key for (key,) in self.query("SELECT p.key FROM gb_operation_param AS op JOIN gb_parameter "
                                             "AS p ON p.uid = op.parameter_uid WHERE op.operation_uid = ?",
                                             handle.uid)]
        self.assertIn(self.WORKSHOP_KEY, read)
        self.declare("PLT-003", "PLT-002")  # desde que lo lee, cambiar lo declarado la deja obsoleta
        self.assertIn(("parameter_changed", self.WORKSHOP_KEY), self.stale_causes(handle.uid))

    def test_c_what_does_not_exist_is_the_entity_itself_or_would_be_a_cycle_is_refused(self) -> None:
        """RF-015-15: declarar una entidad que no existe (PLT-009), la propia (PLT-003) o una que parte de la
        superficie de la que declara (P1 en P2: P2 parte de la de P1, sería un ciclo) se rechaza con la
        entidad, el campo, lo declarado y el motivo, sin escribir nada."""
        self.refused("PLT-003", "PLT-009", "PLT-009", "no existe")
        self.refused("PLT-003", "PLT-003", "PLT-003", "propia")
        self.refused("PLT-001", "PLT-002", "PLT-002", "ciclo")


class FillOnlySupportsTest(FillOnlyCase):
    """RF-015-15, D-11 (y, sin entidades, la 013 y la 014 como antes): sobre la cantera de la 014, con el diseño
    «solo relleno» «Balsa» creado **antes** de que la versión tenga entidades (el gancho ni se llama: la
    versión no tiene ninguna), la «Plataforma de la balsa» (corta a 255 m, en la lámina de agua) y «Balsa 2»,
    que rellena sobre su huella y se apoya en ella."""

    before_stored: ClassVar[Any]
    after_stored: ClassVar[Any]
    twin_request: ClassVar[Any]
    had_entities: ClassVar[tuple[bool, bool]]
    revision: ClassVar[str]
    recomputed: ClassVar[Any] = None

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.build()
        first = cls.exists()
        with mock.patch.object(entity_store, "survey_supports",
                               side_effect=AssertionError("sin entidades, el gancho ni se llama")):
            cls.before_stored = cls.fill(fill_test.REQUEST)
        cls.made(asked(BALSA))
        cls.had_entities = (first, cls.exists())
        cls.twin_request = model.FillOnlyRequest("Balsa 2", fill_test.ENVELOPE, fill_test.START,
                                                 fill_test.REST.code, water=fill_test.WATER)
        cls.after_stored = cls.fill(cls.twin_request)

    def test_a_without_entities_nothing_changes_and_the_hook_is_not_even_called(self) -> None:
        """RF-015-15 (coste cero): la versión sin entidades no paga el gancho (una consulta: ``_has_entities``
        es falso antes de crear la plataforma y verdadero después) y «Balsa», creada así, queda como antes: sin
        entradas ``supported_on`` ni ``support_footprint`` y sin la cifra ``des.supported_m3``; sus entradas
        son las de «solo relleno» (``fill_only_inputs``) y sus cifras, las del diseño."""
        self.assertEqual(self.had_entities, (False, True))
        uid = self.before_stored.handle.uid
        self.assertEqual(self.supports_of(uid), [])
        self.assertEqual(self.volumes_of(uid), {})
        roles = {role for (role,) in self.query(
            "SELECT role FROM gb_operation_io WHERE operation_uid = ? AND direction = 'in'", uid)}
        self.assertIn("surface", roles)
        self.assertIn("envelope", roles)
        self.assertFalse(roles & {"supported_on", "support_footprint"})
        keys = {key for (key,) in self.query("SELECT key FROM gb_figure WHERE operation_uid = ?", uid)}
        self.assertIn("des.fill_m3", keys)
        self.assertNotIn("des.supported_m3", keys)

    def test_b_a_fill_only_that_fills_over_the_footprint_of_a_platform_rests_on_it(self) -> None:
        """RF-015-15, D-11: «Balsa 2» (de la ladera, sin cortar nada, rellena la lámina a 270 m) deja la
        superficie de la plataforma de la balsa (a 255 m, bajo la ladera de 267 a 271 m) con el relleno sobre
        el terreno en ella: se apoya en la plataforma, con la superficie y la huella como entradas y los m³ de
        ``r − máx(s, e)`` sobre su huella (el cálculo a mano de los ficheros, a ≤ 10⁻⁹ relativo)."""
        uid = self.after_stored.handle.uid
        psf, epr = provenance.dataset_name("psf", BALSA), provenance.dataset_name("epr", BALSA)
        self.assertEqual(self.supports_of(uid), [(psf, "supported_on"), (epr, "support_footprint")])
        found = self.volumes_of(uid)
        self.assertEqual(list(found), ["PLT-001"])
        oracle = self.by_hand(provenance.dataset_name("srf", "Balsa 2"), qfx.terrain(self.grid), psf, epr)
        self.assertGreater(oracle, 100.0)
        self.assertLessEqual(abs(found["PLT-001"] - oracle) / oracle, 1e-9)
        scope = figures_mod.scope_json(provenance.entity_figure_scope("Balsa 2", "PLT-001"))
        self.assertEqual(self.figures_of(uid)[("des.supported_m3", scope)], found["PLT-001"])

    @classmethod
    def recompute_older(cls) -> Any:
        """Recalcula «Balsa» —el «solo relleno» creado **antes** de la entidad— con ``recompute_run``, una vez por
        clase (los dos casos que la usan no dependen de su orden): su ``OperationHandle``, ya completa."""
        if cls.recomputed is None:
            older = cls.before_stored.handle.uid
            ((settings,),) = cls.query_of("SELECT settings FROM gb_operation WHERE uid = ?", older)
            cls.clock.advance(minutes=1)
            handle, work = design_store.recompute_run(recompute_mod.RecomputeRequest(
                cls.project, older, provenance.FILL_ONLY, json.loads(settings), (), (), version=cls.v1.uid))
            fill_test.drive(work)
            cls.recomputed = handle
        return cls.recomputed

    def test_c_recomputing_the_fill_only_keeps_what_it_rested_on(self) -> None:
        """RF-015-15, ADR-0030 §4: recalcular «Balsa 2» arrastra la superficie y la huella de la plataforma y
        mide otra vez lo apoyado (el mismo, nada cambió)."""
        old = self.after_stored.handle.uid
        settings = json.loads(self.query("SELECT settings FROM gb_operation WHERE uid = ?", old)[0][0])
        before = self.volumes_of(old)
        self.clock.advance(minutes=1)
        request = recompute_mod.RecomputeRequest(self.project, old, provenance.FILL_ONLY, settings, (), (),
                                                 version=self.v1.uid)
        handle, work = design_store.recompute_run(request)
        fill_test.drive(work)
        self.assertEqual(self.supports_of(handle.uid), self.supports_of(old))
        self.assertEqual(self.volumes_of(handle.uid), before)

    def test_c_recomputing_a_fill_only_made_before_the_entity_gains_the_dependency(self) -> None:
        """RF-015-15, ADR-0030 §4, CE-015-01 (C-1, error 59): «Balsa», creada **antes** de la plataforma, rellena
        sobre su huella como «Balsa 2» y, **al recalcularse**, gana la dependencia (antes no: la operación ya
        empezada no admitía entradas nuevas): la superficie y la tabla de la huella de P1 como entradas, con
        el hash que tenían y el volumen del cálculo a mano (≤ 10⁻⁹ relativo), y la cifra con el ámbito de P1.
        Lo que se le apoya a P1 y lo que lista descartarla son ya las dos, y la dependencia es la de «Crear»:
        la misma que registraría una operación calculada después."""
        before = self.before_stored.handle.uid
        self.assertEqual(self.supports_of(before), [], "creada sin entidades: sin dependencia")
        handle = self.recompute_older()
        new = handle.uid
        self.assertNotEqual(new, before)
        psf, epr = provenance.dataset_name("psf", BALSA), provenance.dataset_name("epr", BALSA)
        self.assertEqual(self.supports_of(new), [(psf, "supported_on"), (epr, "support_footprint")])
        found = self.volumes_of(new)
        self.assertEqual(list(found), ["PLT-001"])
        oracle = self.by_hand(provenance.dataset_name("srf", "Balsa"), qfx.terrain(self.grid), psf, epr)
        self.assertGreater(oracle, 100.0)
        self.assertLessEqual(abs(found["PLT-001"] - oracle) / oracle, 1e-9)
        scope = figures_mod.scope_json(provenance.entity_figure_scope("Balsa", "PLT-001"))
        self.assertEqual(self.figures_of(new)[("des.supported_m3", scope)], found["PLT-001"])
        marked = self.query(
            "SELECT d.name, io.role, io.content_sha256 = d.content_sha256 FROM gb_operation_io AS io "
            "JOIN gb_dataset AS d ON d.uid = io.item_uid WHERE io.operation_uid = ? AND io.direction = 'in' "
            "AND io.role IN ('supported_on', 'support_footprint') ORDER BY io.fid", new)
        self.assertEqual([(name, role) for name, role, _same in marked],
                         [(psf, "supported_on"), (epr, "support_footprint")])
        self.assertTrue(all(same for _name, _role, same in marked), "con el hash que tienen ahora")
        listed = entities.dependents(self.project, self.v1.uid, "PLT-001")
        self.assertEqual(sorted(item.name for item in listed), ["Balsa", "Balsa 2"])
        self.assertEqual({item.name: item.state for item in listed},
                         {"Balsa": entities.EntityState.CURRENT, "Balsa 2": entities.EntityState.CURRENT})
        plan = entity_store.discard_plan(self.project, self.v1.uid, "PLT-001")
        self.assertEqual(sorted(item.name for item in plan.dependents), ["Balsa", "Balsa 2"])
        listed_volume = {item.name: item.volume_m3 for item in plan.dependents}
        self.assertEqual(listed_volume["Balsa"], found["PLT-001"])
        self.assertEqual(self.current_fill_of("Balsa"), new, "es la operación vigente de «Balsa»")

    def test_d_reproducing_the_frozen_fill_only_gives_the_supported_volume_too(self) -> None:
        """RF-015-15, RF-009-11: congelada V01, la reproducción de «Balsa 2» da la misma cifra de lo apoyado
        (desde la superficie de partida y la superficie y la huella congeladas de la plataforma) y todo igual;
        también la de «Balsa», recalculada con su dependencia nueva (C-1)."""
        late = self.recompute_older().uid
        self.clock.advance(minutes=1)
        frozen = fill_test.drive(freeze.freeze_steps(self.project, self.v1.uid, reason="Entrega")).result
        revision = str(frozen.frozen.uid)
        self.clock.advance(minutes=1)
        report = fill_test.drive(reproduce_mod.reproduce_steps(self.project, revision)).result
        for uid in (self.current_fill_of("Balsa 2"), late):
            with self.subTest(operation=uid):
                found = [check for check in report.figures if check.operation_uid == uid
                         and check.key == "des.supported_m3"]
                self.assertEqual(len(found), 1)
                self.assertTrue(found[0].same, found)
                self.assertTrue(all(check.same for check in report.figures if check.operation_uid == uid))
        self.assertTrue(report.matches, report.not_reproducible)


class LateSupportTest(FillOnlyCase):
    """RF-015-15, RF-015-16, RF-015-17, CE-015-01 (C-1, el patrón del error 59), por el camino de la persona
    («Recalcular lo obsoleto»): «Balsa», un «solo relleno», se creó **antes** de que existiera la plataforma P1
    y «Balsa 2», después; las dos rellenan lo mismo sobre su huella. En el orden de las pruebas: (a) lo que se le
    apoya a P1 antes, (b) tras cambiar la altura de banco y repetir las dos, (c) la cascada desde P1 y (d)
    descartarla."""

    old: ClassVar[Any]
    twin: ClassVar[Any]
    HEIGHT_KEY: ClassVar[str] = design_params.bench_key(fill_test.REST.code, "height_m")
    FILLED_M3: ClassVar[float] = 936.0
    """A mano, con la altura de banco 0,5 m mayor (la sonda de la verificación): lo que rellenan las dos sobre
    la huella de P1."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.build()
        cls.old = cls.fill(fill_test.REQUEST)  # «Balsa»: antes de que exista ninguna entidad
        cls.made(asked(BALSA))
        cls.twin = cls.fill(model.FillOnlyRequest("Balsa 2", fill_test.ENVELOPE, fill_test.START,
                                                  fill_test.REST.code, water=fill_test.WATER))

    def listed(self) -> dict[str, float | None]:
        """Lo que se le apoya a P1 (``dependents``), por nombre, con su volumen."""
        return {item.name: item.volume_m3 for item in entities.dependents(self.project, self.v1.uid, "PLT-001")}

    def test_a_before_recalculating_only_the_design_made_after_the_entity_rests_on_it(self) -> None:
        """RF-015-15 (la premisa de C-1): «Balsa» no tiene la dependencia (se creó sin entidades) y solo «Balsa 2»
        figura entre lo que se le apoya a P1 y entre lo que lista descartarla."""
        self.assertEqual(list(self.listed()), ["Balsa 2"])
        plan = entity_store.discard_plan(self.project, self.v1.uid, "PLT-001")
        self.assertEqual([item.name for item in plan.dependents], ["Balsa 2"])
        self.assertEqual(self.supports_of(self.old.handle.uid), [])

    def test_a_if_the_entity_changes_while_it_is_measured_the_recompute_fails_and_registers_nothing(self) -> None:
        """RF-015-15, RF-013-17 (como ``des.input_changed`` al empezar una operación): si el dato de la entidad cambia
        entre que se mide el resultado y se anota la dependencia, la medida ya no le corresponde: el recálculo
        falla con ``des.input_changed``, nombrando el dato, y no deja ni la dependencia, ni la cifra, ni la
        operación como buena (la anterior sigue vigente)."""
        older = self.old.handle.uid
        ((settings,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", older)
        self.clock.advance(minutes=1)
        handle, work = design_store.recompute_run(recompute_mod.RecomputeRequest(
            self.project, older, provenance.FILL_ONLY, json.loads(settings), (), (), version=self.v1.uid))
        psf = provenance.dataset_name("psf", BALSA)
        genuine = self.record(psf, self.v1).content_sha256
        measure = design_store._seen

        def changed(conn: Any, uses: Any, version: Any) -> Any:
            found = measure(conn, uses, version)
            with self.project.write_transaction() as writing:  # alguien cambia la superficie de P1 justo después
                writing.execute("UPDATE gb_dataset SET content_sha256 = ? WHERE name = ?", ("0" * 64, psf))
            return found

        try:
            with mock.patch.object(design_store, "_seen", changed), self.assertRaises(DesignError) as caught:
                fill_test.drive(work)
        finally:
            with self.project.write_transaction() as writing:
                writing.execute("UPDATE gb_dataset SET content_sha256 = ? WHERE name = ?", (genuine, psf))
        self.assertEqual(caught.exception.code, "des.input_changed")
        self.assertIn(psf, caught.exception.text)
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE uid = ?", handle.uid), [("failed",)])
        self.assertEqual(self.supports_of(handle.uid), [])
        self.assertEqual(self.volumes_of(handle.uid), {})
        self.assertEqual(self.query("SELECT superseded_by FROM gb_operation WHERE uid = ?", older), [(None,)])

    def test_b_recalculating_the_stale_registers_the_dependency_of_the_older_design_too(self) -> None:
        """RF-015-15, RF-015-17, CE-015-01 (C-1): tras cambiar la altura de banco, «Recalcular lo obsoleto» repite
        las dos (ninguna falla) y lo que se le apoya a P1 y lo que lista descartarla son **las dos**, cada una con
        sus metros cúbicos del cálculo a mano (≤ 10⁻⁹ relativo; 936 m³ las dos, como midió la sonda), no solo
        la que se creó después."""
        self.change(self.HEIGHT_KEY, fill_test.REST.height_m + 0.5)
        self.assertEqual(self.recompute_plan(), [(provenance.FILL_ONLY,), (provenance.FILL_ONLY,)])
        self.clock.advance(minutes=1)
        outcome = finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual([(str(result.status), result.unit.op_types) for result in outcome.results],
                         [("done", (provenance.FILL_ONLY,))] * 2)
        psf, epr = provenance.dataset_name("psf", BALSA), provenance.dataset_name("epr", BALSA)
        terrain = qfx.terrain(self.grid)
        found = self.listed()
        self.assertEqual(sorted(found), ["Balsa", "Balsa 2"])
        for name in ("Balsa", "Balsa 2"):
            with self.subTest(design=name):
                oracle = self.by_hand(provenance.dataset_name("srf", name), terrain, psf, epr)
                self.assertLessEqual(abs(oracle - self.FILLED_M3) / self.FILLED_M3, 1e-9)
                self.assertLessEqual(abs(found[name] - oracle) / oracle, 1e-9)
                self.assertEqual(self.supports_of(self.current_fill_of(name)),
                                 [(psf, "supported_on"), (epr, "support_footprint")])
        plan = entity_store.discard_plan(self.project, self.v1.uid, "PLT-001")
        self.assertEqual({item.name: item.volume_m3 for item in plan.dependents}, found)

    def test_c_changing_the_entity_leaves_both_designs_stale_with_their_cause(self) -> None:
        """RF-015-16, RF-008-24 (C-1): con la dependencia registrada, cambiar la cota de P1 deja obsoletas las dos
        (en cascada: antes, «Balsa» quedaba al día aunque rellenaba sobre ella)."""
        names = ("Balsa", "Balsa 2")
        self.assertEqual([self.stale_causes(self.current_fill_of(name)) for name in names], [set(), set()])
        self.change(design_params.entity_key("PLT-001", "start_level_m"), 254.0)
        for name in names:
            with self.subTest(design=name):
                self.assertNotEqual(self.stale_causes(self.current_fill_of(name)), set())

    def test_d_discarding_the_entity_leaves_both_designs_in_support_removed(self) -> None:
        """RF-015-17 (C-1, error 59): descartar P1 deja en «apoyo retirado» a las dos, no solo a «Balsa 2»."""
        self.clock.advance(minutes=1)
        entity_store.discard_entity(self.project, self.v1.uid, "PLT-001", reason="La balsa no se hace",
                                    decided_by="Samuel (IMGA)")
        self.assertEqual(sorted((item.name, item.op_type) for item in entities.retired_supports(
            self.project, self.v1.uid)), [("Balsa", provenance.FILL_ONLY), ("Balsa 2", provenance.FILL_ONLY)])


class FrozenSupportsTest(SupportsCase):
    """RF-015-15, RF-009-11: congelar V01 con P1 y P2 (que se apoya en ella) y reproducir da las mismas cifras,
    **también** ``des.supported_m3``, desde la superficie y la huella congeladas de P1."""

    first: ClassVar[Any]
    second: ClassVar[Any]
    revision: ClassVar[str]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.first = cls.made(prep.request())
        cls.second = cls.made(over())
        cls.clock.advance(minutes=1)
        frozen = finish(freeze.freeze_steps(cls.project, cls.v1.uid, reason="Entrega de la prueba"))
        cls.revision = str(frozen.frozen.uid)
        cls.clock.advance(minutes=1)

    def test_d_reproducing_gives_the_supported_volume_too(self) -> None:
        """RF-015-15, RF-009-11: V01.r1 se reproduce —sin proyecto— con la misma cifra de lo apoyado (la
        reproducción lee la superficie de P1 y la tabla de su huella congeladas, con ``s`` y ``r``) y todo
        igual, sin escribir nada en el proyecto."""
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        report = finish(reproduce_mod.reproduce_steps(self.project, self.revision))
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root)),
                         before, "reproducir no escribe en el proyecto")
        uid = self.second.handle.uid
        found = [check for check in report.figures if check.operation_uid == uid
                 and check.key == "des.supported_m3"]
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].same, found)
        self.assertLessEqual(abs(found[0].reproduced - OVER_VOLUME_M3) / OVER_VOLUME_M3, 1e-9)
        self.assertTrue(all(check.same for check in report.figures))
        self.assertTrue(all(check.same for check in report.outputs))
        self.assertFalse(report.not_reproducible)
        self.assertTrue(report.matches)


class DragSupportsTest(SupportsCase):
    """RF-015-15, D-11, P-5: un diseño que solo **arrastra el terreno** sobre la huella de una plataforma
    «cortada» no se apoya en ella."""

    other: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())
        cls.other = cls.made(asked(DRAG, start=prep.HOLE_DATASET))

    def test_d_a_design_that_only_drags_the_terrain_over_a_cut_platform_is_not_supported(self) -> None:
        """RF-015-15, P-5: «Arrastra el terreno» (que parte de otro terreno, corta a 255 m y cruza la huella de
        P1) deja el terreno —**por encima** de la plataforma cortada— tal como estaba en casi toda ella: sin
        el ``máx(partida, entidad)`` contaría como apoyada en P1 (``r − e`` pasa de 0,02 m en cientos de sus
        celdas); con él, ``a`` es 0 a mano y no se apoya en nada (ni entradas ni cifra)."""
        uid = self.other.handle.uid
        self.assertEqual(self.supports_of(uid), [])
        self.assertEqual(self.volumes_of(uid), {})
        mine, theirs = self.grid_of(provenance.dataset_name("psf", DRAG)), self.grid_of(PSF1)
        rows, cols = self.footprint_of(EPR1)
        with np.errstate(invalid="ignore"):
            naive = (mine[rows, cols] - theirs[rows, cols]) > THICKNESS_M
        self.assertGreater(int(naive.sum()), 500, "sin el máx, la mayor parte de la huella contaría")
        self.assertEqual(self.by_hand(provenance.dataset_name("psf", DRAG), prep.hole_raster().values,
                                      PSF1, EPR1), 0.0)

    def test_d_recomputing_a_design_that_rests_on_nothing_gains_no_dependency(self) -> None:
        """RF-015-15 (C-1, el reverso): recalcular «Arrastra el terreno», que cruza la huella de P1 sin rellenar
        encima, **no** gana ninguna entrada ni cifra (como al crearla: la versión tiene entidades, pero ninguna
        bajo lo que rellena)."""
        self.clock.advance(minutes=1)
        handle, work = design_store.recompute_run(self.request_for(self.other.handle.uid))
        finish(work)
        self.assertNotEqual(handle.uid, self.other.handle.uid)
        self.assertEqual(self.supports_of(handle.uid), [])
        self.assertEqual(self.volumes_of(handle.uid), {})


class RecomputeSupportsTest(SupportsCase):
    """RF-015-15, ADR-0030 §4, RF-015-02 (T14): recalcular P2 lleva lo que apoyaba y lo **vuelve a medir** sobre
    el resultado nuevo (no copia el volumen): una operación hecha es inmutable."""

    first: ClassVar[Any]
    second: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.first = cls.made(prep.request())
        cls.second = cls.made(over())

    def test_c_recomputing_keeps_what_it_rested_on_and_measures_it_again(self) -> None:
        """RF-015-15, ADR-0030 §4: P2 sube de 252 a 253 m (parámetro de su fila de la versión) y se recalcula:
        la operación **nueva** (la anterior queda como historia con sus 8.000 m³) anota otra vez la superficie
        de P1 y la tabla de su huella y mide **12.000 m³** (3 m sobre 1.000 celdas de 4 m²), no los 8.000 de
        antes."""
        old = self.second.handle.uid
        before = self.volumes_of(old)["PLT-001"]
        self.assertLessEqual(abs(before - OVER_VOLUME_M3) / OVER_VOLUME_M3, 1e-9)
        self.change(design_params.entity_key("PLT-002", "start_level_m"), 253.0)
        self.assertEqual(len(self.recompute_plan()), 1)
        self.clock.advance(minutes=1)
        handle, work = design_store.recompute_run(self.request_for(old))
        finish(work)
        new = handle.uid
        self.assertNotEqual(new, old)
        self.assertEqual(self.supports_of(new), [(PSF1, "supported_on"), (EPR1, "support_footprint")])
        found = self.volumes_of(new)
        self.assertEqual(list(found), ["PLT-001"])
        self.assertLessEqual(abs(found["PLT-001"] - 12_000.0) / 12_000.0, 1e-9)
        self.assertEqual(self.volumes_of(old)["PLT-001"], before, "la historia no cambia")
        self.assertEqual(self.current("PLT-002"), new)
        self.assertEqual(self.recompute_plan(), [])


class ThicknessRecomputeTest(ThicknessCase):
    """RF-015-15, ADR-0030 §4: al recalcular con otro espesor mínimo se **vuelve a medir** (no se copia lo
    anterior) y la dependencia que ya tenía se queda (una operación hecha es inmutable)."""

    second: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())
        cls.second = cls.made(over())

    def test_c_recomputing_with_a_thicker_minimum_measures_zero_and_keeps_the_dependency(self) -> None:
        """RF-015-15: P2 se apoya en P1 con 8.000 m³; el espesor mínimo pasa a 2,1 m (la deja obsoleta por ese
        parámetro) y, recalculada, la operación nueva sigue teniendo la superficie y la huella de P1 como
        entradas (lo que apoyaba se arrastra) pero con **0 m³** medidos de nuevo: ni los 8.000 de antes ni
        una dependencia que desaparece."""
        first = self.second.handle.uid
        self.assertLessEqual(abs(self.volumes_of(first)["PLT-001"] - OVER_VOLUME_M3) / OVER_VOLUME_M3, 1e-9)
        self.thickness(2.1)
        self.assertIn(("parameter_changed", self.KEY), self.stale_causes(first))
        self.clock.advance(minutes=1)
        handle, work = design_store.recompute_run(self.request_for(first))
        finish(work)
        self.assertEqual(self.supports_of(handle.uid),
                         [(PSF1, "supported_on"), (EPR1, "support_footprint")])
        self.assertEqual(self.volumes_of(handle.uid), {"PLT-001": 0.0})


class SupportedOnFillTest(SupportsCase):
    """RF-015-15, D-11, CE-015-01: P2 («en corte y relleno» sobre la huella de P1, de su superficie) se apoya en
    P1 con los 8.000 m³ a mano; P1, que se creó antes, no se apoya en nada."""

    first: ClassVar[Any]
    second: ClassVar[Any]
    shown: ClassVar[tuple[Any, ...]]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.first = cls.made(prep.request())
        cls.clock.advance(minutes=1)
        calculation = cls.calculate_in(over())
        cls.shown = entity_store.detected_supports(cls.project, calculation.entity, calculation.outcome)
        cls.clock.advance(minutes=1)
        cls.second = calculation.create()

    def test_b_the_platform_that_fills_on_another_rests_on_it_with_the_volume_by_hand(self) -> None:
        """RF-015-15, CE-015-01 (D-9): la operación de P2 anota la superficie de P1 como ``supported_on`` y
        la tabla de su huella como ``support_footprint`` (además de la superficie de partida, que es la misma
        con el papel ``surface``) y la cifra ``des.supported_m3`` con el ámbito de P1 —CALCULADO, en m³—:
        **8.000 m³**, a ≤ 10⁻⁹ relativo del cálculo a mano y del que sale de los ficheros (``r − máx(s, e)``
        sobre la huella de P1)."""
        uid = self.second.handle.uid
        self.assertEqual(self.supports_of(uid), [(PSF1, "supported_on"), (EPR1, "support_footprint")])
        inputs = {(name, role) for name, role in self.query(
            "SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'in'", uid)}
        self.assertIn((PSF1, "surface"), inputs)
        self.assertIn((PSF1, "supported_on"), inputs)
        found = self.volumes_of(uid)
        self.assertEqual(list(found), ["PLT-001"])
        self.assertLessEqual(abs(found["PLT-001"] - OVER_VOLUME_M3) / OVER_VOLUME_M3, 1e-9)
        oracle = self.by_hand(provenance.dataset_name("psf", OVER), self.grid_of(PSF1), PSF1, EPR1)
        self.assertLessEqual(abs(found["PLT-001"] - oracle) / oracle, 1e-9)
        scope = figures_mod.scope_json(provenance.entity_figure_scope(OVER, "PLT-001"))
        self.assertEqual(self.figures_of(uid)[("des.supported_m3", scope)], found["PLT-001"])
        self.assertEqual(self.query("SELECT unit, kind FROM gb_figure WHERE operation_uid = ? AND key = "
                                    "'des.supported_m3'", uid), [("m3", "CALCULADO")])

    def test_b_the_first_platform_rests_on_nothing_and_what_rests_on_it_is_a_query(self) -> None:
        """RF-015-15, ADR-0030 §4: P1 se creó antes y no se apoya en nada (ni entradas ni cifras); lo que se le
        apoya a P1 es una consulta de las entradas con el rol ``supported_on`` (la lista de la T24: P2, que
        además parte de su superficie: se ve tanto por partida como por relleno); las dos siguen al día."""
        self.assertEqual(self.supports_of(self.first.handle.uid), [])
        self.assertEqual(self.volumes_of(self.first.handle.uid), {})
        rests = self.query(
            "SELECT o.uid, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "JOIN gb_operation AS o ON o.uid = io.operation_uid WHERE io.direction = 'in' AND d.name = ? "
            "ORDER BY io.role", PSF1)
        self.assertEqual(rests, [(self.second.handle.uid, "supported_on"),
                                 (self.second.handle.uid, "surface")])
        registry = entities.registry(self.project, self.v1.uid)
        self.assertEqual([str(entry.record.state) for entry in registry], ["current", "current"])

    def test_b_what_the_hook_shows_is_what_creating_records(self) -> None:
        """RF-015-15: ``detected_supports`` (lo que apoyaría una plataforma calculada, para enseñarlo antes de
        crearla) dio a P1 con las mismas 1.000 celdas y los mismos 8.000 m³ que registró «Crear»."""
        self.assertEqual([(item.code, item.cells) for item in self.shown], [("PLT-001", 1000)])
        self.assertLessEqual(abs(self.shown[0].volume_m3 - OVER_VOLUME_M3) / OVER_VOLUME_M3, 1e-9)
        self.assertEqual(self.shown[0].volume_m3, self.volumes_of(self.second.handle.uid)["PLT-001"])
