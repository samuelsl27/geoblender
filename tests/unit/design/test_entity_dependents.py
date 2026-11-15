# SPDX-License-Identifier: GPL-3.0-or-later
"""Cascada, causa y lista de dependencias de las entidades (spec 015, T24; HU-015-2; RF-015-15, RF-015-16;
RNF-015-02; plan 015 §5.2.3 «Estados» y «Dependencias», §5.4 A6; ADR-0030 §4; CE-015-01 y CE-015-05).

- **La lista** (``design.entities.dependents`` y ``dependencies_of``): «lo que se apoya en E» y «en qué se apoya
  E» son **una consulta de entradas** (los papeles ``supported_on`` y ``surface`` sobre el dato ``des_psf_`` de
  la entidad), de entidades y de diseños de la 013 y la 014, **en una sola lista**: nombre, tipo, volumen
  apoyado (la cifra ``des.supported_m3`` con ese ámbito; sin volumen si solo parte de su superficie) y estado.
- **La causa** (``stale_reason`` y ``operation_reason``): el «Obsoleto: …» de la 008 con la **entidad** que cambió
  (su nombre, no su código) y lo que cambió.
- **La cascada** (RF-015-16, RF-008-24, RF-008-26): cambiar un parámetro de P1 deja obsoletas, con su causa, P1,
  P2 (que parte de su superficie y rellena sobre ella), el «solo relleno» de la 014 que se apoyaba en ellas y
  una verificación de la 012 que usa la superficie de P2; «Recalcular lo obsoleto» las rehace en orden de
  dependencia; una revisión congelada no se marca ni cambia (RF-009-19).
- **Rendimiento** (RNF-015-02): con 200 entidades en la versión, las dos listas, ≤ 1 s en disco local.

La historia con proyecto, sobre la cantera de la 014 con las capas de plataformas (rejilla gruesa de 2 m): P1 es
la «Plataforma de la balsa» (a 255 m, en la lámina de agua de la 014: corta), P2 «Sobre la balsa» (a 257 m, «en
corte y relleno», **de la superficie de P1**: rellena 2 m sobre su huella), P3 «Arrastra el terreno» (de la
superficie de P2, sin rellenar), el «solo relleno» «Balsa 2» (rellena la lámina a 270 m: se apoya en P1 y en P2)
y la verificación de la 012 «Revisión de la balsa» (partida: el terreno; final: la superficie de P2).
"""

from __future__ import annotations

import json
import unittest
from typing import Any, ClassVar

from tests.support import constraints_fixtures as cfx
from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender
from tests.unit.design import test_after_entity_change as chain_test
from tests.unit.design import test_entity_supports as sup
from tests.unit.design import test_fill_only_operation as fill_test
from tests.unit.design import test_platform_operation as ops_test
from tests.unit.design import test_platform_prepare as prep

core_params = import_geoblender("core.params")
cstore = import_geoblender("reserves.compliance_store")
dataset_registry = import_geoblender("core.datasets.registry")
design_params = import_geoblender("design.params")
entities = import_geoblender("design.entities")
freeze = import_geoblender("core.versions.freeze")
gis = import_geoblender("gis")
model = import_geoblender("design.model")
operations = import_geoblender("core.provenance.operations")
provenance = import_geoblender("design.provenance")
recompute_mod = import_geoblender("core.provenance.recompute")
reproduce_mod = import_geoblender("core.versions.reproduce")
steps = import_geoblender("design.steps")
surfaces = import_geoblender("reserves.surfaces")

EntityState = entities.EntityState
BALSA, ON_TOP, DRAG = sup.BALSA, "Sobre la balsa", sup.DRAG
TWIN, CHECK = "Balsa 2", "Revisión de la balsa"
ON_TOP_LAYER = "gis_fea_plataformas_sobre"
PSF1, PSF2 = (provenance.dataset_name("psf", name) for name in (BALSA, ON_TOP))
PSF_FIRST = provenance.dataset_name("psf", prep.LOADING)
"""El dato de la superficie de la primera entidad de la prueba de 200 entidades (la «Plataforma de carga»)."""
EPR1, EPR2 = (provenance.dataset_name("epr", name) for name in (BALSA, ON_TOP))
TWIN_SURFACE = provenance.dataset_name("srf", TWIN)
GRADIENT = design_params.entity_key("PLT-001", "gradient_pct")
LABEL = "Pendiente de la rasante de la plataforma"
"""La etiqueta (en español) del parámetro ``gradient_pct`` de una plataforma."""
FILL_M = 2.0
"""P2 sube 2 m (257 − 255) sobre cada celda de la huella de P1 (a mano)."""


def recompute_verification(request: Any) -> Any:
    """Lo que registra ``bl`` como función de recálculo de la verificación de la 012: lleva sus pasos hasta el
    final y da su operación."""
    handle, work = cstore.recompute_run(request)
    sup.finish(work)
    return handle


def on_top_layer() -> Any:
    """La capa de ejes de «Sobre la balsa»: el eje y el ancho de la plataforma de la balsa, a 257 m."""
    path = ((135.0, 305.0), (165.0, 305.0))
    return qfx.LayerData(ON_TOP_LAYER, "line", (((cfx.absolute(path),),),), (ON_TOP,),
                         {"ancho": (6.0,), "cota_inicial": (257.0,), "pendiente": (0.0,)})


def on_top(**changes: Any) -> Any:
    """P2: «en corte y relleno» sobre la superficie de P1."""
    return prep.request(ON_TOP, fields=prep.line_fields(ON_TOP_LAYER), start="entity:PLT-001",
                        mode=model.PlatformMode.CUT_FILL, **changes)


class DependentsCase(sup.SupportsCase):
    """El proyecto de la cantera con la historia de arriba, **una vez por clase**, y los ayudantes de lo que
    queda registrado (la operación vigente de cada cosa y su cambio de parámetro)."""

    twin: ClassVar[Any]

    @classmethod
    def definitions(cls) -> tuple[Any, ...]:
        return (*ops_test.real_definitions(), *fill_test.definitions(),
                cstore.operation_def(recompute_verification, cstore.REPRODUCE[cstore.VERIFY]), *cstore.FIGURES)

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_families(design_params.FAMILIES)
        cls.addClassCleanup(core_params.unregister_families, "des")
        for param in ("height_m", "face_deg", "berm_m", "anchor_m", "mesh_factor"):
            fill_test.declare(cls.project, cls.clock, design_params.bench_key(fill_test.REST.code, param),
                              getattr(fill_test.REST, param))
        envelope = model.EnvelopeRequest(
            fill_test.ENVELOPE, "down",
            model.SeedSource("fixed", zone=model.Zone("layer", qfx.WATER_LAYER),
                             elevation_m=fill_test.ENVELOPE_LEVEL_M),
            slope_deg=fill_test.ENVELOPE_SLOPE_DEG)
        cls.clock.advance(minutes=1)
        fill_test.drive(steps.envelope_run(cls.project, envelope, version=cls.v1.uid,
                                           masks=cls.masks_v1)).result.create()
        qfx.write_feature_layer(cls.project, cls.clock, on_top_layer())
        cls.clock.advance(minutes=1)
        cls.made(sup.asked(BALSA))
        cls.made(on_top())
        cls.made(sup.asked(DRAG, start="entity:PLT-002"))
        cls.twin = cls.fill(model.FillOnlyRequest(TWIN, fill_test.ENVELOPE, fill_test.START,
                                                  fill_test.REST.code, water=fill_test.WATER))
        cls.verify()

    @classmethod
    def fill(cls, request: Any) -> Any:
        """«Calcula» y «crea» el diseño «solo relleno» ``request`` en V01."""
        cls.clock.advance(minutes=1)
        return fill_test.drive(steps.fill_only_run(cls.project, request, version=cls.v1.uid,
                                                   masks=cls.masks_v1)).result.create()

    @classmethod
    def verify(cls) -> str:
        """La verificación de la 012 con el terreno de partida y la superficie de P2 como final: el uid de su
        operación (consume la de P2 con el papel ``final_1``)."""
        cls.clock.advance(minutes=1)
        sup.finish(cstore.verify_project_steps(
            cls.project, version=cls.v1.uid, name=CHECK,
            start=surfaces.SurfaceRef(dataset=fill_test.START, label="Partida"),
            finals=(surfaces.SurfaceRef(dataset=PSF2, label=ON_TOP),)))
        return str(cls.query_of("SELECT uid FROM gb_operation WHERE op_type = ? AND status = 'done' "
                                "AND superseded_by IS NULL ORDER BY fid DESC LIMIT 1", cstore.VERIFY)[0][0])

    def check_uid(self) -> str:
        """El uid de la verificación vigente."""
        return str(self.query("SELECT uid FROM gb_operation WHERE op_type = ? AND status = 'done' AND "
                              "superseded_by IS NULL ORDER BY fid DESC LIMIT 1", cstore.VERIFY)[0][0])

    def fill_uid(self) -> str:
        """El uid de la operación vigente de «Balsa 2»."""
        rows = self.query("SELECT uid, settings FROM gb_operation WHERE op_type = 'des.fill_only' AND "
                          "status = 'done' AND superseded_by IS NULL ORDER BY fid")
        (found,) = [uid for uid, settings in rows if json.loads(settings).get("name") == TWIN]
        return str(found)

    def listed(self, code: str) -> list[tuple[Any, ...]]:
        """«Lo que se apoya en» ``code``, como filas ``(nombre, tipo, entidad, papeles)``."""
        return [(row.name, row.op_type, row.entity, row.roles)
                for row in entities.dependents(self.project, self.v1.uid, code)]

    def cells_of(self, table: str) -> int:
        """Las celdas de la huella de la tabla ``des_epr_`` ``table`` de V01."""
        return int(self.footprint_of(table)[0].size)


# ---------------------------------------------------------------------------------------------
# La lista (a) y la cascada (b a f), sobre el mismo proyecto
# ---------------------------------------------------------------------------------------------


# ---------------------------------------------------------------------------------------------
# Una restricción ajena
# ---------------------------------------------------------------------------------------------


class ForeignConstraintTest(chain_test.ChainCase):
    """RF-015-16: cambiar una **restricción ajena** que usa una entidad. P1 (la «Plataforma de carga», que no
    protege) y P2 (que protege 4 m, de la superficie de P1): al declarar, las máscaras cambian y P1, que las usó,
    queda obsoleta con la causa; el motivo la dice."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())
        cls.chain()
        cls.made(prep.request(prep.WORKSHOP, start="entity:PLT-001", protect=True, guard_m=4.0))
        cls.chain()

    def test_b_a_constraint_another_entity_declares_stales_the_one_that_used_the_masks_with_its_reason(self) -> None:
        """RF-015-16, RF-012-06, D-21: P1 queda obsoleta por otro contenido de las máscaras que consumió (lo
        que cambia la restricción que declara P2); el motivo es el «Obsoleto: cambió …» de la 008 con el nombre
        del dato, y es el mismo que el del registro de las entidades."""
        first = self.current("PLT-001")
        causes = self.stale_causes(first)
        self.assertEqual({kind for kind, _name in causes}, {"dataset_changed"})
        self.assertIn("gis_msk", {name for _kind, name in causes})
        self.assertEqual(entities.registry(self.project, self.v1.uid).get("PLT-001").record.state,
                         EntityState.STALE)
        reason = entities.stale_reason(self.project, self.v1.uid, "PLT-001")
        self.assertTrue(reason.startswith("Obsoleto: cambió «"), reason)
        for _kind, name in causes:
            self.assertIn(f"cambió «{name}»", reason)
        self.assertEqual(entities.operation_reason(self.project, self.v1.uid, first), reason)
        self.assertEqual(entities.stale_reason(self.project, self.v1.uid, "PLT-001", language="en")
                         .split(": ")[0], "Stale")


# ---------------------------------------------------------------------------------------------
# 200 entidades
# ---------------------------------------------------------------------------------------------


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
