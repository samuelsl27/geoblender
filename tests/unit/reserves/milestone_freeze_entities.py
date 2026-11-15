# SPDX-License-Identifier: GPL-3.0-or-later
"""Pruebas de hito de «test_freeze_entities» (spec 015, T48; plan 015 §7.4): las clases que pesan,
movidas sin cambiar una aserción. El «verde» deja en ``test_freeze_entities`` las más ligeras de cada
requisito; las de aquí las ejecuta el paso «hito» de ``tools/check.py --completo`` (la publicación
lo pide siempre).
"""

from __future__ import annotations

import dataclasses

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import constraints_project as cp
from tests.support import entity_fixtures as efx
from tests.support import quarry_fixtures as qfx
from tests.support import res_fixtures
from tests.unit.design import test_entity_supports as sup
from tests.unit.design import test_fill_only_operation as fill_test
from tests.unit.reserves.test_freeze_entities import (
    CHAIN,
    EntityState,
    FreezeCase,
    ItemKind,
    NEW_OUTSIDE_LOCAL,
    NEW_TOP_M,
    PSF1,
    PSF2,
    PSF3,
    THICKNESS_M,
    TWIN_SURFACE,
    access,
    compliance,
    cstore,
    design_store,
    entities,
    entity_store,
    freeze,
    geotiff_reader,
    gis,
    provenance,
    unchecked,
)


class FreezeChainTest(FreezeCase):
    """RF-015-04, RF-012-25 (P-2): P1 → P2 → P3 y «Balsa 2», en el orden de las pruebas: (a) solo la última, (b) con la
    de la 014, (c) las intermedias a petición, (d) una verificación sustituida, (e) sin calcular, (f) la de la última
    hecha y (g) congelar."""

    def test_a_three_chained_platforms_freeze_asks_to_check_only_the_last(self) -> None:
        """RF-015-04, RF-012-25, P-2: con tres plataformas encadenadas (P1 del terreno, P2 de la superficie de P1, P3 de
        la de P2), congelar pide verificar **solo la última**: su superficie, sobre su dato y con la nota de siempre;
        P1 y P2, que llevan el papel ``entity_surface`` y no ``design_surface``, son de trabajo y no se piden."""
        registry = entities.registry(self.project, self.v1.uid)
        self.assertEqual([entry.record.state for entry in registry], [EntityState.CURRENT] * 3)
        self.assertEqual([tail.code for tail in entities.chain_tails(registry.records)], ["PLT-003"])
        roles = self.roles()
        self.assertEqual({roles[name] for name in CHAIN}, {provenance.ENTITY_SURFACE_ROLE})
        self.assertEqual(roles[TWIN_SURFACE], provenance.DESIGN_SURFACE_ROLE)
        found = self.findings()
        self.assertEqual([name for name in CHAIN if name in found], [PSF3])
        entry = found[PSF3]
        self.assertEqual((entry.item_kind, entry.item_uid, entry.finding),
                         (ItemKind.DATASET, self.record(PSF3, self.v1).uid, unchecked(PSF3)))
        self.assertTrue(self.plan().needs_acceptance)

    def test_b_a_chain_and_a_design_surface_of_the_014_count_both(self) -> None:
        """RF-015-04, RF-012-25, RF-013-31: la cadena de entidades y la superficie de diseño de la 014 («Balsa 2», con
        el papel ``design_surface``) **cuentan las dos**, cada una una vez y con la nota de siempre; nada más (ni la
        envolvente, ni las tablas de las entidades, ni sus informes)."""
        found = self.findings()
        self.assertEqual(set(found), {PSF3, TWIN_SURFACE})
        self.assertEqual({entry.finding for entry in found.values()}, {unchecked(PSF3), unchecked(TWIN_SURFACE)})
        self.assertEqual([entry.item_kind for entry in found.values()], [ItemKind.DATASET] * 2)
        self.assertEqual(self.findings(self.v2), {}, "los datos son de la versión")

    def test_c_an_intermediate_is_checked_on_request_and_registers_its_compliance_like_a_design_surface(self) -> None:
        """RF-015-04, RF-012-21, RF-012-24: la orden de la 012 **acepta la superficie de una entidad que no es la
        última** (P1 y P2, ``entity_surface``) como final: la verifica por recinto, registra su cumplimiento (la
        operación vigente con la superficie como entrada ``final_1`` y su tabla) como la de una de diseño, y no pide
        nada más al congelar: la lista no cambia (la última y la de la 014 siguen sin verificar)."""
        for name, final in (("Revisión de P1", PSF1), ("Revisión de P2", PSF2)):
            result = self.check(name, final)
            self.assertEqual(result.fails, (False,), name)
            with self.project.read() as conn:
                self.assertIn(name, cstore.verification_names(conn, self.v1.uid))
            self.assertEqual(self.query(
                "SELECT d.name FROM gb_operation AS o JOIN gb_operation_io AS io ON io.operation_uid = o.uid "
                "JOIN gb_dataset AS d ON d.uid = io.item_uid WHERE o.op_type = ? AND o.status = 'done' AND "
                "o.superseded_by IS NULL AND io.direction = 'in' AND io.role = 'final_1' AND o.settings LIKE ?",
                cstore.VERIFY, f'%"{name}"%'), [(final,)])
        self.assertEqual(set(self.findings()), {PSF3, TWIN_SURFACE})

    def test_d_a_replaced_check_of_an_intermediate_does_not_make_it_asked(self) -> None:
        """RF-015-04, RF-012-25 (013 D-28): repetida la verificación de P1 **sin** su superficie, esta, que fue final
        de una sustituida, **no se pide** (es de trabajo, no de diseño: lo que la regla de las sustituidas busca es
        una superficie de diseño que se deja sin verificar); la última de la cadena y la de la 014 siguen pidiéndose."""
        grid = self.grid
        raised = qfx.terrain(grid).copy()
        res_fixtures.write_grids(self.project, [("otra", gis.Raster(grid, raised, efx.CRS, efx.VERTICAL))],
                                 message="Otra superficie, para sustituir la verificación")
        self.check("Revisión de P1", "gis_dtm_otra")
        found = self.findings()
        self.assertNotIn(PSF1, found)
        self.assertEqual(set(found), {PSF3, TWIN_SURFACE})

    def test_e_entities_brought_to_another_version_without_calculating_do_not_count(self) -> None:
        """RF-015-04, RF-015-18: las tres entidades traídas a V02 quedan **sin calcular** (parámetros, sin superficie):
        no hay nada que verificar y congelar V02 no pide nada; V01 sigue igual."""
        before = self.findings()
        found = entity_store.bring_entities(self.project, "V01", "V02", codes=["PLT-001", "PLT-002", "PLT-003"])
        self.assertEqual(len(found.entities), 3)
        states = {entry.record.state for entry in entities.registry(self.project, self.v2.uid)}
        self.assertEqual(states, {EntityState.UNCALCULATED})
        self.assertEqual([tail.code for tail in entities.chain_tails(
            entities.registry(self.project, self.v2.uid).records)], ["PLT-003"])
        self.assertEqual(self.findings(self.v2), {})
        self.assertEqual(set(self.findings()), set(before))

    def test_f_with_the_check_of_the_last_done_the_chain_asks_for_nothing(self) -> None:
        """RF-015-04, RF-012-25: verificada la última (P3, final de una verificación vigente que cumple), su superficie
        ya no se lista ni la verificación pide nada; verificada también la de la 014, **congelar no pide aceptar
        nada**."""
        result = self.check("Revisión de P3", PSF3)
        self.assertEqual(result.fails, (False,))
        self.assertEqual(set(self.findings()), {TWIN_SURFACE})
        self.check("Revisión de Balsa 2", TWIN_SURFACE)
        self.assertEqual(self.findings(), {})
        self.assertFalse(self.plan().needs_acceptance)

    def test_g_freezing_goes_ahead_without_accepting_anything(self) -> None:
        """RF-015-04, RF-012-25: con todo verificado, congelar V01 procede **sin aceptación**: V01.r1 se congela y no
        lleva ninguna nota de verificación pendiente."""
        self.clock.advance(minutes=1)
        frozen = sup.finish(freeze.freeze_steps(self.project, self.v1.uid, reason="Entrega de la prueba"))
        self.assertEqual(self.query("SELECT state FROM gb_revision WHERE uid = ?", str(frozen.frozen.uid)),
                         [("frozen",)])
        self.assertNotIn("finding", str(frozen.frozen.accepted))
        self.assertEqual(self.findings(), {})


class FreezeNewLimitTest(FreezeCase):
    """RF-015-04, RF-012-21, RF-012-22, RF-012-25, RF-014-26 (P-9), en el orden de las pruebas: P3 verificada y,
    después, el límite legal redibujado más corto por el norte: (a) lo de la 014 no ve la plataforma, (b) la
    verificación vigente queda obsoleta y (c) repetida avisa de lo que P3 mueve fuera del límite."""

    CHECK = "Revisión de P3"

    def cut_outside_by_hand(self) -> float:
        """Los m³ de corte de P3 frente al terreno fuera del límite legal nuevo, **de los ficheros y a mano**: las
        celdas donde baja más que el espesor mínimo y que están al norte del paralelo del límite."""
        grid = self.grid
        ground = geotiff_reader.read_geotiff(self.root / self.record(fill_test.START).locator).values
        final = geotiff_reader.read_geotiff(self.root / self.record(PSF3, self.v1).locator).values
        with np.errstate(invalid="ignore"):
            cut = ground - final
            counted = (cut > THICKNESS_M) & qfx.in_box(NEW_OUTSIDE_LOCAL, grid)
        return float(cut[counted].sum()) * grid.dx * grid.dy

    def test_a_the_check_of_the_014_does_not_see_the_platform_and_the_last_one_is_checked(self) -> None:
        """RF-014-26, P-9: «Ajustar el diseño a un límite nuevo» y la comprobación de la 014 trabajan sobre las
        superficies ``design_surface`` de sus tipos de operación: **no ven la superficie de la plataforma** (ni con el
        tipo de la plataforma); la verificación de P3, con el límite de siempre, cumple y no pide nada."""
        with self.project.read() as conn:
            listed = design_store.limit_surfaces(
                conn, self.v1.uid, types=(*design_store.LIMIT_CHECKED_TYPES, *design_store.REFIT_SOURCES,
                                          provenance.PLATFORM))
            platform = design_store.limit_surfaces(conn, self.v1.uid, types=(provenance.PLATFORM,))
        self.assertTrue(listed, "la superficie de la 014 sí se ve")
        self.assertEqual(platform, ())
        self.assertFalse({origin.record.name for origin in listed} & set(CHAIN))
        result = self.check(self.CHECK, PSF3)
        self.assertEqual(result.fails, (False,))
        self.assertEqual(set(self.findings()), {TWIN_SURFACE})

    def test_b_a_new_limit_leaves_the_check_of_the_last_stale_and_listed(self) -> None:
        """RF-012-25, P-9: redibujado el límite legal más corto por el norte, las máscaras quedan obsoletas y la
        verificación de P3, que las usa, **obsoleta**: congelar la lista (con su nombre y por obsoleta) y no lista de
        nuevo la superficie de P3 (es su final)."""
        (legal,) = [item for item in self.stored_constraints() if item.code == "concesion"]
        self.clock.advance(minutes=1)
        cp.edit_constraints(self.project, [dataclasses.replace(
            legal, parts=((cfx.rectangle(qfx.LEGAL_LOCAL[0], qfx.LEGAL_LOCAL[1], qfx.LEGAL_LOCAL[2], NEW_TOP_M),),))])
        self.assertEqual(access.mask_state(self.project, self.v1.uid)[0], access.MaskState.STALE)
        found = self.findings()
        self.assertIn(self.CHECK, found)
        self.assertIn(f"La verificación «{self.CHECK}» está obsoleta", found[self.CHECK].finding)
        self.assertNotIn(PSF3, found)

    def test_c_the_check_repeated_warns_of_what_the_platform_moves_outside_the_new_limit(self) -> None:
        """RF-012-21, RF-012-22, RF-012-25, P-9, error 46: repetida la verificación de P3 con el límite nuevo (las
        máscaras se compilan de nuevo), **da «no cumple» fuera del límite legal** con los m³ de corte de P3 al norte
        del límite nuevo (a ≤ 10⁻⁹ relativo de la cuenta a mano de los ficheros), y congelar **lo avisa**: la nota de
        la verificación nombra el recinto y esos m³; la superficie de P3 no se lista aparte (es final de una
        vigente). (P3 se calculó con el límite de antes y sigue obsoleta: a la nota de «no cumple» se suma la de
        «obsoleta», que no se comprueba aquí.)"""
        expected = self.cut_outside_by_hand()
        self.assertGreater(expected, 0.0, "P3 corta al norte del límite nuevo")
        result = self.check(self.CHECK, PSF3)
        self.assertEqual(result.fails, (True,))
        (final,) = result.finals
        outside = final.zone(compliance.OUTSIDE_LEGAL)
        self.assertEqual((outside.verdict, outside.counts), (compliance.Verdict.FAILS, compliance.Counts.CUT))
        self.assertAlmostEqual(outside.counted_m3, expected, delta=1e-9 * expected)
        found = self.findings()
        self.assertEqual(found[self.CHECK].item_kind, ItemKind.OPERATION)
        note = found[self.CHECK].finding
        self.assertIn(f"La verificación «{self.CHECK}» no cumple en la final «{PSF3}»", note)
        self.assertIn("fuera del límite legal", note)
        self.assertIn(cstore._volume_text(outside.counted_m3) + " m³ de corte", note)
        self.assertNotIn(PSF3, found)
        self.assertTrue(self.plan().needs_acceptance)
