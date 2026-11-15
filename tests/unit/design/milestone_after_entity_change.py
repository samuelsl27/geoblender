# SPDX-License-Identifier: GPL-3.0-or-later
"""Pruebas de hito de «test_after_entity_change» (spec 015, T48; plan 015 §7.4): las clases que pesan,
movidas sin cambiar una aserción. El «verde» deja en ``test_after_entity_change`` las más ligeras de cada
requisito; las de aquí las ejecuta el paso «hito» de ``tools/check.py --completo`` (la publicación
lo pide siempre).
"""

from __future__ import annotations

import json
from unittest import mock

from tests.support import step_modals
from tests.support.package import import_geoblender
from tests.support.versions_fixtures import freeze_rows
from tests.unit.design import test_declare_operation as decl
from tests.unit.design import test_platform_operation as ops
from tests.unit.design import test_platform_prepare as prep
from tests.unit.design.test_after_entity_change import (
    CAUSE_DATASET,
    CELL_M2,
    CODE,
    COMPILE,
    ChainCase,
    DECLARE,
    EDITOR,
    FirstDeclarationCase,
    GUARD_M,
    LOADING,
    P1_CODE,
    PLATFORM,
    SAMPLED_EVENTS,
    WORKSHOP,
    access,
    dilate,
    entities,
    entity_store,
    preview,
    recompute_mod,
    versions_model,
)


class ChainTest(ChainCase):
    """RF-015-10, RF-015-16, RF-012-06, H-1, D-21: P1 creada sin declaradas y, en el orden de las pruebas,
    (a) la primera cadena, (b) la repetición, (c) P2 que protege, (d) «Recalcular lo obsoleto», (e) otro
    resguardo y (f) retirar la protección."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.first = cls.made(prep.request())
        cls.compile_before = str(cls.query_of(
            "SELECT o.uid FROM gb_operation AS o WHERE o.op_type = ? AND o.superseded_by IS NULL",
            COMPILE)[0][0])

    # --- (a) La primera vez ------------------------------------------------------------------------

    def test_a_the_first_chain_declares_an_empty_table_and_compiles_the_masks_once(self) -> None:
        """RF-015-10, H-1: sin ninguna entidad que proteja, la primera cadena declara una tabla **vacía** (la
        versión ya tiene su ``des_decl_v01``) y, como la compilación vigente no la había consumido, **compila
        las máscaras de nuevo** una vez: con la tabla como entrada y, como no hay ninguna declarada, **iguales**
        (ni lo ganado ni lo perdido) y sin dejar nada obsoleto: P1, que las usó, sigue al día."""
        self.assertIs(self.state(), access.MaskState.CURRENT)  # las de la 012, sin tabla
        chain = self.chain()
        self.assertIsInstance(chain, entity_store.EntityChain)
        self.assertEqual((chain.version, chain.declared, chain.declaration_changed, chain.masks_compiled),
                         ("V01", 0, True, True))
        self.assertIsNone(chain.failure)
        self.assertEqual((chain.changes, chain.obsolete), ((), ()))
        self.assertIs(chain.masks_state, access.MaskState.CURRENT)
        self.assertEqual([notice.code for notice in chain.notices()],
                         ["des.entity_chain_declared", "des.entity_chain_masks"])
        self.assertNotEqual(self.compile_op(), self.compile_before)
        self.assertIn("des_decl", self.inputs(self.compile_op()))
        self.assertIs(self.state(), access.MaskState.CURRENT)
        self.assertEqual(self.recompute_plan(), [], "unas máscaras iguales no dejan nada obsoleto")
        self.assertEqual(self.stale_causes(self.current("PLT-001")), set())

    def test_b_repeating_it_without_changes_compiles_nothing_and_changes_nothing(self) -> None:
        """RF-015-10, A8, RF-012-06: repetir la cadena sin cambiar nada vuelve a declarar (sustituye a la
        declaración vigente, el mismo contenido y el mismo hash) pero **no recompila**: la compilación vigente es
        la misma, las máscaras siguen al día y no se dice nada de ellas."""
        before, digest = self.compile_op(), self.record_of().content_sha256
        chain = self.chain()
        self.assertEqual((chain.declared, chain.declaration_changed, chain.masks_compiled),
                         (0, False, False))
        self.assertEqual((chain.changes, chain.obsolete, chain.failure), ((), (), None))
        self.assertEqual(chain.notices(), ())
        self.assertEqual(self.compile_op(), before)
        self.assertEqual(self.record_of().content_sha256, digest)
        self.assertIs(self.state(), access.MaskState.CURRENT)

    # --- (c) Una plataforma que protege ------------------------------------------------------------

    def test_c_a_platform_that_protects_gets_its_zone_in_the_masks_and_the_report(self) -> None:
        """RF-015-10, RF-012-06, RF-015-16, D-21: P2 (que protege con 4 m) se crea y la cadena declara su
        restricción y recompila las máscaras con su zona: la huella ampliada 2 celdas (calculada aquí con otra
        fórmula), sin el relleno de esa zona; el informe da por su código lo **ganado** (el polígono: la huella;
        la zona: la huella ampliada) y lo perdido (nada) en m²; y quedan obsoletas, con su causa (otro contenido
        de un dato que consumieron, las máscaras), las operaciones que usaron las anteriores: P1 y **la propia
        P2**, cuya restricción cambió lo que ella misma consumió."""
        stored = self.made(prep.request(WORKSHOP, start="entity:PLT-001", protect=True, guard_m=GUARD_M))
        self.assertEqual(self.stale_causes(str(stored.handle.uid)), set(), "al crearla, está al día")
        chain = self.chain()
        self.assertEqual((chain.declared, chain.declaration_changed, chain.masks_compiled), (1, True, True))
        self.assertIsNone(chain.failure)
        footprint_m2, zone_m2 = self.zone_area("PLT-002", 2)
        self.assertGreater(zone_m2, footprint_m2)
        (change,) = chain.changes
        self.assertEqual((change.code, change.name), (CODE, WORKSHOP))
        self.assertEqual(change.ctype, import_geoblender("core.constraints.model").ConstraintType.NO_FILL)
        for found, expected in ((change.polygon_gained_m2, footprint_m2), (change.zone_gained_m2, zone_m2)):
            self.assertAlmostEqual(found, expected, delta=1e-9 * expected)
        self.assertEqual((change.polygon_lost_m2, change.zone_lost_m2), (0.0, 0.0))
        masks = access.load_masks(self.project, self.v1.uid)
        zone = masks.zone(CODE).mask(self.grid.shape)
        self.assertTrue((zone == dilate(self.footprint("PLT-002"), 2)).all())
        self.assertEqual(masks.ctypes[CODE], "no_fill")
        self.assertFalse(masks.fill_allowed()[zone].any(), "ni se rellena su zona")
        self.assertEqual(self.entity_declared_code(), CODE)
        names = sorted(item.name for item in chain.obsolete)
        self.assertEqual(names, sorted([LOADING, WORKSHOP]))
        self.assertTrue(all(item.kind is preview.ObsoleteKind.CONSUMER and item.op_type == PLATFORM
                            for item in chain.obsolete))
        for code in ("PLT-001", "PLT-002"):
            causes = self.stale_causes(self.current(code))
            self.assertEqual({kind for kind, _name in causes}, {CAUSE_DATASET}, code)
            self.assertTrue({"gis_msk", "gis_mskz", "gis_mskr"} <= {name for _kind, name in causes}, causes)
        lines = [notice.text("es") for notice in chain.notices()]
        self.assertTrue(lines[0].startswith("Las restricciones que declaran las entidades de V01 están al día: 1"))
        self.assertIn("Las máscaras de V01 se han compilado de nuevo", lines[1])
        area = f"{round(footprint_m2):,}".replace(",", " ")  # el espacio fino de miles
        self.assertTrue(lines[2].startswith(f"{WORKSHOP} (restricción declarada): polígono +"), lines[2])
        self.assertIn("m² −0 m², zona +", lines[2])
        self.assertTrue(lines[3].startswith("Con las máscaras nuevas han quedado obsoletas 2 operaciones"),
                        lines[3])
        self.assertEqual(len(lines), 4)
        self.assertGreater(len(area), 0)

    def entity_declared_code(self) -> str:
        (found,) = self.declared()
        return str(found.code)

    # --- (d) El ciclo ------------------------------------------------------------------------------

    def test_d_recomputing_the_stale_resolves_the_cycle_and_leaves_nothing_stale(self) -> None:
        """RF-015-16, RF-008-26, D-21, CE-015-04: entidad → declarada → máscaras → entidad es un ciclo (P2
        consumió las máscaras que su propia restricción cambió, y el grafo da por obsoleto todo el ciclo): las
        máscaras, aun así, se entregan (**es lo que cierra ``mask_state``**: sus propias entradas no han
        cambiado, la declaración que consumieron es la de ahora) y «Recalcular lo obsoleto» rehace P1 y P2 con
        ellas (las de P2 incluyen su zona, que en el modo «en corte» no le impide cortar), **su salida no
        cambia** (el mismo hash de la superficie, la tabla y el informe) y por eso lo que dependía de ellas (la
        declaración y la compilación) pierde su marca sin recalcularse. Cada pasada rehace **una** unidad (lo
        recalculado que vuelve a quedar obsoleto espera, RF-008-27): con dos entidades encadenadas, dos
        pasadas; no queda nada obsoleto y las máscaras siguen siendo las de la declarada."""
        types = [self.query("SELECT op_type FROM gb_operation WHERE uid = ?", uid)[0][0]
                 for unit in self.plan_units() for uid in unit]
        self.assertIn(PLATFORM, types)
        self.assertEqual(self.recompute_plan()[0], (PLATFORM,), "empieza por una plataforma (el ciclo)")
        self.assertIs(self.state(), access.MaskState.CURRENT, "se entregan: sin ello nada las recalcularía")
        before = {code: self.hashes_of(self.current(code)) for code in ("PLT-001", "PLT-002")}
        declaration, masks_op, table = self.current_declaration(), self.compile_op(), self.declared_dump()
        rounds: list[tuple[str, ...]] = []
        for _ in range(4):
            self.clock.advance(minutes=1)
            done = ops.finish(recompute_mod.recompute_steps(self.project))
            statuses = [result.status for result in done.results]
            self.assertTrue(statuses and all(status is recompute_mod.UnitStatus.DONE for status in statuses),
                            done.results)
            rounds.append(tuple(op for result in done.results for op in (self.query(
                "SELECT op_type FROM gb_operation WHERE uid = ?", uid)[0][0] for uid in result.operations)))
            if not self.recompute_plan():
                break
        self.assertEqual(sorted(op for names in rounds for op in names), [PLATFORM, PLATFORM],
                         "solo se rehacen las dos entidades")
        self.assertLessEqual(len(rounds), 2)
        self.assertEqual(self.recompute_plan(), [])
        for code in ("PLT-001", "PLT-002"):
            self.assertEqual(self.stale_causes(self.current(code)), set(), code)
            self.assertEqual(self.hashes_of(self.current(code)), before[code], f"{code}: su salida no cambia")
        self.assertEqual(self.declared_dump(), table, "la declaración queda como estaba")
        self.assertEqual(self.current_declaration(), declaration, "y no se recalcula: perdió su marca")
        self.assertEqual(self.compile_op(), masks_op, "ni las máscaras")
        self.assertIs(self.state(), access.MaskState.CURRENT)
        self.assertIn(CODE, access.load_masks(self.project, self.v1.uid).zones)

    # --- (e) Otro resguardo ------------------------------------------------------------------------

    def test_e_changing_the_guard_declares_and_compiles_again_with_what_the_zone_gains(self) -> None:
        """RF-015-10, RF-012-06: el resguardo de P2 pasa de 4 a 6 m (otra persona): la cadena repite la
        declaración (otra tabla: otro hash), recompila las máscaras y da lo ganado por la zona (la corona de
        una celda más; el polígono no cambia: la huella es la misma) y lo perdido, nada."""
        digest = self.record_of().content_sha256
        self.change_as(decl.guard_key("PLT-002"), 6.0, EDITOR)
        chain = self.chain()
        self.assertEqual((chain.declared, chain.declaration_changed, chain.masks_compiled), (1, True, True))
        self.assertNotEqual(self.record_of().content_sha256, digest)
        (found,) = self.declared()
        self.assertEqual((found.buffer_out_m, found.decided_by), (6.0, EDITOR))
        (change,) = chain.changes
        _footprint_m2, old_zone = self.zone_area("PLT-002", 2)
        _footprint_m2, new_zone = self.zone_area("PLT-002", 3)
        self.assertGreater(new_zone, old_zone)
        self.assertAlmostEqual(change.zone_gained_m2, new_zone - old_zone, delta=1e-9 * new_zone)
        self.assertEqual((change.polygon_gained_m2, change.polygon_lost_m2, change.zone_lost_m2),
                         (0.0, 0.0, 0.0))
        zone = access.load_masks(self.project, self.v1.uid).zone(CODE).mask(self.grid.shape)
        self.assertTrue((zone == dilate(self.footprint("PLT-002"), 3)).all())

    # --- (f) Retirar la protección ------------------------------------------------------------------

    def test_f_retiring_the_protection_removes_the_restriction_and_reports_what_the_zone_loses(self) -> None:
        """RF-015-10, RF-012-06: P2 deja de proteger: la cadena deja la tabla **vacía** (existe, la compilación
        la consume), recompila las máscaras sin la zona y da lo perdido por su código: el polígono y la zona
        enteros; el relleno de su huella vuelve a estar admitido."""
        _footprint_m2, zone_m2 = self.zone_area("PLT-002", 3)
        footprint_m2 = float(self.footprint("PLT-002").sum()) * CELL_M2
        self.change_as(decl.protect_key("PLT-002"), False, EDITOR)
        chain = self.chain()
        self.assertEqual((chain.declared, chain.declaration_changed, chain.masks_compiled), (0, True, True))
        self.assertEqual(self.declared(), ())
        (change,) = chain.changes
        self.assertEqual((change.code, change.polygon_gained_m2, change.zone_gained_m2), (CODE, 0.0, 0.0))
        self.assertAlmostEqual(change.polygon_lost_m2, footprint_m2, delta=1e-9 * footprint_m2)
        self.assertAlmostEqual(change.zone_lost_m2, zone_m2, delta=1e-9 * zone_m2)
        masks = access.load_masks(self.project, self.v1.uid)
        self.assertNotIn(CODE, masks.zones)
        self.assertTrue(masks.fill_allowed()[self.footprint("PLT-002")].any())


class EveryEventTest(FirstDeclarationCase):
    """RF-015-29, RF-015-10, CE-015-04: Esc en **cualquier** evento de lo que sigue a «Crear» (87 con el presupuesto
    mínimo; aquí, los cinco primeros y otros ocho repartidos hasta el último, cada uno en una copia de la
    instantánea) con una plataforma que protege **no deja nunca** las máscaras al día sin su zona, ni operaciones
    en curso, ni la base dañada (que la cadena siguiente lo termina, ya lo prueba ``StepsTest``)."""

    def test_a_closing_at_any_event_never_leaves_the_masks_current_without_the_zone(self) -> None:
        with self.fresh() as project:
            total = sum(1 for _ in entity_store.after_entity_change(
                project, self.v1, budget_s=step_modals.ONE_STEP_S))
        self.assertGreater(total, 60)
        events = sorted({*range(0, 5), *(round(total * index / SAMPLED_EVENTS) for index in range(1, SAMPLED_EVENTS + 1))})
        for count in events:
            with self.subTest(events=count), self.fresh() as project:
                self.close_after(project, count)
                self.nothing_left_open(project)
                self.never_current_without_its_zone(project)


class FirstDeclarationTest(FirstDeclarationCase):
    """RF-015-10, RF-015-29, CE-015-04, HU-015-1 (el error 51; hallazgo E-1): sin ninguna declaración en la versión
    (la primera de todas), la plataforma que protege **ya existe** (``Crear`` hizo su commit) y lo que sigue falla o
    se cierra con Esc **antes** de escribirla: la entidad no tiene su restricción en ningún sitio y, si las máscaras
    siguen «al día», un operador rellenaría sobre su huella sin ningún aviso (420 m³ en la sonda de la verificación).
    Hasta que se escriba la tabla, las máscaras están **obsoletas con su causa** y quien las pide declara y compila
    antes."""

    def test_a_the_state_it_starts_from_has_a_live_protecting_entity_and_no_declaration(self) -> None:
        """RF-015-10: el punto de partida (la instantánea): P1 viva y calculada, protege, ninguna tabla de
        declaradas, y las máscaras (las de la 012, compiladas antes de que existiera) obsoletas por una restricción
        que **aún no está declarada**."""
        entry = entities.registry(self.project, self.v1.uid).get("PLT-001")
        self.assertEqual(str(entry.record.state), "current")
        self.assertFalse(self.declaration_exists(self.project))
        self.assertIs(self.never_current_without_its_zone(self.project), access.MaskState.STALE)
        self.assertIs(access.mask_cause(self.project, self.v1.uid), access.MaskCause.DECLARED_NEW)

    def test_b_a_declaration_that_fails_leaves_the_masks_stale_with_their_cause(self) -> None:
        """RF-015-10, RF-015-29: la etapa de declarar falla (un fallo del disco): no se escribe nada de ella, el
        fallo va en el resultado (la etapa de declarar y su aviso) y **no se recompila nada** (la compilación no
        puede leer una tabla que no existe); las máscaras no pueden estar al día sin la zona."""
        with self.fresh() as project, mock.patch.object(entity_store, "declared_rows_steps",
                                                        side_effect=OSError("disco lleno")):
            chain = ops.finish(entity_store.after_entity_change(project, self.v1))
            self.assertIs(chain.failure.stage, entity_store.ChainStage.DECLARE)
            self.assertFalse(self.declaration_exists(project))
            self.assertFalse(chain.masks_compiled)
            self.assertIs(self.never_current_without_its_zone(project), access.MaskState.STALE)
            self.assertIs(chain.masks_state, access.MaskState.STALE)
            self.assertIs(access.mask_cause(project, self.v1.uid), access.MaskCause.DECLARED_NEW)
            self.nothing_left_open(project)

    def test_c_closing_it_before_the_first_declaration_is_written_leaves_nothing_and_the_masks_stale(self) -> None:
        """RF-015-29, RF-015-10, CE-015-04: Esc tras 0, 1, 2… eventos, hasta que la declaración se escribe: **ninguno
        deja las máscaras al día sin la zona** (la sonda de la verificación: tras 0, 1 y 2 eventos, 420 m³ de
        relleno y 296 m³ de borde sin aviso), sin operaciones en curso ni la base dañada; la tabla no existe
        mientras no se escribe y, escrita, las máscaras salen obsoletas por ella."""
        absent = 0
        for events in range(0, 6):
            with self.subTest(events=events), self.fresh() as project:
                self.close_after(project, events)
                self.nothing_left_open(project)
                self.assertIs(self.never_current_without_its_zone(project), access.MaskState.STALE)
                if not self.declaration_exists(project):
                    absent += 1
                    self.assertIs(access.mask_cause(project, self.v1.uid), access.MaskCause.DECLARED_NEW)
        self.assertGreaterEqual(absent, 3, "Esc en los eventos 0, 1 y 2 no dejaba rastro: es lo que se prueba")

    def test_d_the_next_operator_declares_and_compiles_before_it_designs(self) -> None:
        """RF-015-10, RF-015-29, CE-015-04: tras lo anterior, quien pide las máscaras por el contrato de los
        operadores (``ensure_masks_steps``) **declara antes**: la restricción de P1 (4 m de resguardo) entra en la
        tabla y en las máscaras, que vuelven a estar al día con su zona; el relleno de su huella no se admite
        (lo que un «en corte y relleno» sobre ella nunca debe rellenar); la declaración es una operación propia y la
        compilación la consume."""
        with self.fresh() as project:
            self.close_after(project, 0)
            self.assertFalse(self.declaration_exists(project))
            masks = ops.finish(access.ensure_masks_steps(project, self.v1.uid))
            self.assertIs(masks.state, access.MaskState.CURRENT)
            self.assertIs(self.never_current_without_its_zone(project), access.MaskState.CURRENT)
            self.assertTrue(self.declaration_exists(project))
            footprint, zone = self.footprint("PLT-001"), masks.zone(P1_CODE).mask(self.grid.shape)
            self.assertTrue((zone == dilate(footprint, 2)).all())
            self.assertFalse(masks.fill_allowed()[footprint].any())
            with project.read() as conn:
                (declarations,) = conn.execute(
                    "SELECT count(*) FROM gb_operation WHERE op_type = ? AND status = 'done' AND "
                    "superseded_by IS NULL", (DECLARE,)).fetchone()
                (consumed,) = conn.execute(
                    "SELECT count(*) FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
                    "WHERE io.operation_uid = ? AND io.direction = 'in' AND d.name = 'des_decl'",
                    (masks.operation_uid,)).fetchone()
            self.assertEqual((declarations, consumed), (1, 1))
            again = ops.finish(access.ensure_masks_steps(project, self.v1.uid))
            self.assertEqual(again.operation_uid, masks.operation_uid, "al día: nada que declarar ni compilar")
            self.nothing_left_open(project)

    def test_e_a_protecting_entity_that_is_no_longer_live_needs_no_declaration(self) -> None:
        """RF-015-10: lo que la declaración recoge son las entidades **vivas** que protegen. Con la única entidad
        que protege **descartada** (ya no es de la versión) y sin tabla, no hay nada pendiente: las máscaras de la
        012 siguen al día, como antes de la 015."""
        with self.fresh() as project:
            self.assertIs(access.mask_state(project, self.v1.uid)[0], access.MaskState.STALE)
            entity_store.discard_entity(project, self.v1.uid, "PLT-001", reason="Prueba de la T38",
                                        decided_by=EDITOR)
            self.assertIs(access.mask_state(project, self.v1.uid)[0], access.MaskState.CURRENT)


class StepsTest(ChainCase):
    """RF-015-29, P-7, RF-009-21: el progreso, Esc y los rechazos de la cadena. P1 (que no protege) y P2 (que sí)
    creadas."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())
        cls.made(prep.request(WORKSHOP, start="entity:PLT-001", protect=True, guard_m=GUARD_M))

    def test_a_the_progress_is_a_percentage_that_never_goes_back(self) -> None:
        """RF-015-29: la cadena da pasos (cada uno de una etapa) como un porcentaje de 0 a 100 que no retrocede,
        con la declaración en su primer tramo y las máscaras en el resto; el último lleva el resultado y es el
        100 %."""
        shown = list(entity_store.after_entity_change(self.project, self.v1, budget_s=1e-9))
        self.assertGreater(len(shown), 4, "un presupuesto mínimo da muchos pasos")
        self.assertTrue(all(step.phase == "entity_chain" for step in shown))
        self.assertTrue(all(step.total == 100 and 0 <= step.done <= 100 for step in shown))
        done = [step.done for step in shown]
        self.assertEqual(done, sorted(done))
        self.assertEqual((shown[0].done, shown[-1].done), (0, 100))
        self.assertTrue(all(step.result is None for step in shown[:-1]))
        self.assertIsInstance(shown[-1].result, entity_store.EntityChain)
        self.assertIs(shown[-1].result.masks_state, access.MaskState.CURRENT)

    def test_b_closing_in_the_middle_of_each_stage_leaves_nothing_half_done(self) -> None:
        """RF-015-29, P-7, RF-012-28: cerrar la cadena (Esc) en la declaración no escribe nada de ella; cerrarla
        en la compilación de las máscaras deja la declaración hecha y **ninguna compilación a medias** (la
        operación queda cancelada): las máscaras, obsoletas con su causa, y la cadena siguiente las compila."""
        self.change_as(decl.guard_key("PLT-002"), 5.0, EDITOR)  # la declaración cambiará: habrá que recompilar
        declaration, masks_op = self.current_declaration(), self.compile_op()
        written = self.written()
        work = entity_store.after_entity_change(self.project, self.v1, budget_s=1e-9)
        next(work)
        next(work)  # dentro de la declaración: la operación empezó, nada escrito todavía
        work.close()
        history = ("operations", "io")  # una operación cancelada queda como historia, con lo que iba a consumir
        self.assertEqual({key: value for key, value in self.written().items() if key not in history},
                         {key: value for key, value in written.items() if key not in history})
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE op_type = ? ORDER BY fid DESC LIMIT 1",
                                    DECLARE), [("cancelled",)])
        self.assertEqual((self.current_declaration(), self.compile_op()), (declaration, masks_op))

        work = entity_store.after_entity_change(self.project, self.v1, budget_s=1e-9)
        for step in work:
            if step.done > entity_store._CHAIN_DECLARE_SHARE:  # ya en la compilación
                break
        else:
            self.fail("la cadena no llegó a compilar las máscaras")
        work.close()
        self.assertNotEqual(self.current_declaration(), declaration, "la declaración ya estaba hecha")
        self.assertEqual(self.compile_op(), masks_op)
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation WHERE status = 'running'"), [(0,)])
        self.assertIs(self.state(), access.MaskState.STALE)
        chain = self.chain()
        self.assertEqual((chain.declaration_changed, chain.masks_compiled), (False, True))
        self.assertIs(self.state(), access.MaskState.CURRENT)

    def test_c_without_an_editable_version_nothing_is_done(self) -> None:
        """RF-009-21: sin versión (``core.version_required``), con una que no existe (``core.version_unknown``)
        o no editable (``core.version_not_editable``), la cadena se rechaza al avanzar y no escribe nada."""
        before = self.written()
        for version, code in ((None, "core.version_required"), ("V99", "core.version_unknown")):
            with self.subTest(version=version), self.assertRaises(versions_model.VersionError) as caught:
                ops.finish(entity_store.after_entity_change(self.project, version))
            self.assertEqual(caught.exception.code, code)
        with self.project.write_transaction() as conn:
            conn.execute("UPDATE gb_version SET status = 'VIGENTE' WHERE uid = ?", (self.v2.uid,))
            conn.execute("UPDATE gb_version SET status = 'SUPERADO', reason_closed = ? WHERE uid = ?",
                         ("Prueba de la T19", self.v2.uid))
        with self.assertRaises(versions_model.VersionError) as caught:
            ops.finish(entity_store.after_entity_change(self.project, self.v2))
        self.assertEqual(caught.exception.code, "core.version_not_editable")
        self.assertEqual(json.dumps(self.written(), default=str), json.dumps(before, default=str))


class FrozenChainTest(ChainCase):
    """RF-015-16, RF-009-19, RF-015-10 (T27): lo **vigente** de la versión sigue siéndolo aunque lo registrara una
    revisión que luego se congeló, y la 008 lo marca obsoleto en la revisión abierta; la cadena lo cuenta entre
    «lo que quedó obsoleto» (antes filtraba por la revisión abierta y no contaba lo congelado)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())
        cls.chain()
        cls.clock.advance(minutes=1)
        with cls.project.write_transaction() as conn:  # P1, ya hecha, pasa a la revisión congelada V01.r1
            freeze_rows(conn, cls.v1, now=cls.clock.now().isoformat(timespec="seconds"), reason="Siguiente")

    def test_a_what_is_live_in_the_frozen_revision_is_counted_with_what_became_obsolete(self) -> None:
        """RF-015-16, RF-009-19: P1 (en V01.r1, congelada, y vigente) usó las máscaras; P2 (que protege, creada en
        la revisión abierta) cambia las máscaras al declarar: la cadena da obsoletas **las dos**, P1 con la causa de
        las máscaras, y V01.r1 no cambia (sigue congelada, con los mismos elementos)."""
        revision = self.query("SELECT uid FROM gb_revision WHERE version_uid = ? AND state = 'frozen'",
                              self.v1.uid)[0][0]
        items = self.query("SELECT * FROM gb_revision_item WHERE revision_uid = ? ORDER BY fid", revision)
        self.made(prep.request(WORKSHOP, start="entity:PLT-001", protect=True, guard_m=GUARD_M))
        chain = self.chain()
        self.assertEqual((chain.declared, chain.masks_compiled), (1, True))
        self.assertEqual(sorted(item.name for item in chain.obsolete), sorted([LOADING, WORKSHOP]))
        self.assertEqual({kind for kind, _name in self.stale_causes(self.current("PLT-001"))}, {CAUSE_DATASET})
        self.assertEqual(self.query("SELECT state FROM gb_revision WHERE uid = ?", revision), [("frozen",)])
        self.assertEqual(self.query("SELECT * FROM gb_revision_item WHERE revision_uid = ? ORDER BY fid",
                                    revision), items, "lo congelado no cambia")
