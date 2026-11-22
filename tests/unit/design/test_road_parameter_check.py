# SPDX-License-Identifier: GPL-3.0-or-later
"""Validar al editar un parámetro de una pista, con su nombre en el rechazo (spec 017, T22b; HU-017-1; RF-017-01, RF-017-03; RF-015-01, RF-015-04, RF-015-08, RF-015-12 y RF-015-15; los hallazgos A-2 de la
015 y D-2 de la 016, con la pista).

«Proyecto ▸ Cambiar parámetro…» (``geoblender.core_set_parameter``) pasa por las reglas **entre** entidades de crear (``design.entity_store.check_parameter_change``) para una clave
``des.<tipo>.{e}.*`` de **cualquier tipo registrado** (``bl.ops.des.PARAMETER_PREFIXES``: la 017 añadió ``des.road.`` y ``des.access.`` en la T03): el nombre único y no vacío (también como nombre
de dato), la capa, la partida —de cada superficie parte una entidad y la cadena no da la vuelta—, el apoyo —ni la superficie de la propia pista ni la de una que parte de la suya— y, **de la pista, ninguna
regla de lo que declara**: no tiene ``protect`` ni ``guard_m`` (RF-017-01, D-15) y su ``mode`` no es el de la plataforma. Siempre con **lo mismo que dice crear**, antes de que la orden escriba y **sin
escribir nada** (el contador de cambios de la base no se mueve).

Sobre la cantera de la 014 (rejilla gruesa) con las cinco entidades de la cadena de la T21 escritas como **parámetros de versión** (sin operación: el registro las lista «sin calcular», que es todo lo que lee
la comprobación): la plataforma ``PLT-001`` («P1», que protege con 4 m), la «Pista a P1» (``RDW-001``: parte de la superficie de P1), el «Ramal» (``RDW-002``: parte de la de la pista y se apoya en ella), una pista
«sobre un eje» (``RDW-003``: parte del terreno) y la «Relleno sobre la calzada» (``PLT-002``: parte de la del ramal), más —de la T40— dos pistas libres que se apoyan por su origen (``RDW-005`` → ``RDW-004`` → ``RDW-001``) y **el perfil de pista** con sus quince
valores. **El origen y el destino de una pista** (lo que pisa: un punto del eje de otra o una entidad) y **un valor del perfil** (``des.roadprofile.{p}.*``: las reglas de «Perfil de pista…») pasan también por
sus reglas al cambiarlos (T40; hallazgos A-2 y A-1). Con la pista calculada de verdad, lo que sigue al cambio está en ``milestone_road_bring.py`` y ``milestone_road_chain.py``.
"""

from __future__ import annotations

import unittest
from typing import Any

from tests.support import entity_fixtures as efx
from tests.support import quarry_fixtures as qfx
from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.support.versions_fixtures import change_counter

core_params = import_geoblender("core.params")
design_params = import_geoblender("design.params")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
messages = import_geoblender("design.messages")
road_profiles = import_geoblender("design.road_profiles")
road_store = import_geoblender("design.road_store")

GROUND = "gis_dtm_ladera"
OTHER_GROUND = "gis_dtm_levantamiento"
PERSON = "Samuel (IMGA)"
# Código → (nombre, valores que se escriben en V01). La cadena: PLT-001 → RDW-001 → RDW-002 → PLT-002; RDW-003 parte del terreno.
WORLD: dict[str, tuple[str, dict[str, Any]]] = {
    "PLT-001": ("P1", {"layer": "gis_fea_plataformas_ejes", "feature": "Eje 1", "start": OTHER_GROUND, "mode": "cut", "protect": True, "guard_m": 4.0}),
    "RDW-001": ("Pista a P1", {"mode": "trace", "layer": "gis_fea_pistas_a_p1", "profile": "pista_principal", "start": "entity:PLT-001", "origin": "Entrada",
                               "destination": "entity:PLT-001", "supports": "PLT-001"}),
    "RDW-002": ("Ramal", {"mode": "trace", "layer": "gis_fea_pistas_puntos", "profile": "pista_principal", "start": "entity:RDW-001", "support": "entity:RDW-001",
                          "origin": "RDW-001@100", "destination": "Destino del ramal", "supports": "RDW-001"}),
    "RDW-003": ("Pista sobre un eje", {"mode": "on_axis", "layer": "gis_fea_pistas_ejes", "feature": "Eje 1", "profile": "pista_principal", "start": GROUND}),
    "PLT-002": ("Relleno sobre la calzada", {"layer": "gis_fea_plataformas_ejes", "feature": "Eje 2", "start": "entity:RDW-002", "mode": "cut_fill"}),
}
FREE_ROADS: dict[str, tuple[str, dict[str, Any]]] = {
    # Dos pistas libres (cada una parte de un terreno que ninguna otra ocupa) que se apoyan por su origen: RDW-005 → RDW-004 → RDW-001 (spec 017, T40; A-2). Solo las escribe ``RoadParameterTest``.
    "RDW-004": ("Pista libre", {"mode": "trace", "layer": "gis_fea_pistas_puntos", "profile": "pista_principal", "start": "gis_dtm_libre_a", "origin": "RDW-001@40", "destination": "Destino libre"}),
    "RDW-005": ("Pista libre 2", {"mode": "trace", "layer": "gis_fea_pistas_puntos", "profile": "pista_principal", "start": "gis_dtm_libre_b", "origin": "RDW-004@5", "destination": "Destino libre"}),
}
PROFILE = "pista_principal"
"""El perfil de pista de las pruebas (con los valores de referencia de IMGA, ``rd.PROFILE``: A 3,5 m, f 3, arcén 0, caballón 1 m —semianchura 5,75 m—, R 20 m y Rmín 12 m), escrito como parámetros de V01
por ``RoadParameterTest``."""
PROJECT_PROFILE = "pista_del_proyecto"
"""El mismo perfil de referencia, pero con sus quince valores **del proyecto** (sin versión; spec 017, T49, hallazgo T47-1): lo que ven las versiones que no tienen valor propio."""


def key(code: str, param: str) -> str:
    return design_params.entity_key(code, param)


class RoadParameterCase(efx.EntityProjectCase):
    """V01 con las cinco entidades de ``WORLD`` y las ayudas de las pruebas."""

    @classmethod
    def write_extra(cls) -> None:
        """Lo que solo necesita una clase (spec 017, T40): el perfil de pista de ``PROFILE`` con sus quince valores (A-1) y las dos pistas libres de ``FREE_ROADS`` (A-2), como parámetros de V01 y, de la T49, el mismo
        perfil con los quince valores del proyecto (``PROJECT_PROFILE``, T47-1)."""
        core_params.register_families(design_params.ROAD_PROFILE_FAMILIES)
        store = core_params.ParameterStore(cls.project)
        with cls.project.write_transaction() as conn:
            for code, (name, values) in FREE_ROADS.items():
                for param, value in {"name": name, **values}.items():
                    store.create(conn, key(code, param), value, kind="ADOPTADO", source="Prueba de la T40 de la 017", source_kind="person", decided_by=PERSON, reason="Prueba de la T40", version=cls.v1.code)
            for item in design_params.RoadProfileParam:
                value = getattr(rd.PROFILE, "class_name" if item is design_params.RoadProfileParam.CLASS else item.value)
                store.create(conn, design_params.road_profile_key(PROFILE, item), value, kind="ADOPTADO", source="Prueba de la T40 de la 017", source_kind="person", decided_by=PERSON,
                             reason="Prueba de la T40", version=cls.v1.code)
                store.create(conn, design_params.road_profile_key(PROJECT_PROFILE, item), value, kind="ADOPTADO", source="Prueba de la T49 de la 017", source_kind="person", decided_by=PERSON,
                             reason="Prueba de la T49")  # el del proyecto: sin versión
        cls.clock.advance(minutes=1)

    STEP_M = qfx.COARSE_STEP_M

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_families((*design_params.ENTITY_FAMILIES, *design_params.ROAD_FAMILIES))
        cls.addClassCleanup(core_params.unregister_families, "des")
        store = core_params.ParameterStore(cls.project)
        cls.clock.advance(minutes=1)
        with cls.project.write_transaction() as conn:
            for code, (name, values) in WORLD.items():
                for param, value in {"name": name, **values}.items():
                    store.create(conn, key(code, param), value, kind="ADOPTADO", source="Prueba de la T22b de la 017", source_kind="person", decided_by=PERSON,
                                 reason="Prueba de la T22b", version=cls.v1.code)
        cls.clock.advance(minutes=1)

    def snapshot(self) -> int:
        """Lo que podría escribir una orden: el contador de cambios de la base (lo sube toda transacción)."""
        return change_counter(self.root)

    def check(self, param_key: str, new: object) -> None:
        """Lo que hace la orden «Cambiar parámetro…» antes de escribir: la comprobación de la entidad en V01."""
        entity_store.check_parameter_change(self.project, param_key, new, version=self.v1.uid)

    def refused(self, param_key: str, new: object, expected: str, *, chain: bool = False, **names: Any) -> Any:
        """Cambiar ``param_key`` a ``new`` se rechaza con ``expected`` y **no escribe nada** (0 transacciones); el rechazo nombra el campo (la clave; el de la cadena de entidades, con ``chain``, es
        ``start``) y lo de ``names`` (en sus valores y en su texto), y su texto no deja ningún marcador sin llenar en ninguno de los dos idiomas. Devuelve el error."""
        before = self.snapshot()
        with self.assertRaises(messages.DesignError) as caught:
            self.check(param_key, new)
        error = caught.exception
        self.assertEqual(error.code, expected)
        self.assertEqual(error.values["field"], "start" if chain else param_key)
        for name, wanted in names.items():
            self.assertEqual(error.values[name], wanted, name)
            self.assertIn(str(wanted), error.text, name)
        for text in (error.text, error.text_in("en")):
            self.assertNotIn("{", text)
        self.assertEqual(self.snapshot(), before, "el rechazo ha escrito algo")
        return error

    def accepted(self, param_key: str, new: object) -> None:
        """La comprobación deja pasar el cambio y tampoco escribe nada (lo escribe la orden después)."""
        before = self.snapshot()
        self.check(param_key, new)
        self.assertEqual(self.snapshot(), before)

    def project_check(self, param: str, value: object, *, profile: str = PROJECT_PROFILE) -> None:
        """La comprobación de «Cambiar parámetro…» de un valor del perfil ``profile`` **para el proyecto** (sin versión; spec 017, T49)."""
        road_profiles.check_profile_change(self.project, design_params.road_profile_key(profile, param), value, version=None)

    def refused_in_project(self, param: str, value: object, expected: str, field: str, shown: object) -> Any:
        """Cambiar el valor ``param`` del perfil del proyecto (``PROJECT_PROFILE``) a ``value`` **para el proyecto** se rechaza con ``expected``, nombrando el perfil, el campo ``field`` y lo que se ve de él
        (``shown``), con el mismo texto que «Perfil de pista…» en ese ámbito. Devuelve el error."""
        with self.assertRaises(messages.DesignError) as caught:
            self.project_check(param, value)
        error = caught.exception
        self.assertEqual((error.code, error.values["field"], error.values["value"], error.values["profile"]),
                         (expected, design_params.road_profile_key(PROJECT_PROFILE, field), shown, PROJECT_PROFILE))
        edited = {item.value: getattr(rd.PROFILE, "class_name" if item is design_params.RoadProfileParam.CLASS else item.value) for item in design_params.RoadProfileParam}
        with self.assertRaises(messages.DesignError) as dialog:
            design_params.check_road_profile(PROJECT_PROFILE, PROJECT_PROFILE, {**edited, param: value})
        self.assertEqual((error.code, error.text, error.text_in("en")), (dialog.exception.code, dialog.exception.text, dialog.exception.text_in("en")))
        return error


class RoadParameterTest(RoadParameterCase):
    """RF-015-01, RF-015-04, RF-015-08, RF-015-15, RF-017-01, RF-017-03: «Cambiar parámetro…» de una pista (todas las pruebas solo leen: una sola copia del proyecto)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.write_extra()

    # --- El nombre y la capa (RF-015-01, RF-015-08) ---

    def test_a_an_empty_name_is_refused_in_every_road_with_the_entity_the_layer_and_the_field(self) -> None:
        """RF-015-01, RF-015-08 (D-2): un nombre vacío, en blanco o ``None`` se rechaza con ``des.entity_param_missing`` en **cada pista** (de «trazar» y «sobre un eje»), con la pista, su capa y
        la clave del campo, y sin una transacción (sin esto, ``entities.registry()`` lanzaba ``des.entity_name_missing`` y rompía preparar, congelar y la barra N de la versión)."""
        for code in ("RDW-001", "RDW-002", "RDW-003"):
            name, values = WORLD[code]
            for blank in ("", "   ", None):
                with self.subTest(code=code, value=blank):
                    error = self.refused(key(code, "name"), blank, "des.entity_param_missing", entity=name)
                    self.assertEqual(error.values["layer"], values["layer"])

    def test_b_a_repeated_name_is_refused_also_across_types_and_one_that_is_free_is_not(self) -> None:
        """RF-015-01 (D-2): el nombre de otra entidad **de cualquier tipo** de la versión (otra pista o una plataforma) se rechaza con ``des.entity_name_repeated``, con quién lo tiene y la versión; y
        el que da el mismo nombre de dato (``des_psf_pista_a_p1``: «pista A P1!») también; el nombre que ya tiene la propia pista y uno libre, se admiten."""
        error = self.refused(key("RDW-002", "name"), "Pista a P1", "des.entity_name_repeated", other="Pista a P1", value="Pista a P1")
        self.assertEqual(error.values["version"], "V01")
        self.refused(key("RDW-003", "name"), "P1", "des.entity_name_repeated", other="P1")
        self.refused(key("PLT-001", "name"), "Ramal", "des.entity_name_repeated", other="Ramal")
        self.refused(key("RDW-002", "name"), "  pista A P1! ", "des.entity_name_repeated", other="Pista a P1")
        self.accepted(key("RDW-002", "name"), "Ramal")
        self.accepted(key("RDW-002", "name"), "Ramal norte")

    def test_c_the_layer_cannot_be_emptied(self) -> None:
        """RF-015-08 (D-2): la capa de una pista no puede quedar sin valor (``des.entity_param_missing``, con la pista y la clave); otra capa se admite."""
        for code in ("RDW-001", "RDW-003"):
            for blank in ("", None):
                with self.subTest(code=code, value=blank):
                    self.refused(key(code, "layer"), blank, "des.entity_param_missing", entity=WORLD[code][0])
        self.accepted(key("RDW-001", "layer"), "gis_fea_otras_pistas")


    # --- La partida y el apoyo (RF-015-04, RF-015-15, RF-017-03) ---

    def test_d_the_start_of_a_road_follows_the_rules_of_the_chain(self) -> None:
        """RF-015-04 (D-2): la partida de una pista no puede quedar vacía (``des.entity_param_missing``), de cada superficie parte una entidad (``des.entity_start_taken``: la de la plataforma
        de la que parte la pista, la de la pista de la que parte el ramal, la del ramal de la que parte el relleno) y la cadena no da la vuelta (``des.entity_chain_cycle``: la pista a P1 no parte de lo
        que deja el relleno, que parte del ramal, que parte de ella); una superficie libre, el terreno de otra pista y la que deja una pista que nadie sigue, se admiten."""
        self.refused(key("RDW-001", "start"), "", "des.entity_param_missing", entity="Pista a P1")
        self.refused(key("RDW-003", "start"), "entity:PLT-001", "des.entity_start_taken", entity="Pista sobre un eje", other="Pista a P1")
        self.refused(key("RDW-001", "start"), "entity:RDW-001", "des.entity_start_taken", entity="Pista a P1", other="Ramal")
        self.refused(key("RDW-003", "start"), "entity:RDW-002", "des.entity_start_taken", entity="Pista sobre un eje", other="Relleno sobre la calzada")
        self.refused(key("RDW-001", "start"), "entity:PLT-002", "des.entity_chain_cycle", chain=True)
        self.refused(key("RDW-001", "start"), "entity:RDW-002", "des.entity_start_taken", entity="Pista a P1", other="Relleno sobre la calzada")
        self.accepted(key("RDW-003", "start"), OTHER_GROUND + "_otra")
        self.accepted(key("RDW-001", "start"), "entity:RDW-003")
        self.accepted(key("RDW-002", "start"), "entity:RDW-001")

    def test_e_the_support_of_a_road_cannot_be_a_cycle(self) -> None:
        """RF-015-15, RF-017-03 (D-2): la superficie de apoyo no es la de la propia pista ni la de una que parte de la suya (``des.entity_supports_unknown``, con la pista y el valor): ni la del ramal
        para la pista de la que parte, ni la del relleno para el ramal; la de la entidad anterior de la cadena, el terreno y nada, se admiten."""
        for code, support in (("RDW-002", "entity:RDW-002"), ("RDW-002", "entity:PLT-002"), ("RDW-001", "entity:RDW-002"), ("RDW-001", "entity:PLT-002"),
                              ("RDW-003", "entity:RDW-003")):
            with self.subTest(code=code, support=support):
                self.refused(key(code, "support"), support, "des.entity_supports_unknown", entity=WORLD[code][0], value=support)
        self.accepted(key("RDW-002", "support"), "entity:RDW-001")
        self.accepted(key("RDW-001", "support"), "entity:PLT-001")
        self.accepted(key("RDW-001", "support"), GROUND)
        self.accepted(key("RDW-002", "support"), None)


    # --- Lo que la pista no tiene (RF-017-01, RF-015-12, D-15): sin ``protect`` ni resguardo, y su ``mode`` no es el de la plataforma ---

    def test_f_a_road_has_no_protect_and_no_guard(self) -> None:
        """RF-017-01, RF-015-12 (D-15): ``protect`` y ``guard_m`` no son valores de la pista (su familia no los tiene: ``parse_entity_key`` no reconoce la clave): cambiarlos no pasa por ninguna regla de
        lo que declara (hasta la T03 era un ``KeyError``) y lo dice el almacén de parámetros; no escribe nada."""
        self.assertFalse({"protect", "guard_m"} & set(entities.entity_type("road").params.names))
        for param, value in (("protect", True), ("protect", False), ("guard_m", 5.0), ("guard_m", None)):
            with self.subTest(param=param):
                self.assertIsNone(design_params.parse_entity_key(f"des.road.rdw_001.{param}"))
                self.accepted(f"des.road.rdw_001.{param}", value)

    def test_g_the_mode_of_a_road_is_not_the_mode_of_a_platform(self) -> None:
        """RF-017-02, RF-015-12 (D-15): cambiar el modo de la pista (los tres) se admite sin comprobar lo que declara; el de la **plataforma** sigue rechazando «en corte y relleno» si protege
        (``des.platform_protect_cut_fill``: sin cambio)."""
        for mode in ("trace", "on_axis", "axis_3d"):
            with self.subTest(mode=mode):
                self.accepted(key("RDW-001", "mode"), mode)
        self.refused(key("PLT-001", "mode"), "cut_fill", "des.platform_protect_cut_fill", entity="P1")
        self.accepted(key("PLT-001", "mode"), "cut")

    def test_h_the_values_that_are_not_of_these_rules_pass(self) -> None:
        """RF-015-01 (D-2): el perfil, las cotas, los parámetros de la ruta y el presupuesto de estados no entran en las reglas entre entidades (los comprueba su definición y, al calcular, la preparación),
        una pista que no está en la versión, un valor que no es del tipo del parámetro (lo dice su definición) y, sin versión o con una que no existe, nada: no se comprueban ni escriben."""
        self.accepted(key("RDW-001", "profile"), "otro_perfil")
        self.accepted(key("RDW-001", "start_level_m"), 110.5)
        self.accepted(key("RDW-001", "mesh_m"), 4.0)
        self.accepted(key("RDW-001", "search_budget"), 1_000_000)
        self.accepted(key("RDW-009", "name"), "Pista a P1")
        self.accepted(key("RDW-001", "name"), 5)
        entity_store.check_parameter_change(self.project, key("RDW-001", "name"), "", version=None)
        entity_store.check_parameter_change(self.project, key("RDW-001", "name"), "", version="V99")

    # --- El origen y el destino: la dependencia por el eje de otra pista o por una entidad no cierra un ciclo (spec 017, T40; A-2) ---

    def test_i_the_origin_and_the_destination_of_a_road_cannot_close_a_cycle(self) -> None:
        """RF-015-15, RF-017-03, RF-017-04 (T40; hallazgo A-2): el origen de una pista (un punto del eje de otra, ``RDW-004@10``) y su destino (una entidad, ``entity:RDW-004``) son **lo que la pista pisa**, y
        no pueden ser ella misma, ni lo que parte de su superficie, ni una pista que **ya se apoya en ella**, directa o por otras (aquí RDW-005 → RDW-004 → RDW-001): se rechaza con
        ``des.entity_supports_unknown`` con la pista, el campo, el valor, a quién se apoyaría y **el recorrido del ciclo** en el motivo, y sin una transacción. Hasta la T40 solo se vigilaba la superficie
        de apoyo y la sonda del verificador A cambiaba el origen de ``RDW-001`` a un punto de una pista que ya se apoyaba en ella y se aceptaba."""
        cases = (("RDW-001", "origin", "RDW-004@10", "RDW-004", ("RDW-004", "RDW-001")), ("RDW-001", "destination", "entity:RDW-004", "RDW-004", ("RDW-004", "RDW-001")),
                 ("RDW-001", "origin", "RDW-005@3", "RDW-005", ("RDW-005", "RDW-004", "RDW-001")), ("RDW-001", "origin", "RDW-001@10", "RDW-001", ()),
                 ("RDW-001", "origin", "RDW-002@5", "RDW-002", ()), ("RDW-001", "destination", "entity:PLT-002", "PLT-002", ()))
        for code, param, value, target, around in cases:
            with self.subTest(code=code, param=param, value=value):
                error = self.refused(key(code, param), value, "des.entity_supports_unknown", entity=WORLD[code][0], value=value, target=target)
                for member in around:
                    self.assertIn(member, str(error.values["reason"]))
        self.accepted(key("RDW-004", "origin"), "RDW-003@10")
        self.accepted(key("RDW-005", "destination"), "entity:RDW-001")
        self.accepted(key("RDW-001", "destination"), "entity:PLT-001")
        self.accepted(key("RDW-002", "origin"), "RDW-001@100")
        for point in ("Entrada", None):
            self.accepted(key("RDW-001", "origin"), point)
        self.accepted(key("RDW-001", "destination"), None)

    # --- Las dependencias declaradas (``supports``): tampoco cierran un ciclo (spec 017, T49; hallazgo T47-2) ---

    def test_i2_the_declared_supports_of_a_road_cannot_close_a_cycle(self) -> None:
        """RF-015-15, RF-015-17, RF-017-03, RF-017-04 (T49; hallazgo T47-2): las dependencias que la persona **declara a mano** en una pista (``des.road.{e}.supports``: códigos separados por comas) pasan por la
        misma regla del ciclo que su origen y su destino (T40): ninguna es ella misma ni una pista que **ya se apoya en ella** por su origen (RDW-004 sale de RDW-001@40: aquí solo por lo que pisa, no
        por su cadena); se rechaza con ``des.entity_supports_unknown`` con la pista, el campo, **el valor entero**, a quién se apoyaría y el recorrido en el motivo, y sin escribir nada (la sonda de la
        T47 declaraba ``RDW-001.supports = RDW-002`` y se aceptaba: «Recalcular lo obsoleto» lo paraba después, ``FAILED``). Una lista donde solo la segunda cierra el ciclo se rechaza por esa; lo que ya
        declara el ramal (la pista) y un código que la versión no tiene (lo dice el cálculo) se admiten. La matriz entera, en ``milestone_road_parameter_matrix``."""
        before = self.snapshot()
        for code, value, target, around in (("RDW-001", "RDW-004", "RDW-004", ("RDW-004", "RDW-001")), ("RDW-001", "PLT-001, RDW-002", "RDW-002", ("RDW-002", "RDW-001")), ("RDW-001", "RDW-001", "RDW-001", ())):
            with self.subTest(code=code, value=value):
                with self.assertRaises(messages.DesignError) as caught:
                    self.check(key(code, "supports"), value)
                error = caught.exception
                self.assertEqual((error.code, error.values["field"], error.values["value"], error.values["target"]), ("des.entity_supports_unknown", key(code, "supports"), value, target))
                self.assertIn(value, error.text)
                self.assertNotIn("{", error.text_in("en"))
                for member in around:
                    self.assertIn(member, str(error.values["reason"]))
        self.check(key("RDW-002", "supports"), "RDW-001")
        self.check(key("RDW-001", "supports"), "RDW-009")
        self.assertEqual(self.snapshot(), before, "el rechazo ha escrito algo")

    def refused_profile(self, param: str, value: object, expected: str, field: str, shown: object) -> Any:
        """Cambiar el valor ``param`` del perfil de la prueba a ``value`` se rechaza con ``expected``, nombrando el perfil, el campo ``field`` (otro valor que el cambiado, en una regla cruzada) y lo
        que se ve de él (``shown``), **con el mismo texto que «Perfil de pista…»** y sin una transacción."""
        before = self.snapshot()
        with self.assertRaises(messages.DesignError) as caught:
            road_profiles.check_profile_change(self.project, design_params.road_profile_key(PROFILE, param), value, version=self.v1.uid)
        error = caught.exception
        self.assertEqual((error.code, error.values["field"], error.values["value"], error.values["profile"]), (expected, design_params.road_profile_key(PROFILE, field), shown, PROFILE))
        edited = {item.value: getattr(rd.PROFILE, "class_name" if item is design_params.RoadProfileParam.CLASS else item.value) for item in design_params.RoadProfileParam}
        with self.assertRaises(messages.DesignError) as dialog:  # lo que dice «Perfil de pista…» (``edit_road_profiles``) de ese mismo perfil
            design_params.check_road_profile(PROFILE, PROFILE, {**edited, param: value})
        self.assertEqual((error.code, error.text, error.text_in("en")), (dialog.exception.code, dialog.exception.text, dialog.exception.text_in("en")))
        self.assertEqual(self.snapshot(), before, "el rechazo ha escrito algo")
        return error

    def accepted_profile(self, param: str, value: object, profile: str = PROFILE) -> None:
        before = self.snapshot()
        road_profiles.check_profile_change(self.project, design_params.road_profile_key(profile, param), value, version=self.v1.uid)
        self.assertEqual(self.snapshot(), before)

    def test_j_a_value_of_the_road_profile_follows_the_rules_of_the_profile(self) -> None:
        """RF-017-04, RF-017-07, RF-015-08 (T40; hallazgo A-1): «Cambiar parámetro…» de un valor de ``des.roadprofile.{p}.*`` rechaza lo que rechaza «Perfil de pista…» y **sin escribir nada**: el radio
        mínimo menor que la semianchura de la sección (3 m con 5,75 m; también el caballón de 20 m, que la sube a 15,25 m), el radio mínimo mayor que el radio (R = 5 m con Rmín = 12 m) y un ángulo
        de 90° (la definición lo admite y RF-017-04 lo excluye), con el perfil, el campo y el valor; los valores buenos (89,9°, Rmín = 6 m, R = Rmín…), la clase y un perfil incompleto, se admiten."""
        for param, value, expected, field, shown in (("min_radius_m", 3.0, "des.road_profile_radius_narrow", "min_radius_m", 3.0), ("curve_radius_m", 5.0, "des.road_profile_radius_order", "min_radius_m", 12.0),
                                                     ("berm_m", 20.0, "des.road_profile_radius_narrow", "min_radius_m", 12.0), ("cut_angle_deg", 90.0, "des.road_profile_value_range", "cut_angle_deg", 90.0),
                                                     ("metric", "bogus", "des.road_profile_value_range", "metric", "bogus")):
            with self.subTest(param=param, value=value):
                self.refused_profile(param, value, expected, field, shown)
        for param, value in (("cut_angle_deg", 89.9), ("min_radius_m", 6.0), ("curve_radius_m", 12.0), ("berm_m", 2.0), ("class", "Otra clase")):
            with self.subTest(param=param, value=value):
                self.accepted_profile(param, value)
        self.accepted_profile("min_radius_m", 3.0, profile="sin_otros_valores")  # el perfil sin sus valores no tiene con qué cruzarse: solo su rango
        self.accepted_profile("min_radius_m", None)  # sin valor: lo dice la definición

    def test_k_a_value_of_the_road_profile_changed_for_the_project_follows_the_same_rules_with_the_values_of_the_project(self) -> None:
        """RF-017-04, RF-017-07, RF-015-08 (T49; hallazgo T47-1): «Cambiar parámetro…» con el ámbito **proyecto** (el que propone el diálogo cuando la versión no tiene valor propio: un valor del proyecto
        llega a las versiones que no tienen el suyo) rechaza lo mismo que con el de la versión, con los valores **del proyecto** del perfil: el radio mínimo menor que la semianchura (3 m con 5,75 m),
        el radio de las curvas menor que el mínimo (5 m con 12 m), el caballón de 20 m que sube la semianchura a 15,25 m y el ángulo de 90°, con el perfil, el campo y el valor y el texto de «Perfil de
        pista…»; hasta la T49 salía sin hacer nada, se escribía y «Recalcular lo obsoleto» daba ``FAILED``. Un valor bueno se admite y el **rango se comprueba siempre**, también en un perfil sin los
        demás valores del proyecto (las cruzadas que necesitan otro valor se quedan para el cálculo, **sin leer otra versión**). Todo sin escribir nada; la matriz entera, en
        ``milestone_road_parameter_matrix``."""
        before = self.snapshot()
        for param, value, expected, field, shown in (("min_radius_m", 3.0, "des.road_profile_radius_narrow", "min_radius_m", 3.0), ("curve_radius_m", 5.0, "des.road_profile_radius_order", "min_radius_m", 12.0),
                                                     ("berm_m", 20.0, "des.road_profile_radius_narrow", "min_radius_m", 12.0), ("cut_angle_deg", 90.0, "des.road_profile_value_range", "cut_angle_deg", 90.0)):
            with self.subTest(param=param, value=value):
                self.refused_in_project(param, value, expected, field, shown)
        self.project_check("min_radius_m", 6.0)
        self.project_check("min_radius_m", 3.0, profile="sin_otros_valores")  # el proyecto no tiene sus demás valores: no hay con qué cruzarlo
        with self.assertRaises(messages.DesignError) as caught:  # el rango, siempre
            self.project_check("cut_angle_deg", 90.0, profile="sin_otros_valores")
        self.assertEqual(caught.exception.code, "des.road_profile_value_range")
        self.assertEqual(self.snapshot(), before, "el rechazo ha escrito algo")


class RoadNameRowTest(RoadParameterCase):
    """RF-015-01, RF-015-08, RF-017-01 (T29c): **renombrar una pista** con «Cambiar parámetro…» (``geoblender.core_set_parameter``). La orden pide la fila **del proyecto** del parámetro (``store.get(clave)``
    sin versión: «El parámetro … no está registrado en el proyecto») y la pista no la tenía: su operación **no lee su nombre** (renombrarla no la deja obsoleta), así que nadie la creaba; la plataforma
    sí la tiene porque la declaración de sus restricciones lee su nombre. **La pista crea la fila de su nombre** como ella (:func:`~design.road_store.ensure_name_row`: «sin confirmar», sin valor y con
    el decisor por defecto: el nombre es el de la versión). Aquí, sin operaciones: la fila y lo que la orden hace con ella; crear, recalcular, traer y la capa de ejes con el proyecto son de los hitos
    y de ``milestone_road_ops``. **En orden** (``test_a`` a ``test_c``)."""

    CODES = ("RDW-001", "RDW-002", "RDW-003")

    def project_row(self, code: str) -> Any:
        """La fila **del proyecto** del nombre de ``code`` (la que pide la orden), o ``None``."""
        return core_params.ParameterStore(self.project).get(key(code, "name"))

    def test_a_a_road_has_no_row_of_its_name_in_the_project_until_it_is_created(self) -> None:
        """RF-015-08, RF-017-01: el estado de partida de lo que arregla la tarea: las pistas de la versión tienen su nombre (el valor de V01) y **ninguna tiene la fila del proyecto**, que es la que pide
        «Cambiar parámetro…» para renombrar."""
        for code in self.CODES:
            with self.subTest(code=code):
                self.assertIsNone(self.project_row(code))
                self.assertEqual(core_params.ParameterStore(self.project).get(key(code, "name"), version=self.v1.uid).value, WORLD[code][0])

    def test_b_the_road_creates_the_row_of_its_name_unconfirmed_without_value_and_only_once(self) -> None:
        """RF-015-08, RF-017-01: ``ensure_name_row`` deja la fila **del proyecto** del nombre «sin confirmar», sin valor y con el decisor por defecto —lo que deja la declaración de la plataforma—, sin
        tocar la de la versión; llamarla otra vez no la cambia (la misma fila, la misma revisión): crear, recalcular y traer la llaman sin mirar si ya está."""
        store = core_params.ParameterStore(self.project)
        before = {code: store.get(key(code, "name"), version=self.v1.uid) for code in self.CODES}
        with self.project.write_transaction() as conn:
            made = {code: road_store.ensure_name_row(self.project, code, conn=conn) for code in self.CODES}
        for code, record in made.items():
            with self.subTest(code=code):
                self.assertEqual((record.key, record.scope, record.scope_uid), (key(code, "name"), core_params.PROJECT_SCOPE, ""))
                self.assertTrue(record.unconfirmed)
                self.assertIsNone(record.value)
                self.assertEqual(record.decided_by, core_params.DEFAULT_DECIDER)
                self.assertEqual(self.project_row(code).uid, record.uid)
                self.assertEqual(store.get(key(code, "name"), version=self.v1.uid), before[code], "la fila de la versión no cambia")
        with self.project.write_transaction() as conn:
            again = {code: road_store.ensure_name_row(self.project, code, conn=conn) for code in self.CODES}
        self.assertEqual({code: (record.uid, record.rev) for code, record in again.items()}, {code: (record.uid, record.rev) for code, record in made.items()})

    def test_c_with_the_row_the_command_finds_the_parameter_and_renaming_works_without_making_it_stale(self) -> None:
        """RF-015-08, RF-015-01, RF-015-16: con las dos filas, lo que hace la orden —busca la del proyecto y la de la versión, comprueba el nombre y cambia la de la versión— renombra la pista: el registro
        de las entidades dice el nombre nuevo; el nombre vacío o repetido se sigue rechazando **sin escribir nada** (y con la fila del proyecto, que no cambia lo que dicen los rechazos)."""
        store = core_params.ParameterStore(self.project)
        record = store.get(key("RDW-002", "name"))
        own = store.get(key("RDW-002", "name"), version=self.v1.uid)
        self.assertIsNotNone(record, "la orden la pide")
        self.assertIsNotNone(own)
        self.refused(key("RDW-002", "name"), "", "des.entity_param_missing", entity="Ramal")
        self.refused(key("RDW-002", "name"), "Pista a P1", "des.entity_name_repeated", other="Pista a P1")
        self.accepted(key("RDW-002", "name"), "Ramal norte")
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            changed = store.change(conn, key("RDW-002", "name"), value="Ramal norte", reason="Se renombra la pista", version=self.v1.uid)
        self.assertEqual((changed.value, changed.rev, str(changed.scope)), ("Ramal norte", own.rev + 1, core_params.VERSION_SCOPE))
        self.assertEqual(entities.registry(self.project, self.v1.uid).get("RDW-002").record.name, "Ramal norte")
        self.assertEqual(store.get(key("RDW-002", "name")).uid, record.uid, "la fila del proyecto sigue siendo la misma")


class SupportPathTest(unittest.TestCase):
    """RF-015-15, RF-017-03 (T40; A-2; **pura**, sin proyecto): el recorrido de lo que **depende de una entidad** —lo que parte de su superficie (la cadena) y las pistas que la pisan por su origen
    o su destino, y lo que depende de ellas— que ``entities.support_path`` da para decir si apoyarse en otra cerraría un ciclo."""

    RECORDS = tuple(entities.EntityRecord(code, name, kind, start) for code, name, kind, start in (
        ("PLT-001", "P1", "platform", "terreno"), ("RDW-001", "Pista a P1", "road", "entity:PLT-001"), ("RDW-002", "Ramal", "road", "entity:RDW-001"), ("PLT-002", "Relleno", "platform", "entity:RDW-002"),
        ("RDW-004", "Pista libre", "road", "libre_a"), ("RDW-005", "Pista libre 2", "road", "libre_b"), ("PLT-003", "Relleno de la libre", "platform", "entity:RDW-004")))
    READS = {"RDW-002": ("RDW-001",), "RDW-004": ("RDW-001",), "RDW-005": ("RDW-004",)}

    def path(self, target: str, *, code: str = "RDW-001", reads: dict[str, tuple[str, ...]] | None = None) -> tuple[str, ...] | None:
        return entities.support_path(self.RECORDS, self.READS if reads is None else reads, code, target)

    def test_a_the_path_goes_from_what_would_rest_to_the_entity_through_the_chain_and_the_roads(self) -> None:
        """RF-015-15, RF-017-03: la ruta de lo que dependería de ``RDW-001`` hasta ella: ella misma; lo que parte de su superficie (aguas abajo de la cadena); una pista que la pisa por su origen, y otra que
        pisa a esa; lo que parte de la superficie de la que la pisa; y una pista que pisa una entidad de la cadena de ``RDW-001`` (depende de ella por la cadena)."""
        self.assertEqual(self.path("RDW-001"), ("RDW-001",))
        self.assertEqual(self.path("PLT-002"), ("PLT-002", "RDW-002", "RDW-001"))
        self.assertEqual(self.path("RDW-004"), ("RDW-004", "RDW-001"))
        self.assertEqual(self.path("RDW-005"), ("RDW-005", "RDW-004", "RDW-001"))
        self.assertEqual(self.path("RDW-004", reads={"RDW-004": ("PLT-002",)}), ("RDW-004", "PLT-002", "RDW-002", "RDW-001"))
        self.assertEqual(self.path("PLT-003"), ("PLT-003", "RDW-004", "RDW-001"), "lo que parte de la superficie de la pista que la pisa depende también de ella")

    def test_b_what_does_not_depend_on_the_entity_is_not_a_cycle(self) -> None:
        """RF-015-15, RF-017-03: lo que la entidad pisa o de lo que parte (aguas arriba), y otra cadena que no la toca, no cierran ningún ciclo: ``None``; y desde ``RDW-004``, ``RDW-001`` no depende de ella."""
        for target in ("PLT-001", "RDW-009"):
            self.assertIsNone(self.path(target), target)
        self.assertIsNone(self.path("RDW-001", code="RDW-004"))
        self.assertIsNone(self.path("PLT-001", code="RDW-004", reads={}))
        self.assertEqual(self.path("RDW-005", code="RDW-004"), ("RDW-005", "RDW-004"))


if __name__ == "__main__":
    unittest.main()
