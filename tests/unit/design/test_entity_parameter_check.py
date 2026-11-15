# SPDX-License-Identifier: GPL-3.0-or-later
"""Validar al editar un parámetro de una entidad, con su nombre en el rechazo (spec 015, T39; hallazgos A-2, A-1 y
B-1 de la verificación única; RF-015-01, RF-015-04, RF-015-05, RF-015-08, RF-015-12).

«Proyecto ▸ Cambiar parámetro…» (``geoblender.core_set_parameter``) solo comprobaba el tipo y el rango de la
definición (``ParamDef``), no las reglas **entre** entidades que sí se aplican al crear: el nombre único, una
entidad por superficie y sin ciclos, y no proteger en «en corte y relleno» ni sin resguardo.
``design.entity_store.check_parameter_change`` las aplica a una clave ``des.platform.{e}.*`` **antes** de que la orden
escriba, con la entidad, el campo y el valor en el rechazo y **sin escribir nada** (el contador de cambios de la base no
se mueve). Lo de A-1 (la superficie de apoyo de una entidad que sería un ciclo, también al insertar antes de otra) lo
rechaza la preparación (``prepare_platform_units``), que es la misma de «Calcular».

Sobre la cantera de la 014 con P1 «Plataforma de carga» (del terreno), P2 «Plataforma de taller» (de la superficie de
P1, que protege con 4 m de resguardo, en el modo «en corte»), creadas con operaciones reales. Una clase que solo lee
(todas las que rechazan: un montaje) y otra que acepta lo válido y lo escribe (otro, aparte).
"""

from __future__ import annotations

import unittest
from typing import Any

from tests.support.package import import_geoblender
from tests.support.versions_fixtures import change_counter
from tests.unit.design import test_entities_chain as chain
from tests.unit.design import test_platform_operation as ops_test
from tests.unit.design import test_platform_prepare as prep

core_params = import_geoblender("core.params")
design_params = import_geoblender("design.params")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
messages = import_geoblender("design.messages")
provenance = import_geoblender("design.provenance")

LOADING, WORKSHOP, TOWER = prep.LOADING, prep.WORKSHOP, prep.TOWER
GROUND = prep.START
HOLE = prep.HOLE_DATASET
LAYER = "gis_fea_plataformas_ejes"
"""La capa de la que salen las plataformas de la prueba (la de los ejes de ``entity_data``)."""
PSF_WORKSHOP = provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, WORKSHOP)
PSF_LOADING = provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, LOADING)


def key(code: str, param: str) -> str:
    return design_params.entity_key(code, param)


class UnsupportableTest(unittest.TestCase):
    """RF-015-15, RF-015-05 (A-1): dónde no puede apoyarse una entidad (sin proyecto: ``entities.unsupportable``)."""

    def setUp(self) -> None:
        self.records = [chain.rec(1, chain.GROUND), chain.rec(2, chain.ref(1)), chain.rec(3, chain.ref(2))]

    def test_an_existing_entity_counts_itself_and_what_follows_it(self) -> None:
        """RF-015-15: P2 no se apoya en P2 ni en P3 (parte de su superficie) y sí en P1 (la antecesora); la
        última, solo en sí misma."""
        self.assertEqual(entities.unsupportable(self.records, "PLT-002"), {"PLT-002", "PLT-003"})
        self.assertEqual(entities.unsupportable(self.records, "PLT-001"), {"PLT-001", "PLT-002", "PLT-003"})
        self.assertEqual(entities.unsupportable(self.records, "PLT-003"), {"PLT-003"})

    def test_a_new_entity_counts_what_follows_the_one_it_is_inserted_before(self) -> None:
        """RF-015-05, A-1: la nueva (que aún no está en la versión) insertada antes de P2 no se apoya en P2 ni en P3
        (pasarán a partir de ella) y sí en P1; por el código o por el nombre de la sucesora; sin inserción, solo
        cuenta consigo misma; una sucesora que no existe no cuenta."""
        self.assertEqual(entities.unsupportable(self.records, "PLT-004", insert_before="PLT-002"),
                         {"PLT-004", "PLT-002", "PLT-003"})
        self.assertEqual(entities.unsupportable(self.records, "PLT-004", insert_before="P1"),
                         {"PLT-004", "PLT-001", "PLT-002", "PLT-003"})
        self.assertEqual(entities.unsupportable(self.records, "PLT-004"), {"PLT-004"})
        self.assertEqual(entities.unsupportable(self.records, "PLT-004", insert_before="Otra"), {"PLT-004"})

    def test_a_discarded_entity_is_a_record_and_does_not_follow(self) -> None:
        """RF-015-17: una entidad descartada no sigue a nadie en la cadena (no se cuenta aguas abajo)."""
        records = [chain.rec(1, chain.GROUND), chain.rec(2, chain.ref(1), state=entities.EntityState.DISCARDED)]
        self.assertEqual(entities.unsupportable(records, "PLT-001"), {"PLT-001"})


class ParameterRulesCase(ops_test.RecomputeCase):
    """V01 con P1 «Plataforma de carga» (del terreno) y P2 «Plataforma de taller» (de la superficie de P1, que protege
    con 4 m de resguardo), y las ayudas de las pruebas."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.made(prep.request())
        cls.made(prep.request(WORKSHOP, start="entity:PLT-001", protect=True, guard_m=4.0))

    def snapshot(self) -> tuple[Any, ...]:
        """Todo lo que podría escribir una orden, con el contador de cambios de la base (lo sube toda transacción)."""
        return (change_counter(self.root), self.written())

    def check(self, param_key: str, value: object) -> None:
        """Lo que hace la orden «Cambiar parámetro…» antes de escribir: la comprobación de la entidad en V01."""
        entity_store.check_parameter_change(self.project, param_key, value, version=self.v1.uid)

    def refused(self, param_key: str, value: object, expected: str, *, chain: bool = False, **names: Any) -> Any:
        """Cambiar ``param_key`` a ``value`` se rechaza con el código ``expected`` y **no escribe nada**; el rechazo
        nombra el campo (la clave; el de la cadena de entidades, con ``chain``, es ``start`` y da de valor la
        superficie de partida de la primera entidad de la vuelta), el valor y lo de ``names`` (en sus valores y
        en su texto)."""
        before = self.snapshot()
        with self.assertRaises(messages.DesignError) as caught:
            self.check(param_key, value)
        error = caught.exception
        self.assertEqual(error.code, expected)
        self.assertEqual(error.values["field"], "start" if chain else param_key)
        if not chain:
            self.assertEqual(error.values["value"], value)
        for name, wanted in names.items():
            self.assertEqual(error.values[name], wanted, name)
            self.assertIn(str(wanted), error.text, name)
        self.assertEqual(self.snapshot(), before, "el rechazo ha escrito algo")
        return error

    def accepted(self, param_key: str, value: object) -> None:
        """La comprobación deja pasar el cambio y tampoco escribe nada (lo escribe la orden después)."""
        before = self.snapshot()
        self.check(param_key, value)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
