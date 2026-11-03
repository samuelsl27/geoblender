# SPDX-License-Identifier: GPL-3.0-or-later
"""Congelar con una superficie de diseño sin verificar (spec 013, T18; HU-013-6; RF-013-31,
RF-012-25; plan 013 §5.6, D-28; plan 012 D-29).

La comprobación de ``res`` al congelar (``reserves.compliance_store.freeze_findings``, registrada
con ``core.versions.freeze.register_freeze_check``) reconoce el papel ``design_surface`` que
``design.provenance`` pone a la superficie del escalonado y la lista, con la misma nota que a la
que fue final de una verificación sustituida, mientras la versión no tenga una verificación al día
que la incluya como final. Sobre el proyecto del diseño (una copia por clase) y con el cálculo
real de ``design`` (una envolvente y un escalonado en V01), en el orden de las pruebas:

- **a**: sin escalonado ni verificación no hay nada que listar (ni en V01 ni en V02).
- **b**: con el escalonado, y sin verificar, se lista su superficie de diseño y solo ella (no la
  envolvente, ni la rejilla de bermas, ni las tablas), sobre su dato y en V01 (los datos son de la
  versión: V02 no lista nada).
- **c**: verificada como final de una verificación vigente, ya no se lista.
- **d**: con esa verificación obsoleta se lista la verificación por obsoleta, no la superficie
  (que no se repite).
- **e**: si la verificación se repite sin la superficie, se lista una sola vez (la sustituida y el
  papel dan la misma entrada, sin duplicar).
- **f**: sin aceptarla no se congela; aceptada, V01.r1 se congela con su nota y la revisión abierta
  sigue listándola.
- **g**: descartada la superficie, ya no se lista.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import design_fixtures as dfx
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered

store = import_geoblender("design.store")
provenance = import_geoblender("design.provenance")
model = import_geoblender("design.model")
design_params = import_geoblender("design.params")
core_params = import_geoblender("core.params")
registry = import_geoblender("core.datasets.registry")
freeze = import_geoblender("core.versions.freeze")
versions_model = import_geoblender("core.versions.model")
raster_mod = import_geoblender("gis.raster")
res_provenance = import_geoblender("reserves.provenance")
surfaces = import_geoblender("reserves.surfaces")
cstore = import_geoblender("reserves.compliance_store")

ItemKind = versions_model.ItemKind
ItemState = versions_model.ItemState

SURFACE = dfx.START_DATASET
PROFILE = "expl_10_60_6"
PROFILE_VALUES = {"height_m": 10.0, "face_deg": 60.0, "berm_m": 6.0, "anchor_m": 125.0,
                  "mesh_factor": 1.0}
BY_HAND = {"source": "Perfil de prueba", "source_kind": "person", "decided_by": "Samuel (IMGA)"}
ENVELOPE_NAME = "Hueco inicial"
DESIGN_NAME = "Diseño inicial"
DESIGN_SURFACE = provenance.dataset_name(provenance.DESIGN_GRID, DESIGN_NAME)
CHECK = "Revisión del diseño"
THICKNESS = "res.verify.min_thickness_m"
BUDGET_S = 0.05
UNCHECKED = (f"«{DESIGN_SURFACE}» es una superficie de diseño sin verificación al día: "
             "ninguna verificación vigente la incluye.")


def _never(request: Any) -> Any:
    raise AssertionError("las pruebas de congelar no recalculan ni reproducen")


def definitions() -> tuple[Any, ...]:
    """Lo que declaran ``des`` y ``res`` a la procedencia, como lo registrará ``bl``."""
    return (*provenance.operation_defs({t: _never for t in provenance.REPRODUCIBLE},
                                       {t: _never for t in provenance.REPRODUCIBLE}),
            *provenance.FIGURES,
            cstore.operation_def(_never, cstore.REPRODUCE[cstore.VERIFY]), *cstore.FIGURES)


def last(steps: Iterator[Any]) -> Any:
    """El último ``Progress`` de unos pasos."""
    found = None
    for found in steps:
        pass
    return found


class DesignSurfaceFreezeTest(dfx.DesignProjectCase):
    """RF-013-31, RF-012-25 (D-28): lo que ``res`` pide aceptar al congelar V01 de una superficie de
    diseño, en el orden de las pruebas (el proyecto es de la clase)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_definitions(design_params.DEFINITIONS)
        cls.addClassCleanup(core_params.unregister_definitions, "des")
        core_params.register_families(design_params.FAMILIES)
        cls.addClassCleanup(core_params.unregister_families, "des")
        core_params.register_definitions(res_provenance.VERIFY_DEFINITIONS)
        cls.addClassCleanup(core_params.unregister_definitions, "res")
        cls.enterClassContext(registered(*definitions()))
        freeze.register_freeze_check(cstore.MODULE, cstore.freeze_findings)
        cls.addClassCleanup(freeze.unregister_freeze_checks, cstore.MODULE)
        cls.start = surfaces.SurfaceRef(dataset=SURFACE, label="Partida")
        cls.clock.advance(minutes=1)
        with cls.project.write_transaction() as conn:
            for param, value in PROFILE_VALUES.items():
                core_params.ParameterStore(cls.project).create(
                    conn, design_params.bench_key(PROFILE, param), value,
                    kind="ADOPTADO" if param == "mesh_factor" else "HIPÓTESIS",
                    reason="Perfil de prueba", **BY_HAND)

    # --- Ayudas -------------------------------------------------------------------------------

    def plan(self, version: Any = None) -> Any:
        return freeze.freeze_plan(self.project, (version or self.v1).uid)

    def findings(self, version: Any = None) -> dict[str, Any]:
        """Las entradas con nota del plan de congelar, por nombre."""
        return {entry.name: entry for entry in self.plan(version).accept if entry.finding}

    def calculate(self) -> None:
        """Calcula en V01 una envolvente y su escalonado (el cálculo real de ``design``)."""
        request = model.EnvelopeRequest(
            name=ENVELOPE_NAME, direction="down",
            seeds=model.SeedSource("surface", surface=SURFACE, zone=model.Zone("domain")),
            slope_mode="constant", slope_deg=35.0, metric="chamfer5", mesh_factor=1.0,
            reach_m=None, domain=model.WorkDomain())
        self.clock.advance(minutes=1)
        handle, steps = store.run_envelope(self.project, request, version=self.v1.uid)
        self.assertEqual(last(steps).result.handle.uid, handle.uid)
        design = model.DesignRequest(name=DESIGN_NAME, envelope=ENVELOPE_NAME, sense="cut",
                                     base_profile=PROFILE, sector_profiles={}, anchor_grid=None)
        self.clock.advance(minutes=1)
        handle, steps = store.run_design(self.project, design, SURFACE, version=self.v1.uid)
        self.assertEqual(last(steps).result.handle.uid, handle.uid)

    def verify(self, finals: Any) -> str:
        """Verifica en V01 la partida frente a ``finals`` (con el nombre de siempre: repetirlo
        sustituye a la anterior) y da el uid de la operación."""
        self.clock.advance(minutes=1)
        last(cstore.verify_project_steps(self.project, version=self.v1.uid, name=CHECK,
                                         start=self.start, finals=finals, budget_s=BUDGET_S))
        return self.query("SELECT uid FROM gb_operation WHERE op_type = ? ORDER BY fid DESC "
                          "LIMIT 1", cstore.VERIFY)[0][0]

    def design_ref(self) -> Any:
        return surfaces.SurfaceRef(dataset=DESIGN_SURFACE, label="Diseño")

    # --- La historia --------------------------------------------------------------------------

    def test_a_nothing_to_list_without_a_design(self) -> None:
        """RF-012-25, RF-013-31: sin escalonado ni verificación, nada que listar (V01 y V02)."""
        self.assertEqual((self.plan().accept, self.plan(self.v2).accept), ((), ()))

    def test_b_the_unchecked_design_surface_is_listed_and_only_it(self) -> None:
        """RF-013-31, RF-012-25 (D-28): calculado el escalonado y sin verificar, se lista su
        superficie de diseño (``des_srf_``, con el papel ``design_surface``) sobre su dato y con la
        nota de siempre; ni la envolvente, ni la rejilla de bermas, ni las tablas, ni V02."""
        self.calculate()
        with self.project.read() as conn:
            roles = dict(conn.execute(
                "SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON "
                "d.uid = io.item_uid WHERE io.operation_uid = d.operation_uid AND "
                "io.direction = 'out' AND d.name LIKE 'des\\_%' ESCAPE '\\'").fetchall())
        self.assertEqual(roles[DESIGN_SURFACE], provenance.DESIGN_SURFACE_ROLE)
        self.assertEqual(len(roles), 5, "la envolvente y las cuatro salidas del escalonado")
        entries = self.findings()
        self.assertEqual(set(entries), {DESIGN_SURFACE})
        entry = entries[DESIGN_SURFACE]
        self.assertEqual((entry.item_kind, entry.item_uid, entry.state, entry.text),
                         (ItemKind.DATASET, self.record(DESIGN_SURFACE, self.v1).uid,
                          ItemState.CURRENT, ""))
        self.assertEqual(entry.finding, UNCHECKED)
        self.assertTrue(self.plan().needs_acceptance)
        self.assertEqual(self.plan(self.v2).accept, (), "los datos son de la versión")

    def test_c_a_check_that_includes_it_up_to_date_lists_nothing(self) -> None:
        """RF-012-25 (D-29): verificada como final de una verificación vigente (y esta, que
        cumple), la superficie ya no se lista y la verificación no pide nada."""
        uid = self.verify((self.design_ref(),))
        self.assertEqual(self.findings(), {})
        self.assertNotIn(uid, {entry.item_uid for entry in self.plan().accept if entry.finding})

    def test_d_a_stale_check_is_listed_for_being_stale_not_the_surface(self) -> None:
        """RF-012-25: cambiado el espesor mínimo de la verificación (es del proyecto), esta queda
        obsoleta y se lista ella (una vigente obsoleta ya se lista por obsoleta); su superficie,
        que sigue siendo su final, no se repite."""
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            core_params.ParameterStore(self.project).change(
                conn, THICKNESS, value=0.05, reason="Prueba de la 013", **BY_HAND)
        entries = self.findings()
        self.assertEqual(set(entries), {CHECK})
        self.assertIn(f"La verificación «{CHECK}» está obsoleta", entries[CHECK].finding)
        self.assertNotIn(DESIGN_SURFACE, "".join(entry.finding for entry in entries.values()))

    def test_e_a_replaced_check_lists_the_surface_once(self) -> None:
        """RF-012-25, RF-013-31 (D-28): repetida la verificación sin la superficie de diseño, esta
        se lista una sola vez: la sustituida la daba y el papel también, pero es una sola entrada
        con una sola nota; la verificación nueva, al día y que cumple, no pide nada."""
        start = cfx.site_start()
        self.write_surfaces(("otra", raster_mod.Raster(start.grid, np.array(start.values),
                                                       start.crs, start.vertical)))
        other = surfaces.SurfaceRef(dataset="gis_dtm_otra", label="Otra")
        self.verify((other,))
        entries = self.findings()
        self.assertEqual(set(entries), {DESIGN_SURFACE})
        self.assertEqual(entries[DESIGN_SURFACE].finding, UNCHECKED)
        self.assertEqual([entry.item_uid for entry in self.plan().accept
                          if entry.item_uid == entries[DESIGN_SURFACE].item_uid],
                         [entries[DESIGN_SURFACE].item_uid])

    def test_f_not_frozen_without_accepting_and_the_note_stays(self) -> None:
        """RF-012-25, RF-009-08 (D-7): sin aceptar no se congela (el rechazo nombra la
        superficie); aceptada, V01.r1 se congela con su nota en lo aceptado y la revisión abierta
        (V01.r2) sigue listándola, porque el dato es de la versión."""
        plan = self.plan()
        self.clock.advance(minutes=1)
        with self.assertRaises(versions_model.VersionError) as caught:
            freeze.freeze_steps(self.project, self.v1.uid, reason="Entrega")
        self.assertEqual(caught.exception.code, "core.version_freeze_accept")
        self.assertIn(DESIGN_SURFACE, str(caught.exception))
        outcome = last(freeze.freeze_steps(self.project, self.v1.uid, reason="Entrega",
                                           accepted=freeze.Acceptance.of(plan))).result
        self.assertEqual(self.query("SELECT state FROM gb_revision WHERE uid = ?",
                                    str(outcome.frozen.uid)), [("frozen",)])
        notes = {item["name"]: item["finding"]
                 for item in json.loads(str(outcome.frozen.accepted))["items"] if "finding" in item}
        self.assertEqual(notes, {DESIGN_SURFACE: UNCHECKED})
        self.assertEqual(set(self.findings()), {DESIGN_SURFACE})

    def test_g_a_discarded_surface_is_not_listed(self) -> None:
        """RF-012-25: descartada la superficie de diseño, ya no hay nada que verificar."""
        uid = self.record(DESIGN_SURFACE, self.v1).uid
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            registry.set_status(conn, self.project, uid, "discarded")
        self.assertEqual(self.findings(), {})
