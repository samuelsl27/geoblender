# SPDX-License-Identifier: GPL-3.0-or-later
"""Pruebas de hito de «test_entity_dependents» (spec 015, T48; plan 015 §7.4): las clases que pesan,
movidas sin cambiar una aserción. El «verde» deja en ``test_entity_dependents`` las más ligeras de cada
requisito; las de aquí las ejecuta el paso «hito» de ``tools/check.py --completo`` (la publicación
lo pide siempre).
"""

from __future__ import annotations

import time

from tests.support import entity_fixtures as efx
from tests.support import quarry_fixtures as qfx
from tests.support import res_fixtures
from tests.unit.design import test_entity_supports as sup
from tests.unit.design import test_fill_only_operation as fill_test
from tests.unit.design import test_platform_operation as ops_test
from tests.unit.design import test_platform_prepare as prep
from tests.unit.design.test_entity_dependents import (
    BALSA,
    DRAG,
    DependentsCase,
    EPR1,
    EPR2,
    EntityState,
    FILL_M,
    GRADIENT,
    LABEL,
    ON_TOP,
    PSF1,
    PSF2,
    PSF_FIRST,
    TWIN,
    TWIN_SURFACE,
    core_params,
    dataset_registry,
    design_params,
    entities,
    freeze,
    gis,
    operations,
    provenance,
    recompute_mod,
    reproduce_mod,
)


class DependentsTest(DependentsCase):
    """RF-015-15, RF-015-16, RF-008-24, RF-008-26, RF-009-19, CE-015-05, en el orden de las pruebas: (a) la lista
    de lo que se apoya en una entidad y de en qué se apoya, **sin cambiar nada**; después (b) cambiar la pendiente
    de P1, (c) «Recalcular lo obsoleto», (d) congelar V01.r1, cambiar otra vez y comprobar lo congelado, (e)
    cambiar una entrada (el terreno) y (f) descartar P1."""

    def ops(self) -> dict[str, str]:
        """La operación vigente de cada cosa de la historia, por su nombre."""
        return {"P1": self.current("PLT-001"), "P2": self.current("PLT-002"), "P3": self.current("PLT-003"),
                "twin": self.fill_uid(), "check": self.check_uid()}

    def test_a_what_rests_on_the_first_platform_is_one_list_with_name_type_and_volume(self) -> None:
        """RF-015-15, D-11, ADR-0030 §4: sobre P1 hay **una sola lista**, por orden de registro: P2 (una
        plataforma que parte de su superficie **y** rellena sobre ella: los dos papeles) y el «solo relleno»
        «Balsa 2» de la 014 (solo ``supported_on``); cada una con su nombre, su tipo y el volumen apoyado: el de
        P2, **a mano** (2 m sobre las celdas de la huella de P1, de 4 m²), y el de «Balsa 2», el de los
        ficheros (``r − máx(s, e)``), a ≤ 10⁻⁹ relativo; las dos al día."""
        found = entities.dependents(self.project, self.v1.uid, "PLT-001")
        self.assertEqual(self.listed("PLT-001"),
                         [(ON_TOP, "des.platform", "PLT-002", ("supported_on", "surface")),
                          (TWIN, "des.fill_only", None, ("supported_on",))])
        on_top_row, twin_row = found
        self.assertEqual((on_top_row.operation_uid, twin_row.operation_uid),
                         (self.current("PLT-002"), self.fill_uid()))
        self.assertEqual((on_top_row.state, twin_row.state), (EntityState.CURRENT, EntityState.CURRENT))
        by_hand = FILL_M * self.cells_of(EPR1) * sup.CELL_M2
        self.assertGreater(by_hand, 0.0)
        self.assertLessEqual(abs(on_top_row.volume_m3 - by_hand) / by_hand, 1e-9)
        oracle = self.by_hand(TWIN_SURFACE, qfx.terrain(self.grid), PSF1, EPR1)
        self.assertGreater(oracle, 100.0)
        self.assertLessEqual(abs(twin_row.volume_m3 - oracle) / oracle, 1e-9)
        self.assertEqual(on_top_row.volume_m3, self.volumes_of(on_top_row.operation_uid)["PLT-001"])

    def test_a_a_platform_that_only_starts_from_the_surface_has_no_volume(self) -> None:
        """RF-015-15: sobre P2 están P3, que **solo parte de su superficie** (sin volumen: ni ``supported_on`` ni
        cifra) y «Balsa 2», que rellena sobre ella (con el suyo, el de los ficheros, a ≤ 10⁻⁹ relativo);
        sobre P3 no hay nada."""
        found = entities.dependents(self.project, self.v1.uid, "PLT-002")
        self.assertEqual(self.listed("PLT-002"), [(DRAG, "des.platform", "PLT-003", ("surface",)),
                                                  (TWIN, "des.fill_only", None, ("supported_on",))])
        self.assertIsNone(found[0].volume_m3)
        oracle = self.by_hand(TWIN_SURFACE, qfx.terrain(self.grid), PSF2, EPR2)
        self.assertLessEqual(abs(found[1].volume_m3 - oracle) / oracle, 1e-9)
        self.assertEqual(entities.dependents(self.project, self.v1.uid, "PLT-003"), ())

    def test_a_the_entity_is_asked_by_code_or_by_name_and_the_unknown_is_a_program_error(self) -> None:
        """RF-015-15: el código manda y el nombre vale (como ``registry.get``); una entidad que no es de la
        versión es un error del programa (``ValueError``), no una lista vacía; la versión, por uid o código."""
        self.assertEqual(entities.dependents(self.project, self.v1.code, BALSA),
                         entities.dependents(self.project, self.v1.uid, "PLT-001"))
        with self.assertRaises(ValueError):
            entities.dependents(self.project, self.v1.uid, "PLT-009")
        with self.assertRaises(ValueError):
            entities.dependencies_of(self.project, self.v1.uid, "PLT-009")

    def test_a_in_what_an_entity_rests_on_is_its_start_and_what_it_rests_on(self) -> None:
        """RF-015-15, D-11: «en qué se apoya» P2 es P1, por los dos papeles y con los mismos m³ de la otra lista;
        P3 parte de la superficie de P2 y no se apoya en ella (sin volumen); P1 parte del terreno, que no es
        una entidad (su nombre es el del dato, sin volumen, y no hay entidad)."""
        (rests,) = entities.dependencies_of(self.project, self.v1.uid, "PLT-002")
        self.assertEqual((rests.name, rests.op_type, rests.entity, rests.roles, rests.state),
                         (BALSA, "des.platform", "PLT-001", ("supported_on", "surface"),
                          EntityState.CURRENT))
        self.assertEqual(rests.operation_uid, self.current("PLT-001"))
        self.assertEqual(rests.volume_m3, entities.dependents(self.project, self.v1.uid, "PLT-001")[0].volume_m3)
        (starts,) = entities.dependencies_of(self.project, self.v1.uid, "PLT-003")
        self.assertEqual((starts.name, starts.entity, starts.roles, starts.volume_m3),
                         (ON_TOP, "PLT-002", ("surface",), None))
        (terrain,) = entities.dependencies_of(self.project, self.v1.uid, "PLT-001")
        self.assertEqual((terrain.name, terrain.entity, terrain.roles, terrain.volume_m3),
                         (fill_test.START, None, ("surface",), None))

    def test_a_the_line_of_the_list_says_name_type_and_volume_in_both_languages(self) -> None:
        """RF-015-15 (la lista que enseñará la barra N y el descarte, T25 y T28): una línea por fila, con el
        nombre, el tipo (el de la operación, traducido) y los m³ o, sin volumen, «superficie de partida»."""
        on_top_row, twin_row = entities.dependents(self.project, self.v1.uid, "PLT-001")
        shown = on_top_row.text("es")
        self.assertTrue(shown.startswith(f"{ON_TOP} (Plataforma): "), shown)
        self.assertIn("m³", shown)
        self.assertIn("Solo relleno", twin_row.text("es"))
        self.assertIn("Fill only", twin_row.text("en"))
        (start,) = [row for row in entities.dependents(self.project, self.v1.uid, "PLT-002")
                    if row.entity == "PLT-003"]
        self.assertEqual(start.text("es"), f"{DRAG} (Plataforma): superficie de partida")
        self.assertEqual(start.text("en"), f"{DRAG} (Platform): start surface")

    def test_b_changing_a_parameter_of_the_first_platform_stales_all_that_depends_on_it_with_the_cause(self) -> None:
        """RF-015-16, RF-008-24, CE-015-05: cambiar la pendiente de P1 deja obsoletas **con la misma causa raíz**
        (``parameter_changed`` de la clave de P1, no de las suyas) a P1, a P2 (que parte de su superficie), a P3
        (de la de P2), a «Balsa 2» (que se apoya en las dos) y a la verificación (que usa la superficie de P2): el
        registro de las entidades las da obsoletas, con la causa, y lista de dependencias da a P2 y a «Balsa
        2» obsoletas."""
        ops = self.ops()
        for uid in ops.values():
            self.assertEqual(self.stale_causes(uid), set(), "antes de cambiar nada, todo al día")
        self.assertEqual(self.recompute_plan(), [])
        self.change(GRADIENT, 0.5)
        for name, uid in ops.items():
            self.assertEqual(self.stale_causes(uid), {("parameter_changed", GRADIENT)}, name)
        registry = entities.registry(self.project, self.v1.uid)
        self.assertEqual([entry.record.state for entry in registry], [EntityState.STALE] * 3)
        for entry in registry:
            self.assertEqual({cause.kind for cause in entry.causes}, {"parameter_changed"})
        listed = entities.dependents(self.project, self.v1.uid, "PLT-001")
        self.assertEqual([row.state for row in listed], [EntityState.STALE, EntityState.STALE])
        self.assertEqual([row.state for row in entities.dependents(self.project, self.v1.uid, "PLT-002")],
                         [EntityState.STALE, EntityState.STALE])
        self.assertTrue(all(row.causes for row in listed))

    def test_b_the_reason_names_the_entity_that_changed_and_what_changed(self) -> None:
        """RF-015-16: el motivo legible (``stale_reason``) es el «Obsoleto: cambió …» de la 008 con **la entidad**
        que cambió —su nombre, «Plataforma de la balsa», no su código ``plt_001``— y lo que cambió (la pendiente
        de su rasante); el mismo para P1 y para P2, que está obsoleta por P1; en inglés, con el texto de la 008 en
        inglés; ``operation_reason`` lo da de una operación que no es una entidad (el «solo relleno» y la
        verificación, que usan la superficie de P2)."""
        wanted = f"Obsoleto: cambió {LABEL} · {BALSA}"
        for code in ("PLT-001", "PLT-002", "PLT-003"):
            self.assertEqual(entities.stale_reason(self.project, self.v1.uid, code), wanted, code)
        self.assertEqual(entities.stale_reason(self.project, self.v1.uid, ON_TOP), wanted, "por su nombre")
        ops = self.ops()
        for name in ("twin", "check"):
            self.assertEqual(entities.operation_reason(self.project, self.v1.uid, ops[name]), wanted, name)
        self.assertNotIn("plt_001", wanted)
        self.assertEqual(entities.stale_reason(self.project, self.v1.uid, "PLT-002", language="en"),
                         f"Stale: Gradient of the platform · {BALSA} changed")
        self.assertEqual(entities.stale_reason(self.project, self.v1.uid, "PLT-002", language="en"),
                         entities.stale_reason(self.project, self.v1.uid, "PLT-002", language="en"))

    def test_b_what_is_up_to_date_has_no_reason(self) -> None:
        """RF-015-16: una entidad al día (o sin calcular) no tiene motivo: ``None``; una entidad que no es de la
        versión, un error del programa."""
        with self.assertRaises(ValueError):
            entities.stale_reason(self.project, self.v1.uid, "PLT-009")
        with self.assertRaises(ValueError):
            entities.operation_reason(self.project, self.v1.uid, "no-es-una-operacion")

    def test_c_recomputing_goes_in_dependency_order_and_leaves_everything_up_to_date(self) -> None:
        """RF-015-16, RF-008-24, RF-008-26: el plan de «Recalcular lo obsoleto» pone P1 primero, después P2 (que
        parte de su superficie) y lo que depende de las dos (P3, «Balsa 2» y la verificación, en su orden de
        registro): **orden de dependencia**; recalculadas, cada una sustituye a la suya, no queda nada obsoleto,
        las dos listas dan la operación nueva de cada una, los m³ apoyados se **miden otra vez** sobre las
        superficies nuevas (a ≤ 10⁻⁹ relativo de la mano) y el motivo vuelve a ser ``None``."""
        ops = self.ops()
        order = [unit[0] for unit in self.plan_units()]
        self.assertEqual(order[:2], [ops["P1"], ops["P2"]])
        self.assertEqual(sorted(order[2:]), sorted([ops["P3"], ops["twin"], ops["check"]]))
        self.assertEqual(len(order), 5)
        before = entities.dependents(self.project, self.v1.uid, "PLT-001")[0].volume_m3
        self.clock.advance(minutes=1)
        outcome = sup.finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual([result.status for result in outcome.results],
                         [recompute_mod.UnitStatus.DONE] * 5)
        made = [result.operations[0] for result in outcome.results]
        self.assertEqual([old for (old,) in self.query(
            "SELECT supersedes_uid FROM gb_operation WHERE uid IN (?, ?, ?, ?, ?) ORDER BY fid", *made)],
            order)
        self.assertEqual(self.recompute_plan(), [])
        self.assertEqual(self.ops(), {name: made[order.index(uid)] for name, uid in ops.items()})
        for code in ("PLT-001", "PLT-002", "PLT-003"):
            self.assertIsNone(entities.stale_reason(self.project, self.v1.uid, code))
        listed = entities.dependents(self.project, self.v1.uid, "PLT-001")
        self.assertEqual([row.operation_uid for row in listed], [self.current("PLT-002"), self.fill_uid()])
        self.assertEqual([row.state for row in listed], [EntityState.CURRENT] * 2)
        now = FILL_M * self.cells_of(EPR1) * sup.CELL_M2
        self.assertLess(listed[0].volume_m3, now, "la rasante de P1 sube: P2 rellena algo menos sobre ella")
        oracle = self.by_hand(provenance.dataset_name("psf", ON_TOP), self.grid_of(PSF1), PSF1, EPR1)
        self.assertLessEqual(abs(listed[0].volume_m3 - oracle) / oracle, 1e-9)
        self.assertNotEqual(listed[0].volume_m3, before)
        twin = self.by_hand(TWIN_SURFACE, qfx.terrain(self.grid), PSF1, EPR1)
        self.assertLessEqual(abs(listed[1].volume_m3 - twin) / twin, 1e-9)

    def test_d_freezing_then_changing_marks_what_is_live_and_nothing_of_the_frozen_revision(self) -> None:
        """RF-015-16, RF-009-19, RF-009-11: congelada V01.r1, cambiar la pendiente de P1 otra vez deja obsoleto
        **lo vivo** (lo «en curso» de la revisión abierta: P1, P2, P3, «Balsa 2» y la verificación, cada una con
        su causa) y «Recalcular lo obsoleto» lo rehace en orden **dentro de la revisión abierta**; la revisión
        congelada **no cambia**: sigue congelada, con los mismos elementos y las mismas operaciones con los
        mismos hash, y se reproduce otra vez igual."""
        self.clock.advance(minutes=1)
        frozen = sup.finish(freeze.freeze_steps(self.project, self.v1.uid, reason="Entrega de la prueba"))
        revision = str(frozen.frozen.uid)
        self.clock.advance(minutes=1)
        items = self.query("SELECT * FROM gb_revision_item WHERE revision_uid = ? ORDER BY fid", revision)
        self.assertTrue(items)
        ops = self.ops()
        hashes = {uid: self.hashes_of(uid) for uid in ops.values()}
        self.assertIsNone(entities.stale_reason(self.project, self.v1.uid, "PLT-002"))
        self.assertEqual([(row.name, row.state) for row in entities.dependents(self.project, self.v1.uid, "PLT-001")],
                         [(ON_TOP, EntityState.CURRENT), (TWIN, EntityState.CURRENT)],
                         "lo registrado en la revisión congelada y vigente sigue siendo lo vigente («en curso»)")
        self.change(GRADIENT, 0.8)
        for name, uid in ops.items():
            self.assertEqual(self.stale_causes(uid), {("parameter_changed", GRADIENT)}, name)
        self.assertEqual(entities.stale_reason(self.project, self.v1.uid, "PLT-002"),
                         f"Obsoleto: cambió {LABEL} · {BALSA}")
        self.assertEqual(self.query("SELECT state FROM gb_revision WHERE uid = ?", revision), [("frozen",)])
        self.assertEqual(self.query("SELECT * FROM gb_revision_item WHERE revision_uid = ? ORDER BY fid",
                                    revision), items, "lo congelado no cambia")
        self.clock.advance(minutes=1)
        outcome = sup.finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual([result.status for result in outcome.results], [recompute_mod.UnitStatus.DONE] * 5)
        (opened,) = self.query("SELECT uid FROM gb_revision WHERE version_uid = ? AND state = 'open'",
                               self.v1.uid)[0]
        made = [result.operations[0] for result in outcome.results]
        self.assertEqual(self.query("SELECT revision_uid FROM gb_operation WHERE uid IN (?, ?, ?, ?, ?)",
                                    *made), [(opened,)] * 5)
        self.assertEqual({uid: self.hashes_of(uid) for uid in ops.values()}, hashes,
                         "las operaciones congeladas siguen con sus hash")
        self.assertEqual(self.query("SELECT * FROM gb_revision_item WHERE revision_uid = ? ORDER BY fid",
                                    revision), items)
        self.assertEqual(self.recompute_plan(), [])
        report = sup.finish(reproduce_mod.reproduce_steps(self.project, revision))
        self.assertTrue(all(check.same for check in report.outputs))
        self.assertTrue(all(check.same for check in report.figures))
        self.assertTrue(report.matches, report.not_reproducible)


    def test_e_changing_an_input_stales_the_entities_that_read_it_with_its_name(self) -> None:
        """RF-015-16, RF-008-24: cambiar **una entrada** (el terreno de partida, que reescribe un dato) deja
        obsoletas a las cinco con la misma causa raíz (``dataset_changed`` del terreno, también P2 y P3, que no
        lo leen: parten de la superficie de P1) y el motivo dice qué dato cambió; las listas las dan obsoletas."""
        shifted = gis.Raster(prep.GRID, qfx.terrain(prep.GRID) + 1.0, efx.CRS, efx.VERTICAL)
        self.clock.advance(minutes=1)
        res_fixtures.write_grids(self.project, [(fill_test.START.removeprefix("gis_dtm_"), shifted)],
                                 message="El terreno cambia")
        for name, uid in self.ops().items():
            self.assertIn(("dataset_changed", fill_test.START), self.stale_causes(uid), name)
        wanted = f"cambió «{fill_test.START}»"
        for code in ("PLT-001", "PLT-002", "PLT-003"):
            reason = entities.stale_reason(self.project, self.v1.uid, code)
            self.assertTrue(reason.startswith("Obsoleto: "), reason)
            self.assertIn(wanted, reason, code)
        self.assertIn(wanted, entities.operation_reason(self.project, self.v1.uid, self.check_uid()))
        self.assertEqual([row.state for row in entities.dependents(self.project, self.v1.uid, "PLT-001")],
                         [EntityState.STALE, EntityState.STALE])

    def test_f_discarding_the_first_platform_keeps_its_list_with_support_removed(self) -> None:
        """RF-015-15, RF-015-17 (la lista que enseña el descarte, T25): descartados los datos de P1 (nada se
        borra), P1 es «descartada»; P2 y «Balsa 2», que consumieron su superficie, quedan en «apoyo retirado» y
        **siguen en la lista** (con sus m³: el aviso de lo que se le apoyaba) y P3, que parte de P2, obsoleta; el
        motivo de P2 lo dice y la lista de «en qué se apoya» P2 da a P1 como descartada."""
        before = entities.dependents(self.project, self.v1.uid, "PLT-001")
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            for name in (PSF1, EPR1, provenance.dataset_name("prp", BALSA)):
                dataset_registry.set_status(conn, self.project, self.record(name, self.v1).uid, "discarded")
        states = {entry.record.code: entry.record.state
                  for entry in entities.registry(self.project, self.v1.uid)}
        self.assertEqual(states, {"PLT-001": EntityState.DISCARDED, "PLT-002": EntityState.SUPPORT_REMOVED,
                                  "PLT-003": EntityState.STALE})
        after = entities.dependents(self.project, self.v1.uid, "PLT-001")
        self.assertEqual([(row.name, row.volume_m3, row.roles) for row in after],
                         [(row.name, row.volume_m3, row.roles) for row in before])
        self.assertEqual([row.state for row in after], [EntityState.SUPPORT_REMOVED] * 2)
        self.assertIsNotNone(entities.stale_reason(self.project, self.v1.uid, "PLT-002"))
        (rests,) = entities.dependencies_of(self.project, self.v1.uid, "PLT-002")
        self.assertEqual((rests.entity, rests.state), ("PLT-001", EntityState.DISCARDED))


class ScaleTest(ops_test.RecomputeCase):
    """RNF-015-02: con **200 entidades** en la versión (la primera de verdad y 199 que se apoyan en
    ella, con su cifra; la segunda, además, parte de su superficie), las dos listas tardan ≤ 1 s en disco local: son una consulta
    de entradas y cifras, sin leer ninguna superficie."""

    ENTITIES = 200
    BY = "Samuel (IMGA)"

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())
        keys: dict[int, list[str]] = {}
        cls.clock.advance(minutes=1)
        store = core_params.ParameterStore(cls.project)
        with cls.project.write_transaction() as conn:
            for number in range(2, cls.ENTITIES + 1):
                code = f"PLT-{number:03d}"
                before = "entity:PLT-001" if number == 2 else f"entity:PLT-{number - 1:03d}"
                keys[number] = []
                for param, value in (("name", f"E{number}"), ("start", before)):
                    keys[number].append(design_params.entity_key(code, param))
                    store.create(conn, keys[number][-1], value, kind="ADOPTADO", source="Prueba de T24",
                                 source_kind="person", decided_by=cls.BY, reason="Prueba de T24",
                                 version=cls.v1.code)
        for number in range(2, cls.ENTITIES + 1):
            cls.synthetic(number, keys[number])

    @classmethod
    def synthetic(cls, number: int, keys: list[str]) -> None:
        """La operación de la entidad ``PLT-nnn`` (sintética: lee sus parámetros, consume la superficie de la
        primera como ``supported_on`` —y, la segunda, parte además del terreno, como ``surface``, que consume
        **antes**— y deja su cifra de lo apoyado; sin datos: la lista no los lee)."""
        name = f"E{number}"
        inputs = [operations.Use(PSF_FIRST, "supported_on")]
        if number == 2:
            inputs.insert(0, operations.Use(fill_test.START, "surface"))
        cls.clock.advance(seconds=1)
        handle = operations.begin_operation(
            cls.project, "des.platform", settings={"code": f"PLT-{number:03d}", "name": name}, params=keys,
            inputs=inputs, executor="blender", version=cls.v1.uid)
        with cls.project.write_transaction() as conn:
            handle.complete(conn, figures=provenance.supported_figures(name, {"PLT-001": float(number)}))

    def test_a_the_two_lists_of_200_entities_take_at_most_a_second(self) -> None:
        """RNF-015-02, RF-015-15: sobre P1 están las otras 199 (con el volumen de su cifra); «en qué se apoya» la
        última es P1 solo y la segunda, P1 y el terreno del que parte (lo que se apoya, antes que la partida,
        aunque la partida se registrara primero); cada lista (en frío, con la versión de 200 entidades) ≤ 1 s,
        sin leer ninguna superficie."""
        self.assertEqual(len(entities.registry(self.project, self.v1.uid)), self.ENTITIES)
        started = time.perf_counter()
        found = entities.dependents(self.project, self.v1.uid, "PLT-001")
        listing_s = time.perf_counter() - started
        started = time.perf_counter()
        rests = entities.dependencies_of(self.project, self.v1.uid, f"PLT-{self.ENTITIES:03d}")
        resting_s = time.perf_counter() - started
        self.assertEqual(len(found), self.ENTITIES - 1)
        self.assertEqual([row.entity for row in found],
                         [f"PLT-{number:03d}" for number in range(2, self.ENTITIES + 1)])
        self.assertEqual({row.roles for row in found}, {("supported_on",)})
        self.assertEqual([row.volume_m3 for row in found], [float(number) for number in range(2, self.ENTITIES + 1)])
        self.assertEqual([(row.entity, row.roles, row.volume_m3) for row in rests],
                         [("PLT-001", ("supported_on",), float(self.ENTITIES))])
        second = entities.dependencies_of(self.project, self.v1.uid, "PLT-002")
        self.assertEqual([(row.name, row.entity, row.roles, row.volume_m3) for row in second],
                         [(prep.LOADING, "PLT-001", ("supported_on",), 2.0),
                          (fill_test.START, None, ("surface",), None)])
        self.assertLessEqual(listing_s, 1.0, f"«lo que se apoya en E» con {self.ENTITIES} entidades")
        self.assertLessEqual(resting_s, 1.0, f"«en qué se apoya E» con {self.ENTITIES} entidades")

    def test_b_the_registry_reads_the_names_and_starts_in_a_few_queries(self) -> None:
        """RNF-015-06 (T45; la regresión de T38 que midió T49): con 200 entidades, el registro de la versión —lo que
        pregunta ``mask_state`` (``declaration_pending``) con cada activación de la vista previa— lee el nombre, la
        partida y el apoyo de todas con una consulta por trozo de claves, no con tres por entidad: una por entidad
        (la de su estado) y unas pocas más, menos de 2 por entidad (eran 1.404 con 200 entidades), y lo mismo que antes
        (nombre, partida y apoyo de cada una)."""
        with self.project.read() as conn:
            statements: list[str] = []
            conn.set_trace_callback(statements.append)
            try:
                registry = entities.registry(self.project, self.v1.uid, conn=conn)
            finally:
                conn.set_trace_callback(None)
        self.assertEqual(len(registry), self.ENTITIES)
        self.assertLess(len(statements), 2 * self.ENTITIES,
                        f"{len(statements)} sentencias para {self.ENTITIES} entidades")
        by_code = {entry.record.code: entry.record for entry in registry}
        self.assertEqual(by_code["PLT-001"].name, prep.LOADING)
        self.assertEqual((by_code["PLT-002"].name, by_code["PLT-002"].start), ("E2", "entity:PLT-001"))
        self.assertEqual((by_code["PLT-200"].name, by_code["PLT-200"].start), ("E200", "entity:PLT-199"))
        self.assertIsNone(by_code["PLT-200"].support)
