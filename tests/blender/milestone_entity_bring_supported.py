# SPDX-License-Identifier: GPL-3.0-or-later
"""Traer las entidades de otra versión con los cuatro tipos de la 016, con la orden real y el mundo de la T33 (spec 016, T47; hallazgo C-4 de
la verificación única; RF-015-18, RF-009-01, RF-015-28, RF-016-24; P-13: pesa más de 1 s, paso «hito»).

El mundo de ``milestone_stockpile_views`` (V01 con las ocho entidades: la detección, dos retiradas, el contrafuerte, los dos cuerpos y dos
plataformas, hechas con las órdenes reales). El cuerpo «bajo un techo» se apoya en la superficie del «sobre una base» (la superficie
conocida es ``entity:BDY-001``; «Cambiar parámetro…» lo admite: D-2) y **«Traer las entidades de…»** copia las ocho a V02 **dos veces**: la
primera con los mismos códigos y la segunda, con los códigos ocupados, con los siguientes, y la superficie conocida del cuerpo **sigue el
código nuevo** (hasta la T47 seguía diciendo ``entity:BDY-001``). Las ocho quedan «sin calcular» y sin ningún dato en V02.

Se ejecuta con ``tools/run_blender_tests.py`` (paso «hito» de ``tools/check.py --completo``).
"""

import json
import unittest
from typing import Any

import bpy

from tests.blender import milestone_stockpile_views as world
from tests.blender.milestone_entity_supported_after import SupportedAfterHelpers

BODIES = ("BDY-001", "BDY-002")


class BringSupportedWorldTest(SupportedAfterHelpers, world.StockpileViewsTest):
    """El mundo de la T33 (su ``test_a``) y, **por el orden de las pruebas**, (x) traer las entidades a V02 dos veces."""

    def body_surfaces(self, version: Any) -> dict[str, Any]:
        """El valor de ``surface`` de cada cuerpo de ``version``, por la clave de su parámetro."""
        return {key: json.loads(value) for key, value in self.rows(
            "SELECT key, value FROM gb_parameter WHERE scope = 'version' AND scope_uid = ? AND key LIKE 'des.body.%.surface' "
            "ORDER BY key", version.uid)}

    def results_in(self, version: Any) -> list[Any]:
        """Los datos propios de la versión (los ``des_*`` que escribe una entidad al calcularse): ninguno si solo tiene definiciones."""
        return self.rows("SELECT name FROM gb_dataset WHERE version_uid = ? AND name LIKE 'des!_%' ESCAPE '!'", version.uid)

    def bring(self) -> set[str]:
        return bpy.ops.geoblender.des_entity_bring("EXEC_DEFAULT", source="V01", entities="")

    def test_x_bringing_the_world_twice_follows_the_codes_also_in_the_known_surface_of_a_body(self) -> None:
        """RF-015-18, RF-009-01, RF-016-24 (C-4): las ocho entidades de V01 se traen a V02 «sin calcular» y sin resultados, con los mismos
        códigos; al traerlas otra vez los cuerpos pasan a ``BDY-003`` y ``BDY-004`` y **la superficie conocida del cuarto es la del tercero**
        (``entity:BDY-003``), no la del primero; lo de V01 no cambia."""
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v01.uid), {"FINISHED"})
        self.assertEqual(self.change("des.body.bdy_002.surface", "entity:BDY-001"), {"FINISHED"})  # D-2: es una referencia válida
        self.finish_refresh()
        before = self.registry_states()
        self.assertEqual(sorted(before), sorted(world.CODES.values()))
        self.assertEqual(self.body_surfaces(self.v01), {"des.body.bdy_001.surface": self.ground, "des.body.bdy_002.surface": "entity:BDY-001"})

        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v02.uid), {"FINISHED"})
        self.assertEqual(self.bring(), {"FINISHED"})
        states = {entry.record.code: str(entry.record.state) for entry in self.entities.registry(self.project, self.v02.uid)}
        self.assertEqual(states, dict.fromkeys(sorted(world.CODES.values()), "uncalculated"))
        self.assertEqual(self.body_surfaces(self.v02), {"des.body.bdy_001.surface": self.ground, "des.body.bdy_002.surface": "entity:BDY-001"})
        self.assertEqual(self.results_in(self.v02), [], "traer no trae resultados")

        self.assertEqual(self.bring(), {"FINISHED"})
        found = {entry.record.code: str(entry.record.state) for entry in self.entities.registry(self.project, self.v02.uid)}
        self.assertEqual(len(found), 2 * len(world.CODES))
        self.assertEqual(set(found.values()), {"uncalculated"})
        self.assertLessEqual({"BDY-003", "BDY-004"}, set(found))
        surfaces = self.body_surfaces(self.v02)
        self.assertEqual(surfaces["des.body.bdy_003.surface"], self.ground)
        self.assertEqual(surfaces["des.body.bdy_004.surface"], "entity:BDY-003", "la superficie conocida sigue el código nuevo (C-4)")
        self.assertEqual(surfaces["des.body.bdy_002.surface"], "entity:BDY-001", "lo ya traído no se toca")
        self.assertEqual(self.results_in(self.v02), [])
        self.assertEqual(self.registry_states(), before, "lo de V01 no cambia")


for _name in dir(world.StockpileViewsTest):  # sus pruebas son suyas: aquí solo su mundo (test_a) y los ayudantes
    if _name.startswith("test_") and not _name.startswith("test_a_") and _name not in vars(BringSupportedWorldTest):
        setattr(BringSupportedWorldTest, _name, None)
del _name


if __name__ == "__main__":
    unittest.main()
