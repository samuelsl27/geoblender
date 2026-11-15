# SPDX-License-Identifier: GPL-3.0-or-later
"""Traer las entidades de otra versión y la versión que parte de otra (spec 015, T26; HU-015-2; RF-015-18,
RF-009-01; D-18; plan 015 §5.2.2, §5.3.3, §5.7 P-4; CE-015-01): el marco del error 59 entre versiones.

- **La versión que parte de otra** (RF-009-01, spec 0.4): ``ParameterStore.inherit`` le da los parámetros de entidad
  de la madre (``des.platform.{e}.*``) con su historial «Heredado de V01.r1» y **sin ningún resultado**: en
  ``entities.registry`` salen «sin calcular»; la declaración y las máscaras no las toman por calculadas.
- **Traer** (``entity_store.bring_entities``): copia las **definiciones** de las entidades de **cualquier otra
  versión** (los parámetros con su decisor, su fecha y su origen, y un historial «Traído de V01.r1»; la capa y la
  geometría de origen; las dependencias que declaró la persona), **sin superficies, tablas, cifras ni restricciones
  declaradas** (se regeneran al calcular), «sin calcular». Si un código ya está ocupado en la versión, la entidad
  recibe el siguiente y **las referencias entre las traídas** (``start``, ``support``, ``supports``) siguen el
  código nuevo; una partida que es un resultado de la versión de origen (la superficie de una entidad que no se
  trae, o una de diseño) no existe en la de destino y queda **sin valor**, con un aviso; el terreno, que es del
  proyecto, se conserva. Las descartadas no se traen. Una sola transacción.
- **Calcularlas** (``platform_run`` con ``code=``): las dependencias se detectan de nuevo (CE-015-01).

Sobre la cantera de la 014 con las capas de plataformas (rejilla gruesa de 2 m). El primer mundo: V01 con P1 («Plataforma
de carga», del terreno), P2 («Sobre la carga», de la superficie de P1, «en corte y relleno»: se apoya en P1), P3 («Plataforma
de taller», de la de P2, que protege con 4 m: declara una restricción), P4 (una «Explanada con eje» **sin calcular**, que
parte de la superficie de P1 por su nombre y declara apoyarse en P1 y en P5), P5 (una «Explanada sin eje», calculada y
**descartada**) y P6 (una «Plataforma de la torre» sin calcular y descartada); V02 (sin entidades), V03 (hija de V01) y
V04 (vacía).
"""

from __future__ import annotations

import unittest
from typing import Any, ClassVar

from tests.support.package import import_geoblender
from tests.unit.design import test_entity_supports as sup
from tests.unit.design import test_platform_operation as ops_test
from tests.unit.design import test_platform_prepare as prep

access = import_geoblender("gis.masks.access")
core_params = import_geoblender("core.params")
design_params = import_geoblender("design.params")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
messages = import_geoblender("design.messages")
params_model = import_geoblender("core.params.model")
provenance = import_geoblender("design.provenance")
versions_model = import_geoblender("core.versions.model")

DesignError = messages.DesignError
EntityState = entities.EntityState
LOADING, OVER, WORKSHOP, TOWER = prep.LOADING, sup.OVER, prep.WORKSHOP, prep.TOWER
WITH_AXIS, NO_AXIS = prep.WITH_AXIS, prep.NO_AXIS
GUARD_M = 4.0
USER = "Samuel (IMGA)"
WHY = "Prueba de la T26"
PSF_LOADING = provenance.dataset_name("psf", LOADING)
NONE = {"datasets": [], "operations": [], "figures": []}
"""Lo que tiene una versión que solo tiene definiciones: ningún resultado."""
FINISH = ops_test.finish


def key(code: str, param: str) -> str:
    return design_params.entity_key(code, param)


def codes(found: Any) -> list[tuple[str, str]]:
    """Los ``(código de origen, código de destino)`` de lo traído."""
    return [(item.source_code, item.code) for item in found.entities]


# ---------------------------------------------------------------------------------------------
# La versión que parte de otra y traer las entidades de otra
# ---------------------------------------------------------------------------------------------


# ---------------------------------------------------------------------------------------------
# Calcularlas de nuevo: la dependencia se detecta otra vez (CE-015-01)
# ---------------------------------------------------------------------------------------------


class BroughtCalculatedTest(sup.SupportsCase):
    """RF-015-18, RF-015-15, CE-015-01, D-18: P1 y P2 (que parte de la superficie de P1 y se apoya en ella con 8.000 m³)
    de V01 se traen a V02, quedan sin calcular y, al calcularlas allí (``platform_run`` con su código), **la dependencia se
    detecta de nuevo**."""

    first: ClassVar[Any]
    second: ClassVar[Any]
    found: ClassVar[Any]
    masks_v2: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.first = cls.made(prep.request())
        cls.second = cls.made(sup.over())
        cls.clock.advance(minutes=1)
        cls.found = entity_store.bring_entities(cls.project, "V01", "V02")
        cls.clock.advance(minutes=1)
        for _step in access.ensure_masks_steps(cls.project, cls.v2.uid):
            pass
        cls.masks_v2 = access.load_masks(cls.project, cls.v2.uid)

    def states(self) -> dict[str, Any]:
        return {entry.record.code: entry.record.state for entry in entities.registry(self.project, self.v2.uid)}

    def test_a_they_are_brought_without_a_calculation_and_without_the_dependency(self) -> None:
        """RF-015-18, CE-015-01: en V02, P1 y P2 salen «sin calcular»: la partida de P2 es la superficie de P1 de V02,
        y nada se apoya en nada todavía (ningún dato ni ninguna cifra en V02)."""
        self.assertEqual([(item.source_code, item.code) for item in self.found.entities],
                         [("PLT-001", "PLT-001"), ("PLT-002", "PLT-002")])
        self.assertEqual(self.states(), {"PLT-001": EntityState.UNCALCULATED, "PLT-002": EntityState.UNCALCULATED})
        self.assertEqual(entities.registry(self.project, self.v2.uid).get("PLT-002").record.start, "entity:PLT-001")
        self.assertEqual(self.query("SELECT count(*) FROM gb_dataset WHERE version_uid = ? AND name LIKE 'des!_%' "
                                    "ESCAPE '!'", self.v2.uid), [(0,)])

    def test_b_calculating_them_in_the_new_version_detects_the_dependency_again(self) -> None:
        """RF-015-18, RF-015-15, CE-015-01: se calcula y se crea P1 en V02 (con su código: no escribe otra vez sus
        parámetros) y luego P2: su operación anota la superficie de P1 de V02 como ``supported_on`` y la tabla de su
        huella, y la cifra ``des.supported_m3`` con el ámbito de PLT-001 **vale lo mismo que en V01** (8.000 m³ a
        mano); ambas quedan al día y P2 aparece en lo que se apoya en P1 de V02; lo de V01 no se toca."""
        v1_ops = self.query("SELECT uid, status, superseded_by FROM gb_operation WHERE uid IN (?, ?) ORDER BY uid",
                            self.first.handle.uid, self.second.handle.uid)
        rows = self.query("SELECT key, rev FROM gb_parameter WHERE scope = 'version' AND scope_uid = ? ORDER BY key",
                          self.v2.uid)
        self.clock.advance(minutes=1)
        first = self.calculate_in(prep.request(), version=self.v2.uid, masks=self.masks_v2, code="PLT-001").create()
        self.clock.advance(minutes=1)
        second = self.calculate_in(sup.over(), version=self.v2.uid, masks=self.masks_v2, code="PLT-002").create()
        self.assertEqual(self.states(), {"PLT-001": EntityState.CURRENT, "PLT-002": EntityState.CURRENT})
        self.assertEqual(self.supports_of(first.handle.uid), [])
        uid = second.handle.uid
        self.assertEqual(self.supports_of(uid), [(sup.PSF1, "supported_on"), (sup.EPR1, "support_footprint")])
        again, before = self.volumes_of(uid), self.volumes_of(self.second.handle.uid)
        self.assertEqual(list(again), ["PLT-001"])
        self.assertLessEqual(abs(again["PLT-001"] - sup.OVER_VOLUME_M3) / sup.OVER_VOLUME_M3, 1e-9)
        self.assertLessEqual(abs(again["PLT-001"] - before["PLT-001"]) / before["PLT-001"], 1e-9,
                             "lo apoyado en V02 es lo mismo que lo apoyado en V01")
        listed = entities.dependents(self.project, self.v2.uid, "PLT-001")
        self.assertEqual([(row.name, set(row.roles)) for row in listed], [(sup.OVER, {"surface", "supported_on"})])
        self.assertEqual(self.query("SELECT uid, status, superseded_by FROM gb_operation WHERE uid IN (?, ?) "
                                    "ORDER BY uid", self.first.handle.uid, self.second.handle.uid), v1_ops)
        self.assertEqual(self.query("SELECT key, rev FROM gb_parameter WHERE scope = 'version' AND scope_uid = ? "
                                    "ORDER BY key", self.v2.uid), rows,
                         "calcular lo traído no reescribe sus parámetros")


if __name__ == "__main__":
    unittest.main()
