# SPDX-License-Identifier: GPL-3.0-or-later
"""«Cambiar parámetro…» y «Recalcular lo obsoleto» con los tipos de entidad de la 016, con la orden real y un proyecto de verdad
(spec 016, T47; hallazgos D-1 y D-2 de la verificación única; RF-015-01, RF-015-04, RF-015-08, RF-015-10, RF-015-12, RF-015-27,
RF-015-29, RF-016-24; P-13: pesa más de 1 s, paso «hito»).

Tres mundos: dos versiones **sin ninguna plataforma** (lo que decidía mal el gancho de la capa, ``_layers_after_recompute``): V01 con un
contrafuerte que protege (y otro, para el nombre repetido y la cadena) y V01 con un cuerpo apoyado; y V01 con la retirada de un acopio
desde la superficie de una plataforma (el «después» de D-2 entre dos tipos).

- **D-2**: ``geoblender.core_set_parameter`` de una entidad de la 016 pasa por las reglas de crearla antes de escribir (un nombre
  vacío o repetido, un resguardo sin valor en el que protege, la partida de otra, un ciclo, la capa vacía) con un mensaje que la nombra,
  en el idioma de Geoblender y **sin una transacción**; y, con el cambio escrito, lanza lo que sigue (la declaración, las máscaras y la
  capa): el **resguardo declarado** pasa de 5 a 12 m **al instante**, sin una pasada de «Recalcular lo obsoleto» (hasta la T47 seguía
  en 5 m).
- **D-1**: tras «Recalcular lo obsoleto» la capa de entidades dice **lo mismo que el registro** también sin plataformas (el contrafuerte
  y el cuerpo estaban «al día» en el registro y la capa decía «obsoleta»).

Se ejecuta con ``tools/run_blender_tests.py`` (paso «hito» de ``tools/check.py --completo``).
"""

import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

import bpy

from tests.blender import milestone_body_ops as body_ops
from tests.blender import milestone_buttress_ops as buttress_ops
from tests.blender import milestone_removal_ops as removal_ops
from tests.blender import test_platform_ops as platform_ops
from tests.support.versions_fixtures import change_counter

TIMER = SimpleNamespace(type="TIMER", value="NOTHING")
SOURCE = "Criterio de la prueba de la T47"
SECOND = "Contrafuerte segundo"


class SupportedAfterHelpers:
    """Lo común de los dos mundos: cambiar un parámetro con la orden real, lo que dice el registro y la capa, y recalcular."""

    def written(self) -> tuple[Any, ...]:
        """Todo lo que podría escribir una orden: el contador de cambios de la base y lo registrado."""
        return (change_counter(self.project.root), self.state())

    def change(self, key: str, value: str) -> set[str]:
        """«Cambiar parámetro…» (``core_set_parameter``, la orden real) de la versión activa."""
        return bpy.ops.geoblender.core_set_parameter(
            "EXEC_DEFAULT", key=key, value=value, scope="VERSION", source=SOURCE, decided_by=platform_ops.PERSON,
            reason=platform_ops.REASON)

    def refused_change(self, key: str, value: str, text: str) -> str:
        """El cambio se rechaza con ``text`` en el mensaje y **sin escribir nada** (ni una transacción)."""
        before = self.written()
        with self.assertRaises(RuntimeError) as caught:
            self.change(key, value)
        message = str(caught.exception)
        self.assertIn(text, message)
        self.assertNotIn("Traceback", message)
        self.assertEqual(self.written(), before, "el rechazo ha escrito algo")
        return message

    def registry_states(self) -> dict[str, str]:
        return {entry.record.code: str(entry.record.state) for entry in self.entities.registry(self.project, self.v01.uid)}

    def layer_states(self) -> dict[str, str]:
        """El estado que dice la capa de entidades de V01 (``des_enl_v01``) de cada entidad."""
        return dict(self.rows("SELECT code, state FROM des_enl_v01"))

    def declared_guards(self) -> dict[str, float]:
        """El resguardo de cada restricción declarada por una entidad de V01, por el código de la entidad."""
        return {item.entity_code: item.buffer_out_m for item in self.declared()}

    def platforms(self) -> int:
        """Cuántas operaciones ``des.platform`` vivas tiene el proyecto: ninguna en estos mundos."""
        ((count,),) = self.rows("SELECT count(*) FROM gb_operation WHERE op_type = 'des.platform' AND status = 'done' "
                                "AND superseded_by IS NULL")
        return int(count)

    def tick(self) -> None:
        gis_ops, res_ops = platform_ops._module("bl.ops.gis"), platform_ops._module("bl.ops.res")
        self.des_ops.des_tick()
        gis_ops.masks_tick()
        res_ops.res_tick()

    def recompute(self) -> Any:
        """«Recalcular lo obsoleto» (``core_recompute_stale``) hasta el final, como lo avanza el modal."""
        with mock.patch.object(self.des_ops, "_ask_confirmation"), \
                mock.patch.object(platform_ops._module("bl.ops.incorporation"), "status_text"):
            self.assertEqual(bpy.ops.geoblender.core_recompute_stale("EXEC_DEFAULT"), {"RUNNING_MODAL"})
            found = [op for op in bpy.context.window.modal_operators
                     if isinstance(op, self.session.GEOBLENDER_OT_core_recompute_stale) and getattr(op, "_steps", None) is not None]
            op = found[0]
            for _ in range(400):
                state = op.modal(bpy.context, TIMER)
                self.tick()
                if state != {"RUNNING_MODAL"}:
                    return op
        self.fail("«Recalcular lo obsoleto» no termina")


class ButtressAfterTest(SupportedAfterHelpers, buttress_ops.CreateButtressTest):
    """V01 con dos contrafuertes que protegen, **por el orden de las pruebas**: (a) el primero, (b) lo que se rechaza, (c) el segundo
    y la cadena, (d) el resguardo declarado al instante y (e) la capa tras «Recalcular lo obsoleto»."""

    def test_a_after_the_first_buttress_there_are_no_platforms_and_the_layer_says_what_the_registry_says(self) -> None:
        """RF-016-24, RF-015-27: V01 con un solo contrafuerte que protege (y ninguna plataforma): la capa de entidades tiene su fila y dice
        lo que el registro."""
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v01.uid), {"FINISHED"})
        self.refresh()
        self.calculate()
        self.assertEqual(self.create(), {"FINISHED"})
        self.assertEqual(self.platforms(), 0)
        self.assertEqual(list(self.registry_states()), ["BTR-001"])
        self.assertEqual(self.layer_states(), self.registry_states())
        self.assertEqual(self.declared_guards(), {"BTR-001": 5.0})

    def test_b_changing_a_parameter_of_the_buttress_follows_the_rules_of_creating_it(self) -> None:
        """RF-015-01, RF-015-08, RF-015-12 (D-2): un nombre vacío, un resguardo sin valor (protege), la capa, la geometría y la partida
        vacías se rechazan con un mensaje que nombra la entidad (en español y en inglés) y **sin
        escribir nada**; hasta la T47 los aceptaba y lo que sigue fallaba con «La entidad no tiene nombre»."""
        key = "des.buttress.btr_001."
        self.refused_change(key + "name", "", "no tiene valor")
        self.refused_change(key + "name", "   ", "no tiene valor")
        self.refused_change(key + "guard_m", "", f"«{buttress_ops.FIRST}»")
        message = self.refused_change(key + "layer", "", "no tiene valor")
        self.assertIn(buttress_ops.CROWN_LAYER, message)
        self.refused_change(key + "start", "", "no tiene valor")
        self.refused_change(key + "feature", "", "no tiene valor")
        self.i18n.set_language("en")
        try:
            self.refused_change(key + "name", "", "has no value")
        finally:
            self.i18n.set_language("es")

    def test_c_the_second_buttress_and_the_chain_and_the_names_are_checked(self) -> None:
        """RF-015-01, RF-015-04 (D-2): con un segundo contrafuerte (parte de la superficie del primero) el nombre del otro se rechaza
        (también el que da el mismo nombre de dato), la partida del primero a la superficie del segundo es un ciclo y la del segundo
        al terreno, la de otro; un nombre libre se admite."""
        self.refresh()
        self.calculate(name=SECOND, feature=buttress_ops.CROWNS[0][0], start=self.panels.platform_default_start(), crown="135")
        self.assertEqual(self.create(), {"FINISHED"})
        self.assertEqual(list(self.registry_states()), ["BTR-001", "BTR-002"])
        self.assertEqual(self.platforms(), 0)
        self.refused_change("des.buttress.btr_002.name", buttress_ops.FIRST, f"ya lo tiene la entidad «{buttress_ops.FIRST}»")
        self.refused_change("des.buttress.btr_002.name", buttress_ops.FIRST.upper(), f"ya lo tiene la entidad «{buttress_ops.FIRST}»")
        self.refused_change("des.buttress.btr_001.start", "entity:BTR-002", "se cierra sobre sí misma")
        self.refused_change("des.buttress.btr_002.start", self.ground, f"ya parte la entidad «{buttress_ops.FIRST}»")

    def test_d_changing_the_guard_declares_the_new_one_at_once_and_updates_the_layer(self) -> None:
        """RF-015-10, RF-015-12, RF-015-29, RF-016-24 (D-2): «Cambiar parámetro…» del resguardo del primero a 12 m lanza lo que sigue (por
        pasos, con Esc): **el resguardo declarado es ya de 12 m**, sin una pasada de «Recalcular lo obsoleto» (hasta la T47 seguía en
        5 m), el del segundo no cambia y la capa de entidades dice lo que el registro."""
        self.assertEqual(self.declared_guards(), {"BTR-001": 5.0, "BTR-002": 5.0})
        self.assertEqual(self.change("des.buttress.btr_001.guard_m", "12"), {"FINISHED"})
        self.finish_refresh()
        self.assertEqual(self.declared_guards(), {"BTR-001": 12.0, "BTR-002": 5.0})
        self.assertEqual(self.layer_states(), self.registry_states())

    def test_e_after_recomputing_the_layer_says_the_same_as_the_registry_without_platforms(self) -> None:
        """RF-015-27, RF-016-24, RF-008-26 (D-1): en una versión **sin plataformas**, tras «Recalcular lo obsoleto» el registro dice
        «al día» y la capa **también** (hasta la T47 seguía diciendo «obsoleta» hasta la siguiente orden de entidades); otra pasada no
        cambia nada."""
        self.assertIn("stale", self.registry_states().values(), "el cambio del resguardo deja obsoleta alguna entidad")
        self.recompute()
        self.assertEqual(set(self.registry_states().values()), {"current"})
        self.assertEqual(self.layer_states(), self.registry_states())
        self.assertEqual(self.platforms(), 0)
        self.recompute()
        self.assertEqual(self.layer_states(), self.registry_states())
        self.assertEqual(self.declared_guards(), {"BTR-001": 12.0, "BTR-002": 5.0})


class BodyAfterTest(SupportedAfterHelpers, body_ops.CreateBodyTest):
    """V01 con un cuerpo apoyado (sin plataformas), **por el orden de las pruebas**: (a) el cuerpo, (b) lo que se rechaza y (c) la capa
    tras cambiar un parámetro y «Recalcular lo obsoleto»."""

    def test_a_after_the_body_there_are_no_platforms_and_the_layer_says_what_the_registry_says(self) -> None:
        """RF-016-24, RF-015-27: V01 con un solo cuerpo «bajo un techo» (y ninguna plataforma): la capa tiene su fila y dice lo que el
        registro."""
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v01.uid), {"FINISHED"})
        self.refresh()
        self.calculate()
        self.assertEqual(self.create(), {"FINISHED"})
        self.assertEqual(self.platforms(), 0)
        self.assertEqual(list(self.registry_states()), ["BDY-001"])
        self.assertEqual(self.layer_states(), self.registry_states())

    def test_b_changing_a_parameter_of_the_body_follows_the_rules_of_creating_it(self) -> None:
        """RF-015-01, RF-015-08 (D-2): un nombre vacío, la capa o la geometría vacías y como superficie conocida la superficie del propio
        cuerpo «bajo un techo» (que no deja ninguna) se rechazan con un mensaje que nombra la entidad y **sin escribir nada**."""
        key = "des.body.bdy_001."
        self.refused_change(key + "name", "", "no tiene valor")
        self.refused_change(key + "layer", "", body_ops.ROOF)
        self.refused_change(key + "feature", "", "no tiene valor")
        self.refused_change(key + "surface", "entity:BDY-001", "no deja una superficie")

    def test_c_after_changing_a_parameter_and_recomputing_the_layer_says_the_same_as_the_registry(self) -> None:
        """RF-015-10, RF-015-27, RF-016-24 (D-1, D-2): cambiar la distancia máxima del cuerpo (que lee su operación) lanza lo que sigue
        y deja la capa diciendo «obsoleta» como el registro; «Recalcular lo obsoleto» lo deja «al día» **en los dos**, sin
        plataformas."""
        self.assertEqual(self.change("des.body.bdy_001.max_distance_m", "80"), {"FINISHED"})
        self.finish_refresh()
        self.assertEqual(self.registry_states(), {"BDY-001": "stale"})
        self.assertEqual(self.layer_states(), {"BDY-001": "stale"})
        self.recompute()
        self.assertEqual(self.registry_states(), {"BDY-001": "current"})
        self.assertEqual(self.layer_states(), {"BDY-001": "current"})
        self.assertEqual(self.platforms(), 0)


class RemovalAfterTest(SupportedAfterHelpers, removal_ops.RemoveStockpileTest):
    """V01 con la plataforma «Sobre acopio» (de su mundo) y la retirada del Acopio 1 que parte de su superficie, **por el orden de las
    pruebas**: (a) la retirada, (b) lo que se rechaza entre los dos tipos y (c) la capa tras cambiar la transición y «Recalcular lo
    obsoleto». Con una plataforma viva no es el caso de D-1 (lo hacen el contrafuerte y el cuerpo), pero sí el del «después» de D-2."""

    def test_a_after_the_removal_the_layer_says_what_the_registry_says(self) -> None:
        """RF-016-24, RF-015-27: la retirada del Acopio 1 desde la superficie de la plataforma: la capa tiene las dos filas y dice lo que
        el registro."""
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v01.uid), {"FINISHED"})
        self.refresh()
        self.calculate()
        self.assertEqual(self.create(), {"FINISHED"})
        self.assertEqual(sorted(self.registry_states()), ["PLT-001", "RMV-001"])
        self.assertEqual(self.layer_states(), self.registry_states())

    def test_b_changing_a_parameter_of_the_removal_is_checked_against_the_other_types(self) -> None:
        """RF-015-01, RF-015-04, RF-015-08 (D-2): un nombre vacío, el nombre de la **plataforma**, la partida vacía y la de la plataforma a
        la superficie de la retirada (un ciclo entre dos tipos) se rechazan con un mensaje que nombra la entidad y **sin escribir
        nada**."""
        self.refused_change("des.removal.rmv_001.name", "", "no tiene valor")
        self.refused_change("des.removal.rmv_001.name", removal_ops.OVER[0], f"ya lo tiene la entidad «{removal_ops.OVER[0]}»")
        self.refused_change("des.removal.rmv_001.start", "", "no tiene valor")
        self.refused_change("des.platform.plt_001.start", "entity:RMV-001", "se cierra sobre sí misma")

    def test_c_after_changing_the_transition_and_recomputing_the_layer_says_the_same_as_the_registry(self) -> None:
        """RF-015-10, RF-015-27, RF-016-24 (D-2): cambiar el ángulo de la transición (que lee la operación de la retirada) lanza lo que
        sigue y deja la capa diciendo «obsoleta» como el registro; «Recalcular lo obsoleto» lo deja «al día» en los dos."""
        self.assertEqual(self.change("des.removal.rmv_001.transition_deg", "25"), {"FINISHED"})
        self.finish_refresh()
        self.assertEqual(self.registry_states()["RMV-001"], "stale")
        self.assertEqual(self.layer_states(), self.registry_states())
        self.recompute()
        self.assertEqual(self.registry_states()["RMV-001"], "current")
        self.assertEqual(self.layer_states(), self.registry_states())


for _parent, _mine in ((buttress_ops.CreateButtressTest, ButtressAfterTest), (body_ops.CreateBodyTest, BodyAfterTest),
                       (removal_ops.RemoveStockpileTest, RemovalAfterTest)):
    for _name in dir(_parent):  # sus pruebas son suyas: aquí solo el mundo y los ayudantes
        if _name.startswith("test") and _name not in vars(_mine):
            setattr(_mine, _name, None)
for _name in dir(platform_ops.CreatePlatformTest):
    for _mine in (ButtressAfterTest, BodyAfterTest, RemovalAfterTest):
        if _name.startswith("test") and _name not in vars(_mine):
            setattr(_mine, _name, None)
del _name, _parent, _mine


if __name__ == "__main__":
    unittest.main()
