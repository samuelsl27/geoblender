# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que sigue a cada orden de entidades en una versión que **tiene una detección de acopios** (spec 016, T21, arreglo previo;
RF-015-10, RF-015-27, RF-016-14; hallazgo de la T20 (b), aviso 3).

La detección de acopios (``STK-001``) es una entidad **sin tabla de huella**: deja la tabla de sus acopios (``des_stk_``) y las
rejillas dispersas, y no la fila ``des_epr_`` que la declaración de restricciones y la capa de entidades leen de toda entidad viva.
Antes del arreglo, ``after_entity_change`` fallaba en sus dos etapas en cuanto la versión tenía una (la declaración, «``mode`` no es un
valor de stockpile»; la capa, «escribió 0 tablas de la entidad, no una») y salía como dos avisos de la cadena, **también para las
órdenes de la 015**. Ahora las dos etapas saltan los tipos sin tabla de huella (:attr:`~geoblender.design.entities.EntityType.
has_footprint`); la retirada y la plataforma, que sí la tienen, salen en la capa.

La cantera de los acopios de 2 m con la detección ``Acopios`` (``STK-001``, V01), la plataforma «Sobre el acopio 4» de la 015 y la
retirada del Acopio 1, **en orden** (``test_a`` a ``test_d``).
"""

from __future__ import annotations

from typing import Any, ClassVar

from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender
from tests.unit.design import milestone_stockpile_supports as sup
from tests.unit.design import test_removal_operation as rem
from tests.unit.design import test_stockpile_operation as ops

entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")


class ChainWithDetectionTest(rem.RemovalCase):
    """RF-015-10, RF-015-27: la declaración y la capa de entidades con una detección en la versión."""

    chain: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.detect()
        qfx.write_feature_layer(cls.project, cls.clock, sup.axes_layer())
        cls.clock.advance(minutes=1)

    def chain_of(self) -> Any:
        """Lo que hace ``after_entity_change`` en V01 (``EntityChain``)."""
        return ops.last(entity_store.after_entity_change(self.project, self.v1.uid))

    def assertWhole(self, chain: Any, layer: int) -> None:  # noqa: N802
        """Las dos etapas salieron bien (sin fallo de la declaración ni de la capa) y la capa enseña ``layer`` entidades."""
        self.assertIsNone(chain.failure, f"la declaración falló: {None if chain.failure is None else chain.failure.reason}")
        self.assertIsNone(chain.layer_failure,
                          f"la capa falló: {None if chain.layer_failure is None else chain.layer_failure.reason}")
        self.assertEqual((chain.declared, chain.layer), (0, layer))
        self.assertFalse([item for item in chain.notices() if item.code.endswith("_failed")], "ningún aviso de fallo")

    def test_a_a_version_with_only_the_detection_declares_nothing_and_shows_no_entity(self) -> None:
        """RF-015-10, RF-015-27: con solo la detección (``STK-001``, **sin ``des_epr_``**) la declaración sale vacía y la capa de entidades
        no enseña ninguna (el acopio no es una fila de la capa: eso es de la T34); ninguna etapa falla ni lo avisa."""
        entry = entities.registry(self.project, self.v1.uid).get("STK-001")
        assert entry is not None
        self.assertFalse(entities.entity_type(entry.record.kind).has_footprint, "la detección no tiene tabla de huella")
        self.assertEqual(entity_store.declared_sources(self.project, self.v1), ())
        self.assertEqual(entity_store.layer_sources(self.project, self.v1), ())
        self.assertWhole(self.chain_of(), 0)

    def test_b_a_platform_of_the_015_next_to_the_detection_chains_without_failures(self) -> None:
        """RF-015-10, RF-015-27 (la orden «Plataforma…» de la 015 en una versión con detección): crear «Sobre el acopio 4» y encadenar lo
        que sigue **no falla** en ninguna de las dos etapas, y la capa enseña la plataforma (una fila, la de su tipo con huella), no la
        detección."""
        self.made(sup.over(sup.FOUR))
        chain = self.chain_of()
        self.assertWhole(chain, 1)
        shown = entity_store.layer_sources(self.project, self.v1)
        self.assertEqual([(item.code, item.name) for item in shown], [("PLT-001", sup.FOUR)])
        self.assertEqual([item.code for item in entity_store.declared_sources(self.project, self.v1)], ["PLT-001"])
        with self.project.read() as conn:
            self.assertFalse(entity_store.layer_pending(self.project, conn, self.v1.uid), "la capa dice lo que el registro")
            self.assertFalse(entity_store.declaration_pending(self.project, conn, self.v1.uid))

    def test_c_a_removal_of_a_stockpile_chains_without_failures_and_shows_in_the_layer(self) -> None:
        """RF-015-10, RF-015-27, RF-016-11: tras retirar el Acopio 1 (``RMV-001``, que **sí** deja su ``des_epr_``) lo que sigue no falla
        y la capa enseña las dos entidades con huella (la plataforma y la retirada), no la detección; la retirada no protege ni declara."""
        self.make(rem.asked(start="entity:PLT-001"))  # de cada superficie parte una sola entidad (RF-015-04)
        chain = self.chain_of()
        self.assertWhole(chain, 2)
        shown = entity_store.layer_sources(self.project, self.v1)
        self.assertEqual([item.code for item in shown], ["PLT-001", "RMV-001"])
        self.assertEqual({item.code for item in entity_store.declared_sources(self.project, self.v1)}, {"PLT-001", "RMV-001"})
        self.assertEqual([item.protect for item in entity_store.declared_sources(self.project, self.v1)], [False, False])

    def test_d_repeating_the_chain_changes_nothing(self) -> None:
        """RF-015-10 (idempotente): repetir lo que sigue a una orden da el mismo contenido de la declaración y de la capa."""
        again = self.chain_of()
        self.assertWhole(again, 2)
        self.assertFalse(again.declaration_changed)
        self.assertFalse(again.layer_changed)
