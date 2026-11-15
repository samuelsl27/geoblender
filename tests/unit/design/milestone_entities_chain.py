# SPDX-License-Identifier: GPL-3.0-or-later
"""Pruebas de hito de «test_entities_chain» (spec 015, T48; plan 015 §7.4): las clases que pesan,
movidas sin cambiar una aserción. El «verde» deja en ``test_entities_chain`` las más ligeras de cada
requisito; las de aquí las ejecuta el paso «hito» de ``tools/check.py --completo`` (la publicación
lo pide siempre).
"""

from __future__ import annotations

import statistics
import time
from typing import Any

from tests.support import entity_fixtures as efx
from tests.support import quarry_fixtures as qfx
from tests.support.provenance_contract import registered
from tests.support.versions_fixtures import change_counter
from tests.unit.design.test_entities_chain import (
    GROUND,
    OP_TYPE,
    State,
    code,
    core_params,
    entities,
    messages,
    numbers,
    operations,
    params,
    ref,
    synthetic_definition,
)


class RegistryScaleTest(efx.EntityProjectCase):
    """El registro con 200 entidades, con su operación cada una, en ≤ 0,3 s (T03)."""

    STEP_M = qfx.COARSE_STEP_M
    COUNT = 200
    BUDGET_S = 0.3

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_families(params.ENTITY_FAMILIES)
        cls.addClassCleanup(core_params.unregister_families, "des")
        cls.enterClassContext(registered(synthetic_definition()))
        store = core_params.ParameterStore(cls.project)
        cls.clock.advance(minutes=1)
        with cls.project.write_transaction() as conn:
            cls.keys = []
            for number in range(1, cls.COUNT + 1):
                values = {"name": f"P{number}", "start": GROUND if number == 1 else ref(number - 1),
                          "start_level_m": 230.0, "gradient_pct": 1.0}
                cls.keys.append([])
                for param, value in values.items():
                    key = params.entity_key(code(number), param)
                    store.create(conn, key, value, kind="ADOPTADO", source="Prueba",
                                 source_kind="person", decided_by="Samuel (IMGA)",
                                 reason="Prueba de escala", version=cls.v1.code)
                    cls.keys[-1].append(key)
        cls.clock.advance(minutes=1)
        with cls.project.write_transaction() as conn:
            for number, keys in enumerate(cls.keys, start=1):
                handle = operations.begin_in_transaction(
                    conn, cls.project, OP_TYPE, settings={"code": code(number)}, params=keys,
                    executor="blender", version=cls.v1.uid)
                handle.complete(conn)

    def test_the_registry_with_200_entities_in_a_third_of_a_second(self) -> None:
        """T03: la consulta con 200 entidades (con su operación vigente y su estado deducido) en
        ≤ 0,3 s (mediana de 5), sin escribir nada; y la cadena de las 200, andada de punta a punta,
        en la misma cuenta."""
        timings = []
        found: Any = None
        before = change_counter(self.root)
        for _ in range(5):
            started = time.perf_counter()
            found = entities.registry(self.project, self.v1.uid)
            timings.append(time.perf_counter() - started)
        self.assertEqual(len(found), self.COUNT)
        self.assertTrue(all(item.record.state is State.CURRENT for item in found))
        self.assertTrue(all(item.operation_uid for item in found))
        self.assertLessEqual(statistics.median(timings), self.BUDGET_S, timings)
        self.assertEqual(change_counter(self.root), before)
        started = time.perf_counter()
        chain = entities.chain_of(found.records, "P1")
        tails = entities.chain_tails(found.records)
        self.assertLessEqual(time.perf_counter() - started, 0.05)
        self.assertEqual((len(chain), numbers(tails)), (self.COUNT, [self.COUNT]))


class RegistryBrokenTest(efx.EntityProjectCase):
    """RF-015-01: una entidad con parámetros y sin nombre."""

    STEP_M = qfx.COARSE_STEP_M

    def test_an_entity_without_name_is_refused(self) -> None:
        """RF-015-01: una entidad con parámetros y sin nombre es un dato roto: el registro dice
        cuál (``des.entity_name_missing``), no lista una entidad sin nombre."""
        core_params.register_families(params.ENTITY_FAMILIES)
        self.addCleanup(core_params.unregister_families, "des")
        store = core_params.ParameterStore(self.project)
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            store.create(conn, params.entity_key("PLT-077", "start_level_m"), 1.0,
                         kind="ADOPTADO", source="Prueba", source_kind="person",
                         decided_by="Samuel (IMGA)", reason="Prueba", version=self.v1.code)
        with self.assertRaises(messages.DesignError) as caught:
            entities.registry(self.project, self.v1.uid)
        self.assertEqual(caught.exception.code, "des.entity_name_missing")
        self.assertIn("PLT-077", caught.exception.obj)
