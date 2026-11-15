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


class RefusedChangesTest(ParameterRulesCase):
    """Lo que se rechaza **sin escribir nada** (y lo válido de al lado que se admite): el nombre y la geometría
    (A-2, RF-015-01), la partida (A-2, RF-015-04), lo que protege (B-1, RF-015-12) y el apoyo (A-1, RF-015-05,
    RF-015-15)."""

    # --- El nombre, la capa y la geometría (RF-015-01) ---------------------------------------------

    def test_name_a_a_name_another_entity_has_is_refused_also_when_it_gives_the_same_data_name(self) -> None:
        """RF-015-01: el nombre de P1 para P2, y el que da el mismo nombre de dato («plataforma DE carga!»), se
        rechazan con ``des.entity_name_repeated``, con la entidad que ya lo tiene, el campo y el valor; el nombre
        de la propia entidad (sin cambiar de nombre) no choca consigo misma."""
        field = key("PLT-002", "name")
        for value in (LOADING, "plataforma DE carga!"):
            with self.subTest(value=value):
                error = self.refused(field, value, "des.entity_name_repeated", other=LOADING)
                self.assertEqual(error.values["version"], "V01")
        self.accepted(field, WORKSHOP)

    def test_name_b_an_empty_name_is_refused(self) -> None:
        """RF-015-01: un nombre vacío (o en blanco) se rechaza con ``des.entity_param_missing``, con la entidad, el
        campo y la capa: antes se aceptaba y ``entities.registry()`` lanzaba ``des.entity_name_missing`` (rompía
        preparar, congelar y la barra N de la versión)."""
        field = key("PLT-002", "name")
        for value in (None, "", "   "):
            with self.subTest(value=value):
                before = self.snapshot()
                with self.assertRaises(messages.DesignError) as caught:
                    self.check(field, value)
                self.assertEqual(caught.exception.code, "des.entity_param_missing")
                self.assertEqual(caught.exception.values["field"], field)
                self.assertEqual(caught.exception.values["entity"], WORKSHOP)
                self.assertEqual(caught.exception.values["layer"], LAYER)
                self.assertEqual(self.snapshot(), before)

    def test_name_c_the_layer_and_the_feature_cannot_be_emptied(self) -> None:
        """RF-015-01, RF-015-08: la capa y la geometría de la entidad no se vacían (como al crearla)."""
        for param in ("layer", "feature"):
            for value in (None, ""):
                with self.subTest(param=param, value=value):
                    with self.assertRaises(messages.DesignError) as caught:
                        self.check(key("PLT-001", param), value)
                    self.assertEqual(caught.exception.code, "des.entity_param_missing")
                    self.assertEqual(caught.exception.values["field"], key("PLT-001", param))
                    self.assertEqual(caught.exception.values["entity"], LOADING)

    # --- La partida (RF-015-04) ---------------------------------------------------------------

    def test_start_a_the_surface_another_entity_starts_from_is_refused(self) -> None:
        """RF-015-04: P2 partiendo del terreno (de donde parte P1) se rechaza con ``des.entity_start_taken`` con la
        entidad que ya parte de él; P1 partiendo de la superficie de P2 (un ciclo), y P2 de la suya, con
        ``des.entity_chain_cycle`` con la vuelta; todo sin escribir. Antes se aceptaba y bloqueaba congelar."""
        error = self.refused(key("PLT-002", "start"), GROUND, "des.entity_start_taken", entity=WORKSHOP, other=LOADING)
        self.assertIn(LOADING, error.text)
        cycle = self.refused(key("PLT-001", "start"), "entity:PLT-002", "des.entity_chain_cycle", chain=True)
        self.assertIn(" → ".join(f"«{name}»" for name in (WORKSHOP, LOADING, WORKSHOP)), cycle.text)
        self.refused(key("PLT-002", "start"), "entity:PLT-002", "des.entity_chain_cycle", chain=True)
        self.refused(key("PLT-001", "start"), "entity:PLT-001", "des.entity_start_taken", entity=LOADING,
                     other=WORKSHOP)  # la superficie de P1 ya la tiene como partida P2

    def test_start_b_an_empty_start_is_refused(self) -> None:
        """RF-015-04, RF-015-08: una entidad no queda sin superficie de partida."""
        for value in (None, ""):
            with self.subTest(value=value):
                with self.assertRaises(messages.DesignError) as caught:
                    self.check(key("PLT-002", "start"), value)
                self.assertEqual(caught.exception.code, "des.entity_param_missing")
                self.assertEqual(caught.exception.values["entity"], WORKSHOP)

    def test_start_c_a_free_surface_is_accepted(self) -> None:
        """RF-015-04: partir de una superficie que ninguna otra entidad usa (aquí la del hueco) y volver a la
        suya se admiten."""
        self.accepted(key("PLT-002", "start"), HOLE)
        self.accepted(key("PLT-002", "start"), "entity:PLT-001")

    # --- Lo que protege (RF-015-12) -----------------------------------------------------------

    def test_protect_a_cut_and_fill_in_an_entity_that_protects_is_refused(self) -> None:
        """RF-015-12: el modo de P2, que protege, a «en corte y relleno» se rechaza con
        ``des.platform_protect_cut_fill`` con la entidad, la capa, el campo y el valor; antes se aceptaba y
        ninguna de las demás entidades declaraba su protección mientras tanto."""
        error = self.refused(key("PLT-002", "mode"), "cut_fill", "des.platform_protect_cut_fill",
                             entity=WORKSHOP, layer=LAYER)
        self.assertIn("en el modo «en corte y relleno»", error.text)

    def test_protect_b_protecting_without_a_guard_is_refused(self) -> None:
        """RF-015-12, RF-015-10 (D-19): P1, que no protege y no tiene resguardo, no pasa a proteger (sin el
        resguardo no se declara nada: ``des.entity_param_missing`` con su campo); y P2, que protege, no se queda
        sin él."""
        before = self.snapshot()
        with self.assertRaises(messages.DesignError) as caught:
            self.check(key("PLT-001", "protect"), True)
        error = caught.exception
        self.assertEqual((error.code, error.values["field"]), ("des.entity_param_missing", key("PLT-001", "guard_m")))
        self.assertEqual((error.values["entity"], error.values["layer"]), (LOADING, LAYER))
        self.assertIn(LOADING, error.text)
        with self.assertRaises(messages.DesignError) as caught:
            self.check(key("PLT-002", "guard_m"), None)
        self.assertEqual((caught.exception.code, caught.exception.values["field"]),
                         ("des.entity_param_missing", key("PLT-002", "guard_m")))
        self.assertEqual(self.snapshot(), before)

    def test_protect_c_what_is_coherent_is_accepted(self) -> None:
        """RF-015-12: el modo «en corte y relleno» de P1 (que no protege), dejar de proteger P2 y cambiar su resguardo
        se admiten."""
        self.accepted(key("PLT-001", "mode"), "cut_fill")
        self.accepted(key("PLT-002", "protect"), False)
        self.accepted(key("PLT-002", "guard_m"), 6.0)

    # --- El apoyo (RF-015-05, RF-015-15) ------------------------------------------------------

    def test_support_a_inserting_before_with_the_support_on_what_will_follow_is_refused(self) -> None:
        """RF-015-05, A-1: insertar N **antes de P1** con apoyo en la superficie de P2 (que pasará a partir de P1,
        que pasará a partir de N) se rechaza con ``des.entity_supports_unknown`` con el motivo del ciclo, el campo y la
        entidad, sin escribir; también con el apoyo en la de P1 (la sucesora) o por el nombre del dato de la
        superficie. Antes se aceptaba, se creaba y «Recalcular lo obsoleto» tardaba tres pasadas."""
        for support in ("entity:PLT-002", "entity:PLT-001", PSF_WORKSHOP):
            with self.subTest(support=support):
                before = self.snapshot()
                with self.assertRaises(messages.DesignError) as caught:
                    self.units(prep.request("Nueva", feature=TOWER, support=support), insert_before="PLT-001")
                error = caught.exception
                self.assertEqual(error.code, "des.entity_supports_unknown")
                self.assertEqual(error.values["field"], key("PLT-003", "support"))
                self.assertEqual(error.values["value"], support)
                self.assertEqual(error.values["entity"], "Nueva")
                self.assertIn("sería un ciclo", error.text)
                self.assertEqual(self.snapshot(), before)

    def test_support_b_what_is_before_the_new_one_is_a_valid_support(self) -> None:
        """RF-015-15: insertar N antes de P2 apoyada en P1 (lo que queda antes de N), o antes de P1 apoyada en el
        terreno, se admite: solo es un ciclo apoyarse en lo que va después."""
        new = prep.request("Nueva", feature=TOWER, start="entity:PLT-001", support="entity:PLT-001")
        self.assertEqual(self.units(new, insert_before="PLT-002").support_surface, PSF_LOADING)
        prepared = self.units(prep.request("Nueva", feature=TOWER, support=GROUND), insert_before="PLT-001")
        self.assertEqual(prepared.support_surface, GROUND)

    def test_support_c_an_existing_entity_cannot_rest_on_itself_or_on_its_successor(self) -> None:
        """RF-015-15, A-1: P1 (recalcularla o calcular la que ya está en la versión) con apoyo en P2 (la sucesora) o
        en su propia superficie se rechaza; P2 apoyada en P1 (su antecesora) y una entidad nueva apoyada en P2, no."""
        for support in ("entity:PLT-002", "entity:PLT-001"):
            with self.subTest(support=support):
                with self.assertRaises(messages.DesignError) as caught:
                    self.units(prep.request(support=support), code="PLT-001", supersedes=self.current("PLT-001"))
                self.assertEqual(caught.exception.code, "des.entity_supports_unknown")
                self.assertEqual(caught.exception.values["field"], key("PLT-001", "support"))
        again = prep.request(WORKSHOP, start="entity:PLT-001", support="entity:PLT-001", protect=True, guard_m=4.0)
        self.units(again, code="PLT-002", supersedes=self.current("PLT-002"))
        self.units(prep.request("Tercera", feature=TOWER, start=HOLE, support="entity:PLT-002"))

    def test_support_d_changing_the_support_of_an_entity_by_its_parameter_follows_the_same_rule(self) -> None:
        """RF-015-15, A-1: «Cambiar parámetro…» de la superficie de apoyo de P1 a la de P2 (o a la suya) se
        rechaza con el mismo código que al preparar; la de P2 a la de P1, o quitarla, se admiten."""
        field = key("PLT-001", "support")
        self.refused(field, "entity:PLT-002", "des.entity_supports_unknown", entity=LOADING)
        self.refused(field, "entity:PLT-001", "des.entity_supports_unknown", entity=LOADING)
        self.refused(field, PSF_WORKSHOP, "des.entity_supports_unknown", entity=LOADING)
        self.accepted(key("PLT-002", "support"), "entity:PLT-001")
        self.accepted(field, None)

    # --- Lo que no es de estas reglas ---------------------------------------------------------

    def test_other_a_other_keys_and_other_values_pass(self) -> None:
        """RF-015-01: una clave que no es de una entidad, la de una entidad que no está en la versión y los valores que
        no entran en las reglas entre entidades (la pendiente, el alcance) no los comprueba: lo suyo es de
        ``ParamDef``; sin versión, o con una que no existe, nada (lo dice el almacén de parámetros)."""
        self.accepted("des.bench.expl.height_m", 5.0)
        self.accepted(key("PLT-009", "name"), LOADING)
        self.accepted(key("PLT-001", "gradient_pct"), 1.5)
        self.accepted(key("PLT-002", "reach_m"), 12.0)
        self.accepted(key("PLT-002", "name"), 5)  # un valor que no es del tipo: lo dice su definición
        entity_store.check_parameter_change(self.project, key("PLT-002", "name"), LOADING, version=None)
        entity_store.check_parameter_change(self.project, key("PLT-002", "name"), LOADING, version="V99")


class ValidChangesTest(ParameterRulesCase):
    """RF-015-01, RF-015-04 y RF-015-12: lo válido sigue admitido y se aplica."""

    def change_checked(self, param_key: str, value: object) -> None:
        """Lo que hace la orden: comprobar y escribir con el almacén de parámetros."""
        self.check(param_key, value)
        self.change(param_key, value)

    def test_z_renaming_and_changing_the_start_to_a_free_surface_still_work(self) -> None:
        """RF-015-01, RF-015-04: renombrar P2 con un nombre libre y cambiar su partida a una superficie libre se
        aceptan y quedan en el registro; el modo «en corte y relleno» de P1 (que no protege) también."""
        self.change_checked(key("PLT-002", "name"), "Taller nuevo")
        self.change_checked(key("PLT-002", "start"), HOLE)
        self.change_checked(key("PLT-001", "mode"), "cut_fill")
        registry = entities.registry(self.project, self.v1.uid)
        self.assertEqual({item.code: (item.name, item.start) for item in registry.records},
                         {"PLT-001": (LOADING, GROUND), "PLT-002": ("Taller nuevo", HOLE)})
        self.assertEqual(core_params.ParameterStore(self.project).get(
            key("PLT-001", "mode"), version=self.v1.uid).value, "cut_fill")

    def test_a_name_that_looks_like_a_code_does_not_make_the_entity_of_that_code(self) -> None:
        """RF-015-01: una entidad **llamada** «PLT-009» no es la entidad de código ``PLT-009`` (que no existe): el
        cambio de una clave de esa entidad que no está en la versión no se comprueba contra la que tiene ese nombre."""
        self.change_checked(key("PLT-002", "name"), "PLT-009")
        self.accepted(key("PLT-009", "name"), LOADING)


if __name__ == "__main__":
    unittest.main()
