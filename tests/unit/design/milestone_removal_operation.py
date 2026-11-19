# SPDX-License-Identifier: GPL-3.0-or-later
"""La orden de retirar con **lo que se apoyaba** en el acopio, con proyecto (spec 016, T20; HU-016-2; RF-016-14, RF-015-15, RF-015-17,
CE-016-04; plan 016 §5.4 A7 y A13, §5.7 P-9; ADR-0031 §4; error 59). Va al paso «hito» de ``check.py --completo`` (P-13: la rejilla de 2 m
con proyecto y dos plataformas); el resto de la orden está en ``test_removal_operation.py``, en el «verde».

La cantera de los acopios de 2 m con la detección ``Acopios`` (``STK-001``, V01) y dos plataformas «en corte y relleno» de la 015 que
rellenan por encima de un acopio cada una: «Sobre el acopio 4» (``PLT-001``, parte del levantamiento) y «Sobre el acopio 3»
(``PLT-002``, parte de la superficie de la primera). Lo que ``milestone_removal_resting.py`` (T18) hacía con una retirada **a mano** lo
hace aquí **la orden real**: «Calcular» la retirada del Acopio 4 desde la superficie de ``PLT-002``, la lista única de lo que se le apoya,
la negativa a crear sin confirmarlo, «Crear» y el relleno en «apoyo retirado».
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender
from tests.unit.design import milestone_removal_resting as resting
from tests.unit.design import milestone_stockpile_supports as sup
from tests.unit.design import test_removal_operation as ops

entities = import_geoblender("design.entities")
messages = import_geoblender("design.messages")
provenance = import_geoblender("design.provenance")
removal = import_geoblender("design.removal")
supported_store = import_geoblender("design.supported_store")

State = entities.EntityState
FOUR, THREE = sup.FOUR, sup.THREE
REMOVAL = "Retirada del acopio 4"
TWO_SURFACE = provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, THREE)


class RestingOnRemovalTest(ops.RemovalCase):
    """RF-016-14, RF-015-17, CE-016-04, P-9, **en orden** (``test_a`` a ``test_c``): la lista de lo que se le apoya al Acopio 4 antes de
    calcular, la negativa a crear sin confirmarla y, creada, el relleno en «apoyo retirado»."""

    created: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.detect()
        qfx.write_feature_layer(cls.project, cls.clock, resting.axes_layer())
        cls.clock.advance(minutes=1)
        cls.made(sup.over(FOUR))
        cls.made(sup.over(THREE, start="entity:PLT-001"))

    def test_a_what_rests_on_the_stockpile_is_one_list_before_calculating_and_is_not_created_unconfirmed(self) -> None:
        """RF-016-14, RF-015-17 (CE-016-04), RF-015-03: retirar el Acopio 4 desde la superficie de «Sobre el acopio 3» da **una sola
        lista** antes de calcular —«Sobre el acopio 4», con su tipo y su volumen **a mano** a ≤ 10⁻⁹ relativo— y su aviso, sin escribir
        nada; «Crear» sin confirmarlo se rechaza (``des.removal_resting_unconfirmed``) **sin escribir nada y sin cerrar el cálculo**."""
        before = self.state()
        listed = supported_store.resting_preview(self.project, self.v1.uid, "STK-001#Acopio 4", "entity:PLT-002")
        self.assertEqual(self.state(), before, "la lista del diálogo solo lee")
        calculation = self.calculate(ops.asked(REMOVAL, "Acopio 4", start="entity:PLT-002"))
        self.assertEqual(listed, calculation.entity.resting, "la lista del diálogo es la que luego calcula la orden")
        self.assertEqual(supported_store.resting_preview(self.project, self.v1.uid, "STK-001#Acopio 1", "entity:PLT-002"), (),
                         "nada se apoya en el Acopio 1")
        self.assertEqual(len(self.temporaries()), 1)
        self.assertEqual({key: value for key, value in self.state().items() if key != "files"},
                         {key: value for key, value in before.items() if key != "files"}, "calcular no escribe")
        (row,) = calculation.summary.resting
        self.assertEqual((row.name, row.kind), (FOUR, "Plataforma"))
        self.assertRelative(row.volume_m3, self.by_hand("Acopio 4", sup.LEVEL_4), "a mano")
        self.assertEqual(row.volume_m3, calculation.entity.resting[0].volume_m3)
        self.assertIn("des.removal_resting", [notice.code for notice in calculation.notices])
        self.assertTrue(calculation.needs_resting_confirmation)
        self.assertGreater(calculation.outcome.resting_m3, 0.0, "lo apoyado, por encima de la superficie con que se detectó")
        with self.assertRaises(messages.DesignError) as caught:
            calculation.create(decided_by=ops.USER)
        self.assertEqual(caught.exception.code, "des.removal_resting_unconfirmed")
        self.assertEqual(caught.exception.values["stockpile"], "Acopio 4")
        self.assertTrue(calculation.open, "sin cerrar el cálculo")
        calculation.discard()
        self.assertEqual(self.state(), before)
        self.assertEqual(self.temporaries(), [])

    def test_b_creating_with_the_confirmation_records_who_confirmed_and_leaves_the_fill_with_its_support_removed(self) -> None:
        """RF-016-14, RF-015-17, P-9 (CE-016-04): con la confirmación expresa se crea (``RMV-001``) y queda anotada en los ajustes de la
        operación (los m³ confirmados, quién y cuándo); el relleno que se apoyaba en ese acopio queda en **«apoyo retirado»** —con su
        causa, nombrando el acopio y la retirada— **sin que se haya descartado nada**; lo que se apoya en otro acopio y la detección, al día."""
        _calculation, stored = self.make(ops.asked(REMOVAL, "Acopio 4", start="entity:PLT-002"), confirm={"resting": True})
        type(self).created = stored
        uid = str(stored.handle.uid)
        settings = json.loads(self.query("SELECT settings FROM gb_operation WHERE uid = ?", uid)[0][0])
        confirmed = supported_store.confirmed_of(settings)
        assert confirmed is not None
        self.assertEqual(confirmed.decided_by, ops.USER)
        self.assertRelative(confirmed.resting_m3 or 0.0, self.by_hand("Acopio 4", sup.LEVEL_4), "lo confirmado")
        self.assertIsNone(confirmed.wall_height_m)
        states = {entry.record.code: entry.record.state for entry in entities.registry(self.project, self.v1.uid)}
        self.assertEqual(states, {"STK-001": State.CURRENT, "PLT-001": State.SUPPORT_REMOVED, "PLT-002": State.CURRENT,
                                  "RMV-001": State.CURRENT})
        self.assertEqual(self.query("SELECT COUNT(*) FROM gb_dataset WHERE status = 'discarded'"), [(0,)], "nada se descartó")
        why = entities.stale_reason(self.project, self.v1.uid, "PLT-001")
        assert why is not None
        self.assertIn("Acopio 4", why)
        self.assertIn(REMOVAL, why)
        self.assertEqual(self.supports_of(str(stored.handle.uid)), [])

    def test_c_the_removal_consumes_the_stockpile_with_the_role_the_graph_reads(self) -> None:
        """RF-016-14, P-9: lo que la retirada anota para que el grafo la lea —el parámetro del acopio, tal como lo leyó, y sus datos con el
        papel ``removed_stockpile``— es lo que hace que quien se apoyaba en él quede en «apoyo retirado»; descartar la retirada lo
        devuelve (el dato vuelve al relleno)."""
        removals = entities.removed_supports_of(self.project, self.v1.uid, self.uid_of("PLT-001"))
        (found,) = removals
        self.assertEqual((found.stockpile, found.detection, found.key, found.code, found.removal),
                         ("STK-001#Acopio 4", "STK-001", "Acopio 4", "RMV-001", REMOVAL))
        self.assertEqual(entities.removed_supports_of(self.project, self.v1.uid, self.uid_of("PLT-002")), (),
                         "la que se apoya en otro acopio no pierde nada")
        entity_store = import_geoblender("design.entity_store")
        entity_store.discard_entity(self.project, self.v1.uid, "RMV-001", reason="Se queda el acopio", decided_by=ops.USER)
        states = {entry.record.code: entry.record.state for entry in entities.registry(self.project, self.v1.uid)}
        self.assertEqual(states["PLT-001"], State.CURRENT, "descartar la retirada devuelve el apoyo")
