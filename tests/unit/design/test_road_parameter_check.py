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
«sobre un eje» (``RDW-003``: parte del terreno) y la «Relleno sobre la calzada» (``PLT-002``: parte de la del ramal). Con la pista calculada de verdad, lo que sigue al cambio está en ``milestone_road_bring.py``.
"""

from __future__ import annotations

import unittest
from typing import Any

from tests.support import entity_fixtures as efx
from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender
from tests.support.versions_fixtures import change_counter

core_params = import_geoblender("core.params")
design_params = import_geoblender("design.params")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
messages = import_geoblender("design.messages")
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


def key(code: str, param: str) -> str:
    return design_params.entity_key(code, param)


class RoadParameterCase(efx.EntityProjectCase):
    """V01 con las cinco entidades de ``WORLD`` y las ayudas de las pruebas."""

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


class RoadParameterTest(RoadParameterCase):
    """RF-015-01, RF-015-04, RF-015-08, RF-015-15, RF-017-01, RF-017-03: «Cambiar parámetro…» de una pista (todas las pruebas solo leen: una sola copia del proyecto)."""

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


class RoadNameRowTest(RoadParameterCase):
    """RF-015-01, RF-015-08, RF-017-01 (T29c): **renombrar una pista** con «Cambiar parámetro…» (``geoblender.core_set_parameter``). La orden pide la fila **del proyecto** del parámetro (``store.get(clave)``
    sin versión: «El parámetro … no está registrado en el proyecto») y la pista no la tenía: su operación **no lee su nombre** (renombrarla no la deja obsoleta), así que nadie la creaba; la plataforma
    sí la tiene porque la declaración de sus restricciones lee su nombre. **La pista crea la fila de su nombre** como ella (:func:`~design.road_store.ensure_name_row`: «sin confirmar», sin valor y con
    el decisor por defecto: el nombre es el de la versión). Aquí, sin operaciones: la fila y lo que la orden hace con ella; crear, recalcular, traer y la capa de ejes con el proyecto son de los hitos
    y de ``test_road_ops``. **En orden** (``test_a`` a ``test_c``)."""

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


if __name__ == "__main__":
    unittest.main()
