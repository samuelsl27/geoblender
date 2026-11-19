# SPDX-License-Identifier: GPL-3.0-or-later
"""Validar al editar un parámetro de **cada tipo de entidad**, con su nombre en el rechazo (spec 016, T47; hallazgo D-2 de la
verificación única; RF-015-01, RF-015-04, RF-015-08, RF-015-12, RF-015-15; RF-016-24).

«Proyecto ▸ Cambiar parámetro…» (``geoblender.core_set_parameter``) pasaba por las reglas **entre** entidades de crear
(``design.entity_store.check_parameter_change``) solo si la clave era ``des.platform.{e}.*``: un contrafuerte que protege
aceptaba ``name = ""`` y ``guard_m = ""`` (la plataforma los rechaza desde la T39 de la 015), un nombre repetido, una partida
que ya es la de otra entidad o una cadena que se cierra sobre sí misma. La comprobación es ahora **de cada tipo registrado**: lo
común (el nombre único y no vacío, la capa y la geometría, la partida, el apoyo y proteger con su resguardo) y lo propio del tipo
(la superficie conocida del cuerpo apoyado), con **lo mismo que dice crear** y sin escribir nada.

Sobre la cantera de la 014 (rejilla gruesa) con las seis entidades de V01 escritas como **parámetros de versión** (sin
operación: el registro las lista «sin calcular», que es todo lo que lee la comprobación): ``STK-001`` (la detección de acopios,
sin cadena), ``RMV-001`` (una retirada del terreno), ``BTR-001`` (un contrafuerte que parte de la retirada y protege con 5 m),
``BDY-001`` (un cuerpo «sobre una base» que parte del contrafuerte), ``BDY-002`` (un cuerpo «bajo un techo», que no deja
superficie) y ``PLT-001`` (una plataforma de la 015 que parte de otra superficie del terreno y protege con 4 m).
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

GROUND = "gis_dtm_ladera"
OTHER_GROUND = "gis_dtm_levantamiento"
PERSON = "Samuel (IMGA)"

# Código → (nombre, valores que se escriben en V01). La cadena: terreno → RMV-001 → BTR-001 → BDY-001; BDY-002 «bajo un techo» no
# deja superficie y PLT-001 parte de otra superficie del terreno.
WORLD: dict[str, tuple[str, dict[str, Any]]] = {
    "STK-001": ("Detección 1", {"layer": "gis_fea_marcas", "surface": GROUND, "candidates": False}),
    "RMV-001": ("Retirada 1", {"stockpile": "STK-001#m01", "start": GROUND}),
    "BTR-001": ("Contrafuerte 1", {"layer": "gis_fea_zonas", "feature": "Z1", "start": "entity:RMV-001", "profile": "EXPL",
                                   "crown_m": 115.0, "protect": True, "guard_m": 5.0}),
    "BDY-001": ("Cuerpo 1", {"layer": "gis_fea_cuerpos", "feature": "C1", "data_layer": "gis_fea_espesores",
                             "data_field": "espesor", "data_from": "field", "surface": GROUND, "sense": "on_base",
                             "start": "entity:BTR-001"}),
    "BDY-002": ("Cuerpo 2", {"layer": "gis_fea_cuerpos", "feature": "C2", "data_layer": "gis_fea_espesores",
                             "data_field": "espesor", "data_from": "field", "surface": GROUND, "sense": "under_roof"}),
    "PLT-001": ("P1", {"layer": "gis_fea_plataformas_ejes", "feature": "Eje 1", "start": OTHER_GROUND, "mode": "cut",
                       "protect": True, "guard_m": 4.0}),
}
PROGRAM_KINDS = {"platform", "stockpile", "removal", "buttress", "body"}


def key(code: str, param: str) -> str:
    return design_params.entity_key(code, param)


class SupportedParameterCase(efx.EntityProjectCase):
    """V01 con las seis entidades de ``WORLD`` y las ayudas de las pruebas."""

    STEP_M = qfx.COARSE_STEP_M

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_families((*design_params.ENTITY_FAMILIES, *design_params.SUPPORTED_FAMILIES))
        cls.addClassCleanup(core_params.unregister_families, "des")
        store = core_params.ParameterStore(cls.project)
        cls.clock.advance(minutes=1)
        with cls.project.write_transaction() as conn:
            for code, (name, values) in WORLD.items():
                for param, value in {"name": name, **values}.items():
                    store.create(conn, key(code, param), value, kind="ADOPTADO", source="Prueba de la T47 de la 016",
                                 source_kind="person", decided_by=PERSON, reason="Prueba de la T47", version=cls.v1.code)
        cls.clock.advance(minutes=1)

    def snapshot(self) -> int:
        """Lo que podría escribir una orden: el contador de cambios de la base (lo sube toda transacción)."""
        return change_counter(self.root)

    def check(self, param_key: str, new: object) -> None:
        """Lo que hace la orden «Cambiar parámetro…» antes de escribir: la comprobación de la entidad en V01."""
        entity_store.check_parameter_change(self.project, param_key, new, version=self.v1.uid)

    def refused(self, param_key: str, new: object, expected: str, *, chain: bool = False, field: str | None = None,
                **names: Any) -> Any:
        """Cambiar ``param_key`` a ``new`` se rechaza con ``expected`` y **no escribe nada** (0 transacciones); el rechazo nombra el
        campo (la clave; el de la cadena de entidades, con ``chain``, es ``start``; ``field``, otro: proteger sin resguardo nombra el
        resguardo) y lo de ``names`` (en sus valores y en su texto). Devuelve el error."""
        before = self.snapshot()
        with self.assertRaises(messages.DesignError) as caught:
            self.check(param_key, new)
        error = caught.exception
        self.assertEqual(error.code, expected)
        self.assertEqual(error.values["field"], field or ("start" if chain else param_key))
        for name, wanted in names.items():
            self.assertEqual(error.values[name], wanted, name)
            self.assertIn(str(wanted), error.text, name)
        self.assertEqual(self.snapshot(), before, "el rechazo ha escrito algo")
        return error

    def accepted(self, param_key: str, new: object) -> None:
        """La comprobación deja pasar el cambio y tampoco escribe nada (lo escribe la orden después)."""
        before = self.snapshot()
        self.check(param_key, new)
        self.assertEqual(self.snapshot(), before)


class NameAndLayerTest(SupportedParameterCase):
    """RF-015-01, RF-015-08 con los tipos de la 016: el nombre y la capa."""

    def test_a_an_empty_name_is_refused_in_every_type_with_the_entity_and_the_field(self) -> None:
        """RF-015-01, RF-015-08 (D-2): un nombre vacío o en blanco se rechaza con ``des.entity_param_missing`` en **cada tipo**
        (la detección, la retirada, el contrafuerte, el cuerpo y la plataforma), con la entidad y la clave del campo, y sin una
        transacción (hasta la T47 los de la 016 lo aceptaban y lo que sigue fallaba con «La entidad no tiene nombre»)."""
        for code, (name, _values) in WORLD.items():
            for blank in ("", "   ", None):
                with self.subTest(code=code, value=blank):
                    self.refused(key(code, "name"), blank, "des.entity_param_missing", entity=name)

    def test_b_a_repeated_name_is_refused_also_across_types_and_one_that_is_free_is_not(self) -> None:
        """RF-015-01 (D-2): el nombre de otra entidad **de cualquier tipo** de la versión se rechaza con
        ``des.entity_name_repeated`` y con quién lo tiene; el mismo nombre que ya tiene la propia entidad y uno libre, se
        admiten."""
        self.refused(key("BTR-001", "name"), "Retirada 1", "des.entity_name_repeated", other="Retirada 1", value="Retirada 1")
        self.refused(key("STK-001", "name"), "Cuerpo 2", "des.entity_name_repeated", other="Cuerpo 2")
        self.refused(key("BDY-001", "name"), "P1", "des.entity_name_repeated", other="P1")
        self.refused(key("PLT-001", "name"), "Contrafuerte 1", "des.entity_name_repeated", other="Contrafuerte 1")
        self.refused(key("RMV-001", "name"), "  Detección 1 ", "des.entity_name_repeated", other="Detección 1")
        self.accepted(key("BTR-001", "name"), "Contrafuerte 1")
        self.accepted(key("BTR-001", "name"), "Contrafuerte nuevo")
        self.accepted(key("STK-001", "name"), "Acopios")

    def test_c_the_layer_and_the_feature_cannot_be_emptied_in_the_types_that_have_them(self) -> None:
        """RF-015-08 (D-2): la capa de la detección, del contrafuerte y del cuerpo y la geometría de estos dos no pueden quedar sin
        valor (``des.entity_param_missing``); la retirada no tiene capa (su clave no es de su familia: no se comprueba)."""
        for code in ("STK-001", "BTR-001", "BDY-001"):
            self.refused(key(code, "layer"), "", "des.entity_param_missing", entity=WORLD[code][0])
        for code in ("BTR-001", "BDY-001"):
            self.refused(key(code, "feature"), None, "des.entity_param_missing", entity=WORLD[code][0])
        self.accepted(key("BTR-001", "layer"), "gis_fea_otras_zonas")
        self.accepted("des.removal.rmv_001.layer", "")  # no es un valor de la retirada: lo dice el almacén de parámetros


class ChainTest(SupportedParameterCase):
    """RF-015-04, RF-015-15 con los tipos de la 016: la partida y el apoyo."""

    def test_a_the_start_of_a_removal_a_buttress_and_a_body_follows_the_rules_of_the_chain(self) -> None:
        """RF-015-04 (D-2): la partida no puede quedar vacía (el cuerpo «bajo un techo» no tiene), de cada superficie parte una
        entidad (``des.entity_start_taken``), la cadena no da la vuelta (``des.entity_chain_cycle``) y nadie parte de la
        superficie de un cuerpo «bajo un techo» (``des.chainless_start``); lo válido, se admite."""
        self.refused(key("RMV-001", "start"), "", "des.entity_param_missing", entity="Retirada 1")
        self.refused(key("BTR-001", "start"), GROUND, "des.entity_start_taken", entity="Contrafuerte 1", other="Retirada 1")
        self.refused(key("BDY-001", "start"), "entity:RMV-001", "des.entity_start_taken", entity="Cuerpo 1", other="Contrafuerte 1")
        self.refused(key("RMV-001", "start"), "entity:BDY-001", "des.entity_chain_cycle", chain=True)
        self.refused(key("BTR-001", "start"), "entity:BDY-002", "des.chainless_start", entity="Contrafuerte 1", other="Cuerpo 2")
        self.accepted(key("BDY-002", "start"), None)  # «bajo un techo»: sin partida
        self.accepted(key("RMV-001", "start"), OTHER_GROUND + "_otra")
        self.accepted(key("BTR-001", "start"), "entity:RMV-001")

    def test_b_the_support_of_every_type_cannot_be_a_cycle(self) -> None:
        """RF-015-15 (D-2): la superficie de apoyo no es la de la propia entidad ni la de una que parte de la suya
        (``des.entity_supports_unknown``, con la entidad y el valor), en la retirada, el contrafuerte y la detección; el terreno y
        lo anterior en la cadena se admiten; y el contrafuerte tampoco se apoya en lo que un cuerpo «bajo un techo» no deja."""
        for code, support in (("RMV-001", "entity:RMV-001"), ("RMV-001", "entity:BTR-001"), ("BTR-001", "entity:BDY-001"),
                              ("STK-001", "entity:STK-001")):
            with self.subTest(code=code, support=support):
                self.refused(key(code, "support"), support, "des.entity_supports_unknown", entity=WORLD[code][0], value=support)
        self.refused(key("BTR-001", "support"), "entity:BDY-002", "des.chainless_start", entity="Contrafuerte 1")
        self.accepted(key("BTR-001", "support"), "entity:RMV-001")
        self.accepted(key("RMV-001", "support"), GROUND)
        self.accepted(key("BDY-001", "support"), None)

    def test_c_the_known_surface_of_a_body_is_a_reference_too(self) -> None:
        """RF-015-15, RF-015-04 (D-2): la superficie conocida de un cuerpo (``des.body.{e}.surface``) no es la de él mismo ni la de
        una que parte de la suya (``des.entity_supports_unknown``) ni la de un cuerpo «bajo un techo»
        (``des.chainless_start``); el terreno, una superficie de diseño o la de una entidad anterior, sí; y la superficie de una
        detección (un dato, no una referencia de la cadena) no se comprueba."""
        self.refused(key("BDY-001", "surface"), "entity:BDY-001", "des.entity_supports_unknown", entity="Cuerpo 1")
        self.refused(key("BDY-002", "surface"), "entity:BDY-002", "des.chainless_start", entity="Cuerpo 2")
        self.refused(key("BDY-001", "surface"), "entity:BDY-002", "des.chainless_start", entity="Cuerpo 1")
        self.accepted(key("BDY-001", "surface"), "entity:RMV-001")
        self.accepted(key("BDY-002", "surface"), OTHER_GROUND)
        self.accepted(key("STK-001", "surface"), "entity:BTR-001")


class ProtectionTest(SupportedParameterCase):
    """RF-015-10, RF-015-12 con el contrafuerte (que protege por defecto) y la plataforma de la 015."""

    def test_a_a_buttress_that_protects_cannot_lose_its_guard_and_cannot_protect_without_one(self) -> None:
        """RF-015-12, D-19 de la 015 (D-2): el contrafuerte protege (``protect`` verdadero): dejar su resguardo sin valor se
        rechaza con ``des.entity_param_missing``, la entidad, el campo y la capa (lo mismo que dice declararlo); cambiarlo a otro y
        dejar de proteger se admiten, y sin proteger ya no hace falta resguardo."""
        error = self.refused(key("BTR-001", "guard_m"), None, "des.entity_param_missing", entity="Contrafuerte 1")
        self.assertEqual(error.values["layer"], "gis_fea_zonas")
        self.accepted(key("BTR-001", "guard_m"), 12.0)
        self.accepted(key("BTR-001", "guard_m"), 0.0)
        self.accepted(key("BTR-001", "protect"), False)

    def test_b_protecting_needs_the_guard_in_the_version_in_every_type(self) -> None:
        """RF-015-12 (D-2): con lo que quedaría la entidad: ``protect`` verdadero sin resguardo en la versión se rechaza en
        **cada tipo** (la retirada y el cuerpo, que no lo tienen; lo mismo que comprueba al declarar), y con él, no."""
        self.refused(key("RMV-001", "protect"), True, "des.entity_param_missing", entity="Retirada 1",
                     field=key("RMV-001", "guard_m"))
        self.refused(key("BDY-001", "protect"), True, "des.entity_param_missing", entity="Cuerpo 1",
                     field=key("BDY-001", "guard_m"))
        self.accepted(key("RMV-001", "protect"), False)

    def test_c_the_cut_and_fill_mode_still_cannot_protect_in_the_platform(self) -> None:
        """RF-015-12 (la plataforma de la 015, sin cambio): el modo «en corte y relleno» de la plataforma que protege se rechaza
        (``des.platform_protect_cut_fill``); el contrafuerte no tiene modo (su clave no es de su familia)."""
        self.refused(key("PLT-001", "mode"), "cut_fill", "des.platform_protect_cut_fill", entity="P1")
        self.accepted(key("PLT-001", "mode"), "cut")
        self.accepted("des.buttress.btr_001.mode", "cut_fill")  # no es un valor del contrafuerte: lo dice el almacén de parámetros


class OtherValuesTest(SupportedParameterCase):
    """Lo que no es de estas reglas sigue pasando."""

    def test_a_other_values_other_keys_and_unknown_entities_pass(self) -> None:
        """RF-015-01: los valores que no entran en las reglas entre entidades (el alcance, la cota de coronación, el margen de
        la detección, el espesor máximo de un cuerpo), una entidad que no está en la versión, una clave que no es de una entidad y
        un valor que no es del tipo (lo dice su definición) no los comprueba; sin versión, o con una que no existe, nada."""
        self.accepted(key("BTR-001", "reach_m"), 30.0)
        self.accepted(key("BTR-001", "crown_m"), 125.0)
        self.accepted(key("STK-001", "margin_m"), 20.0)
        self.accepted(key("BDY-001", "max_distance_m"), 50.0)
        self.accepted(key("BTR-009", "name"), "Contrafuerte 1")
        self.accepted("des.bench.expl.height_m", 5.0)
        self.accepted(key("BDY-001", "name"), 5)
        entity_store.check_parameter_change(self.project, key("BTR-001", "name"), "", version=None)
        entity_store.check_parameter_change(self.project, key("BTR-001", "name"), "", version="V99")

    def test_b_every_registered_type_has_the_rule_of_the_name(self) -> None:
        """RF-015-01, RF-016-24 (D-2): los cinco tipos del programa están registrados y todos rechazan un nombre vacío: añadir un
        tipo nuevo no deja el cambio de su nombre sin comprobar (la comprobación sale del registro de ``design.entities``, no de
        una lista aparte)."""
        registered = entities.registered_types()
        self.assertEqual({item.kind for item in registered}, PROGRAM_KINDS)
        for spec in registered:
            with self.subTest(kind=spec.kind):
                code = f"{spec.prefix}-001"
                self.assertIn(code, WORLD)
                self.refused(key(code, "name"), "", "des.entity_param_missing")


if __name__ == "__main__":
    unittest.main()
