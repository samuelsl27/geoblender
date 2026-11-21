# SPDX-License-Identifier: GPL-3.0-or-later
"""La petición de una pista traída «sin calcular» (spec 017, T33c; HU-017-1 y HU-017-2; RF-015-18, RF-015-04, RF-017-01, RF-017-03; plan 017 §5.2.3 y §5.7 P-5; duda T22b (d)).

Una pista traída a otra versión (``entity_store.bring_entities``) o heredada de la versión de la que parte queda **sin calcular**: tiene sus parámetros (``des.road.{e}.*``) y ningún resultado.
``road_store.entity_road_request`` es lo que «Calcular…» (``geoblender.des_entity_calculate``) pide para calcularla **con lo que ya tiene la versión**, como ``entity_store.entity_request`` hace con la
plataforma: la ``RoadRequest`` que arma ``provenance.road_request(ajustes, parámetros)`` con los parámetros vigentes de la entidad y los ajustes que la operación que no tiene habría llevado (el nombre
de la pista y el campo de los nombres de la capa, que **no es un parámetro**: sin él). No escribe nada; rechaza una pista que ya está calculada o descartada, la que no es una pista y la que no tiene de
dónde salir (sin capa, modo, perfil o partida: ``des.entity_calculate_missing`` con el campo) y su texto, que antes decía solo «cree la plataforma», **dice las dos cosas que valen**.

Sobre la cantera de la 014 (rejilla gruesa) con las cinco entidades de ``test_road_bring.WORLD`` escritas como parámetros de V01 (sin operación: lo que se trae son definiciones). **En orden**
(``test_a`` a ``test_c``): cada una parte de lo que dejó la anterior en V02.
"""

from __future__ import annotations

import unittest
from typing import Any

from tests.support import entity_fixtures as efx
from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender
from tests.support.versions_fixtures import change_counter
from tests.unit.design.test_road_bring import GROUND, PERSON, WORLD, key

core_params = import_geoblender("core.params")
design_params = import_geoblender("design.params")
entity_store = import_geoblender("design.entity_store")
messages = import_geoblender("design.messages")
road_model = import_geoblender("design.road_model")
road_store = import_geoblender("design.road_store")


class BroughtRoadRequestTest(efx.EntityProjectCase):
    """RF-015-18, RF-017-01, RF-017-03: la petición de las pistas traídas a V02 y lo que se rechaza. **En orden** (``test_a`` a ``test_c``)."""

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
                    store.create(conn, key(code, param), value, kind="ADOPTADO", source="Prueba de la T33c de la 017", source_kind="person", decided_by=PERSON,
                                 reason="Prueba de la T33c", version=cls.v1.code)
        cls.clock.advance(minutes=1)

    def request(self, version: Any, code: str) -> Any:
        return road_store.entity_road_request(self.project, version.uid, code)

    def test_a_the_request_of_a_brought_road_is_made_of_what_the_version_stores(self) -> None:
        """RF-015-18, RF-017-01, RF-017-03, RF-015-01: traída V01 a V02, la petición de cada pista sale **de sus parámetros de V02** (la capa, el modo, el perfil, la partida, el apoyo, el origen y
        el destino, el destino por cota con su zona) y de su nombre; **sin el campo de los nombres de la capa** (no es un parámetro) y sin ninguna cifra que no tenga la entidad; la pista a P1 parte de
        la plataforma y acaba en ella, **el ramal sale del eje de la anterior a 100,5 m** (con su coma) y se apoya en ella, la rampa acaba a una cota en su zona; **no escribe nada** (0 transacciones)
        y la pista de V01, la misma petición con los mismos parámetros."""
        entity_store.bring_entities(self.project, "V01", "V02")
        before = change_counter(self.root)
        first, branch, ramp = (self.request(self.v2, code) for code in ("RDW-001", "RDW-002", "RDW-003"))
        for found in (first, branch, ramp):
            self.assertIsInstance(found, road_model.RoadRequest)
            self.assertIsNone(found.fields.name_field, "el campo de los nombres de la capa no es un parámetro de la entidad")
            self.assertEqual(found.mode, road_model.RoadMode.TRACE)
            self.assertEqual(found.profile, "pista_principal")
        self.assertEqual((first.name, first.fields.layer, first.start, first.origin, first.destination, first.support), ("Pista a P1", "gis_fea_pistas_a_p1", "entity:PLT-001", "Entrada",
                                                                                                                         "entity:PLT-001", None))
        self.assertEqual((branch.name, branch.fields.layer, branch.start, branch.origin, branch.destination, branch.support),
                         ("Ramal", "gis_fea_pistas_puntos", "entity:RDW-001", "RDW-001@100,5", "Destino del ramal", "entity:RDW-001"))
        self.assertEqual((ramp.name, ramp.start, ramp.origin, ramp.destination, ramp.dest_zone, ramp.dest_level_m, ramp.dest_tol_m),
                         ("Rampa a una cota", GROUND, "Entrada", None, "Cota 120", 120.0, 0.5))
        self.assertEqual(change_counter(self.root), before, "pedir la petición no escribe: 0 transacciones")
        for code in ("RDW-001", "RDW-002", "RDW-003"):
            with self.subTest(codigo=code):
                self.assertEqual(self.request(self.v2, code), self.request(self.v1, code), "los mismos parámetros, la misma petición que en la versión de origen")

    def test_b_a_platform_a_missing_code_and_a_written_state_are_refused_before_anything(self) -> None:
        """RF-015-18, RF-015-01: el código de una plataforma no es el de una pista, uno que no está en la versión tampoco (``ValueError``, un error del programa: la orden mira antes el tipo y
        la lista) y la versión que no existe o no se edita se rechaza como en toda orden de la 009 (``VersionError``); ninguno escribe nada."""
        before = change_counter(self.root)
        for code in ("PLT-001", "RDW-099"):
            with self.subTest(codigo=code), self.assertRaises(ValueError):
                self.request(self.v2, code)
        with self.assertRaises(Exception) as caught:
            road_store.entity_road_request(self.project, "V99", "RDW-001")
        self.assertEqual(type(caught.exception).__name__, "VersionError")
        self.assertEqual(change_counter(self.root), before)

    def test_c_a_road_without_its_start_is_refused_naming_the_field_and_the_text_says_both_things(self) -> None:
        """RF-015-18, RF-015-04, RF-017-03: traer otra vez (los códigos ocupados: la rampa recibe ``RDW-006`` y **su partida, el terreno, ya es la de ``RDW-003``**: queda sin valor, RF-015-04) deja una
        pista que **no se puede calcular hasta que se elija otra partida**: ``des.entity_calculate_missing`` con **la pista, su código, la versión y el campo** (``des.road.rdw_006.start``), sin
        escribir nada; y el texto del rechazo, en los dos idiomas y sin marcadores, dice **las dos cosas que valen** —«Plataforma…» para una plataforma y «Pista…» para una pista— y no solo
        «cree la plataforma»."""
        entity_store.bring_entities(self.project, "V01", "V02")
        before = change_counter(self.root)
        with self.assertRaises(messages.DesignError) as caught:
            self.request(self.v2, "RDW-006")
        error = caught.exception
        self.assertEqual(error.code, "des.entity_calculate_missing")
        self.assertEqual((error.values["entity"], error.values["code"], error.values["version"], error.values["field"]),
                         ("Rampa a una cota (V01)", "RDW-006", "V02", key("RDW-006", "start")))
        self.assertEqual(change_counter(self.root), before)
        for language, platform, road in (("es", "«Plataforma…»", "«Pista…»"), ("en", "«Platform…»", "«Road…»")):
            with self.subTest(idioma=language):
                text = error.text_in(language)
                self.assertNotIn("{", text)
                for part in ("Rampa a una cota (V01)", "RDW-006", "V02", key("RDW-006", "start"), platform, road):
                    self.assertIn(part, text)
        self.assertEqual(messages.lookup("des.entity_calculate_missing").severity, "error")


if __name__ == "__main__":
    unittest.main()
