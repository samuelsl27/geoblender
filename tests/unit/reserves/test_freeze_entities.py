# SPDX-License-Identifier: GPL-3.0-or-later
"""Congelar con cadenas de entidades de diseño (spec 015, T32; HU-015-1; RF-015-04, RF-012-25, RF-012-21; plan 015
§5.1, §5.2.3 y §5.7, P-2 y P-9; plan 012 D-29; plan 013 D-28).

La comprobación de ``res`` al congelar (``reserves.compliance_store.freeze_findings``, registrada con
``core.versions.freeze.register_freeze_check``) pide verificar, además de las superficies con el papel
``design_surface`` de la 013 y la 014, **la última de cada cadena de entidades** (``design.entities.chain_tails``:
RF-015-04, «la última de cada cadena sea su superficie de diseño para la comprobación de congelar y las demás,
superficies de trabajo que se verifican a petición»). La superficie de una entidad lleva el papel propio
``entity_surface`` (P-2) y no ``design_surface``: las intermedias de una cadena no la piden. Sobre la cantera
sintética de la 014 con las capas de plataformas (rejilla gruesa de 2 m) y la historia de la T24: P1 «Plataforma
de la balsa» (del terreno), P2 «Sobre la balsa» (de la superficie de P1), P3 «Arrastra el terreno» (de la de P2) y el
«solo relleno» «Balsa 2» de la 014 (una superficie ``design_surface``), **sin ninguna verificación**:

- **La cadena** (:class:`FreezeChainTest`, en el orden de las pruebas): (a) con tres plataformas encadenadas congelar
  pide verificar **solo la última**; (b) y a la vez la superficie de diseño de la 014; (c) las intermedias se
  verifican a petición (la orden de la 012 las acepta y registra su cumplimiento como las de diseño) y no añaden nada;
  (d) una verificación de una intermedia sustituida por otra no hace que se pida; (e) las entidades traídas a otra
  versión, sin calcular, no cuentan; (f) con la verificación de la última hecha, congelar procede.
- **Una descartada** (:class:`FreezeDiscardedTest`): descartada la última de la cadena, su superficie no cuenta (ya no
  está viva) y la última de la cadena que queda es la anterior.
- **Un límite nuevo** (:class:`FreezeNewLimitTest`, P-9): la plataforma no se ajusta con «Ajustar el diseño a un límite
  nuevo» de la 014 (esa orden ajusta ``design_surface``); una plataforma que queda fuera de un límite nuevo **la avisa
  la verificación de congelar**, con los m³ que mueve fuera, y las comprobaciones de la 014 no la ven.
"""

from __future__ import annotations

import unittest
from typing import Any


from tests.support.package import import_geoblender
from tests.unit.design import test_entity_dependents as dep
from tests.unit.design import test_entity_supports as sup
from tests.unit.design import test_fill_only_operation as fill_test

access = import_geoblender("gis.masks.access")
compliance = import_geoblender("reserves.compliance")
core_params = import_geoblender("core.params")
cstore = import_geoblender("reserves.compliance_store")
design_store = import_geoblender("design.store")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
freeze = import_geoblender("core.versions.freeze")
geotiff_reader = import_geoblender("gis.geotiff.reader")
gis = import_geoblender("gis")
provenance = import_geoblender("design.provenance")
surfaces = import_geoblender("reserves.surfaces")
versions_model = import_geoblender("core.versions.model")

ItemKind = versions_model.ItemKind
EntityState = entities.EntityState
PSF1, PSF2, TWIN_SURFACE = dep.PSF1, dep.PSF2, dep.TWIN_SURFACE
PSF3 = provenance.dataset_name("psf", sup.DRAG)
CHAIN = (PSF1, PSF2, PSF3)
THICKNESS_M = sup.THICKNESS_M
CELL_M2 = sup.CELL_M2
BY = "Samuel (IMGA)"


def unchecked(name: str) -> str:
    """La nota de una superficie de diseño sin verificación al día (``res.freeze_surface_unchecked``)."""
    return f"«{name}» es una superficie de diseño sin verificación al día: ninguna verificación vigente la incluye."


class FreezeCase(dep.DependentsCase):
    """La historia de :class:`~tests.unit.design.test_entity_dependents.DependentsCase` (P1, P2 y P3 encadenadas y el
    «solo relleno» de la 014) **sin su verificación**, con la comprobación de ``res`` registrada al congelar y los
    ayudantes de lo que enseña el plan."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        freeze.register_freeze_check(cstore.MODULE, cstore.freeze_findings)
        cls.addClassCleanup(freeze.unregister_freeze_checks, cstore.MODULE)

    @classmethod
    def verify(cls) -> str:
        """Sin verificación: es lo que pide esta prueba (la base verifica la superficie de P2, una intermedia)."""
        return ""

    def plan(self, version: Any = None) -> Any:
        return freeze.freeze_plan(self.project, (version or self.v1).uid)

    def findings(self, version: Any = None) -> dict[str, Any]:
        """Las entradas con nota del plan de congelar, por nombre."""
        return {entry.name: entry for entry in self.plan(version).accept if entry.finding}

    def check(self, name: str, *finals: str, version: Any = None) -> Any:
        """«Verificar un diseño por recinto…» de la 012 de ``finals`` (nombres de dato) frente al terreno, con el
        nombre ``name`` (repetirlo sustituye a la anterior): su ``VerifyResult``."""
        self.clock.advance(minutes=1)
        stored = sup.finish(cstore.verify_project_steps(
            self.project, version=(version or self.v1).uid, name=name,
            start=surfaces.SurfaceRef(dataset=fill_test.START, label="Partida"),
            finals=tuple(surfaces.SurfaceRef(dataset=final, label=final) for final in finals)))
        return stored.result

    def roles(self) -> dict[str, str]:
        """El papel con que escribió su operación cada superficie de la historia (por su nombre)."""
        return {str(name): str(role) for name, role in self.query(
            "SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = d.operation_uid AND io.direction = 'out' AND d.name IN (?, ?, ?, ?)",
            *CHAIN, TWIN_SURFACE)}


# ---------------------------------------------------------------------------------------------
# La cadena
# ---------------------------------------------------------------------------------------------


# ---------------------------------------------------------------------------------------------
# Una descartada
# ---------------------------------------------------------------------------------------------


class FreezeDiscardedTest(FreezeCase):
    """RF-015-04, RF-015-17: descartar la última de la cadena."""

    def test_a_a_discarded_one_does_not_count_and_the_last_one_that_is_left_does(self) -> None:
        """RF-015-04, RF-015-17, RF-012-25: descartada P3 (la última, que está sin verificar), su superficie **no
        cuenta** (es un registro, ya no está viva); la última de la cadena que queda es P2, **que se pide** (sin
        verificar); P1, que sigue siendo intermedia, no; y la superficie de la 014 también."""
        self.assertEqual(set(self.findings()), {PSF3, TWIN_SURFACE})
        self.clock.advance(minutes=1)
        sup.finish(entity_store.discard_entity_steps(self.project, self.v1.uid, "PLT-003",
                                                     reason="Se retira la plataforma", decided_by=BY))
        states = {entry.record.code: entry.record.state for entry in entities.registry(self.project, self.v1.uid)}
        self.assertEqual(states["PLT-003"], EntityState.DISCARDED)
        found = self.findings()
        self.assertNotIn(PSF3, found, "una descartada no cuenta")
        self.assertEqual(set(found), {PSF2, TWIN_SURFACE}, "la última de la cadena que queda es P2")
        self.assertEqual(found[PSF2].finding, unchecked(PSF2))
        self.assertNotIn(PSF1, found)


# ---------------------------------------------------------------------------------------------
# Un límite nuevo (P-9)
# ---------------------------------------------------------------------------------------------


NEW_TOP_M = 270.0
"""El límite legal redibujado, a mano: el norte del rectángulo baja de 360 a 270 m (local); lo que está al norte de
ese paralelo queda **fuera** del límite legal (la banda de 5 m hacia dentro, entre 265 y 270, es otro recinto)."""
NEW_OUTSIDE_LOCAL = (0.0, NEW_TOP_M, 400.0, 400.0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
