# SPDX-License-Identifier: GPL-3.0-or-later
"""Descartar una entidad, «apoyo retirado» y soltar el apoyo (spec 015, T25; HU-015-2; RF-015-17, RF-009-12,
RF-008-26, RF-008-27, RF-015-10, RF-015-15; D-12; plan 015 §5.2.3, §5.3.3, §5.4 A7 y §5.7 P-6; ADR-0030 §4;
CE-015-01 y CE-015-04): el caso del **error 59** (un relleno seguía apoyado en un acopio que se retiraba).

- **La lista antes** (``entity_store.discard_plan``): **una sola lista** de lo que se apoya en la entidad y de lo que
  parte de ella —nombre, tipo y volumen apoyado en m³, la de ``entities.dependents``—, sin escribir nada.
- **Descartar** (``entity_store.discard_entity``): poner ``DISCARDED`` los datos que escribió (nada se borra,
  RF-009-12) o, si no está calculada, el parámetro de versión ``des.platform.{e}.discarded``; con un **evento**
  (``entity_discarded``) y el motivo. Lo que se le apoyaba queda en **«apoyo retirado»**, con la causa
  («Apoyo retirado: se descartó «P1»»), y «Recalcular lo obsoleto» **no lo recalcula**
  (``core.recompute_no_successor_release``) hasta que la persona lo rehaga sobre otra superficie, lo descarte o lo dé
  por bueno con un motivo.
- **Soltar el apoyo** (``entity_store.release_support``, A7, P-6): repetir la operación **con** ``supersedes`` sin
  esa entrada, con el motivo y el decisor en sus ajustes (``supports_released``, acumulada) y un evento
  (``support_released``); su salida no cambia (mismo hash) y lo que dependía de ella **no se recalcula**
  (RF-008-26); el gancho de las dependencias no vuelve a registrar una entidad soltada.
- **La restricción** de la entidad descartada **sale de las máscaras** (``after_entity_change``).

Tres mundos sobre la cantera de la 014 con las capas de plataformas (rejilla gruesa de 2 m): el de CE-015-01
(P1, P2 que parte de su superficie y rellena sobre ella, P3, el «solo relleno» «Balsa 2» y una verificación),
uno con dos cosas que se apoyan sin partir de P1 —una plataforma que lo declara y el «solo relleno»— y una
verificación de éste, y el de una plataforma que protege.
"""

from __future__ import annotations

import json
import unittest
from typing import Any


from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender
from tests.unit.design import test_entity_dependents as dep
from tests.unit.design import test_entity_supports as sup
from tests.unit.design import test_fill_only_operation as fill_test
from tests.unit.design import test_platform_prepare as prep

access = import_geoblender("gis.masks.access")
core_params = import_geoblender("core.params")
cstore = import_geoblender("reserves.compliance_store")
dataset_registry = import_geoblender("core.datasets.registry")
declared_mod = import_geoblender("core.constraints.declared")
design_params = import_geoblender("design.params")
design_store = import_geoblender("design.store")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
events = import_geoblender("core.project.events")
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")
provenance = import_geoblender("design.provenance")
recompute_mod = import_geoblender("core.provenance.recompute")
steps = import_geoblender("design.steps")
surfaces = import_geoblender("reserves.surfaces")

DesignError = messages.DesignError
EntityState = entities.EntityState
BALSA, ON_TOP, DRAG, TWIN = dep.BALSA, dep.ON_TOP, dep.DRAG, dep.TWIN
WORKSHOP = prep.WORKSHOP
PSF1, PSF2, EPR1, EPR2 = dep.PSF1, dep.PSF2, dep.EPR1, dep.EPR2
PRP1 = provenance.dataset_name("prp", BALSA)
TWIN_SURFACE = dep.TWIN_SURFACE
TWIN_CHECK = "Revisión de Balsa 2"
BY = "Samuel (IMGA)"
WHY = "La balsa no se hace: la propiedad cambia el plan"


class DiscardCase:
    """Lo común de los tres mundos: ayudantes de lo que queda registrado (eventos, estados, el estado entero del
    proyecto)."""

    def events(self, kind: Any) -> list[Any]:
        with self.project.read() as conn:  # type: ignore[attr-defined]
            return events.read_events(conn, kind)

    def states(self) -> dict[str, Any]:
        registry = entities.registry(self.project, self.v1.uid)  # type: ignore[attr-defined]
        return {entry.record.code: entry.record.state for entry in registry}

    def state_of(self, code: str) -> Any:
        return self.states()[code]

    def dataset_status(self, *names: str) -> dict[str, str]:
        return dict(self.query(  # type: ignore[attr-defined]
            f"SELECT name, status FROM gb_dataset WHERE name IN ({', '.join('?' for _ in names)}) "
            "AND version_uid = ?", *names, self.v1.uid))  # type: ignore[attr-defined]

    def everything(self) -> dict[str, Any]:
        """Todo lo que podría escribir descartar o soltar, con los eventos."""
        return {**self.written(), "events": self.query("SELECT kind, message FROM gb_event ORDER BY fid")}  # type: ignore[attr-defined]

    def locator(self, name: str) -> str:
        """Dónde está el dato ``name`` de V01, **también descartado** (``record`` solo da lo vigente)."""
        ((found,),) = self.query("SELECT locator FROM gb_dataset WHERE name = ? AND version_uid = ?",  # type: ignore[attr-defined]
                                 name, self.v1.uid)  # type: ignore[attr-defined]
        return str(found)

    def settings_of(self, uid: str) -> dict[str, Any]:
        ((settings,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", uid)  # type: ignore[attr-defined]
        return dict(json.loads(settings))


# ---------------------------------------------------------------------------------------------
# CE-015-01: P1, P2 (de su superficie), P3, «Balsa 2» y una verificación
# ---------------------------------------------------------------------------------------------


# ---------------------------------------------------------------------------------------------
# Dar por bueno (A7, P-6): una plataforma que lo declara y un «solo relleno», sin partir de P1
# ---------------------------------------------------------------------------------------------


class ReleasedLiveEntityTest(DiscardCase, sup.SupportsCase):
    """RF-015-17, A7, ADR-0030 §4: lo que se suelta **no vuelve a registrarse** aunque la entidad siga viva (lo que
    habrá con la retirada de un acopio de la 016): P1 (la «Plataforma de la balsa») y «Balsa 2», que rellena sobre
    ella. Repetir «Balsa 2» soltando P1 no lleva sus entradas ni su cifra, y un recálculo después, que sí detectaría
    P1 (sigue viva y «Balsa 2» sigue rellenando sobre ella), tampoco: lo soltado va en sus ajustes."""

    @classmethod
    def definitions(cls) -> tuple[Any, ...]:
        return dep.DependentsCase.definitions()

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
        cls.made(sup.asked(BALSA))
        cls.clock.advance(minutes=1)
        fill_test.drive(steps.fill_only_run(
            cls.project, model.FillOnlyRequest(TWIN, fill_test.ENVELOPE, fill_test.START, fill_test.REST.code,
                                               water=fill_test.WATER),
            version=cls.v1.uid, masks=cls.masks_v1)).result.create()

    def fill_op(self) -> str:
        ((uid,),) = self.query("SELECT uid FROM gb_operation WHERE op_type = 'des.fill_only' AND status = 'done' "
                               "AND superseded_by IS NULL")
        return str(uid)

    def request(self, uid: str) -> Any:
        ((settings,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", uid)
        return recompute_mod.RecomputeRequest(self.project, uid, "des.fill_only", json.loads(settings), (), (),
                                              version=self.v1.uid)

    def test_a_what_is_released_is_neither_carried_nor_registered_again_by_the_hook(self) -> None:
        """RF-015-17, A7, ADR-0030 §4: «Balsa 2» rellena sobre P1, que está viva: sin soltar nada se apoya en ella
        (las entradas y la cifra); repetida **soltando** P1 (``recompute_run(released=…)``) no lleva sus entradas
        (``carried``) ni su cifra (el gancho no la detecta) y deja lo soltado en sus ajustes; un recálculo normal
        después —P1 sigue viva y «Balsa 2» sigue rellenando sobre ella— tampoco la vuelve a registrar; el estado de
        P1 no cambia."""
        first = self.fill_op()
        self.assertEqual([name for name, _role in self.supports_of(first)], [PSF1, EPR1])
        self.assertEqual(list(self.volumes_of(first)), ["PLT-001"])
        released = provenance.ReleasedSupport("PLT-001", WHY, BY, "2026-11-15T10:00:00Z")
        self.clock.advance(minutes=1)
        handle, work = design_store.recompute_run(self.request(first), released=(released,))
        sup.finish(work)
        self.assertEqual(self.supports_of(handle.uid), [])
        self.assertEqual(self.volumes_of(handle.uid), {})
        self.assertEqual(self.settings_of(handle.uid)["supports_released"], [released.settings()])
        self.clock.advance(minutes=1)
        again, work = design_store.recompute_run(self.request(handle.uid))
        sup.finish(work)
        self.assertEqual(self.supports_of(again.uid), [], "el gancho no la vuelve a registrar")
        self.assertEqual(self.volumes_of(again.uid), {})
        self.assertEqual(self.settings_of(again.uid)["supports_released"], [released.settings()])
        self.assertEqual(self.state_of("PLT-001"), EntityState.CURRENT)
        with self.assertRaises(ValueError):  # lo que no deja una superficie que se apoye en una entidad
            design_store.recompute_run(recompute_mod.RecomputeRequest(
                self.project, "uid", "des.envelope", {}, (), (), version=self.v1.uid), released=(released,))


# ---------------------------------------------------------------------------------------------
# La restricción de una entidad descartada y descartar sin calcular
# ---------------------------------------------------------------------------------------------


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
