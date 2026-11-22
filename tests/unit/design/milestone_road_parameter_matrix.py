# SPDX-License-Identifier: GPL-3.0-or-later
"""«Cambiar parámetro…» de una pista y de un perfil de pista: **la matriz entera** del ámbito proyecto y de las dependencias declaradas, como prueba de **hito** (spec 017, T49;
hallazgos T47-1 y T47-2 de la verificación de lo cambiado; HU-017-1; RF-017-03, RF-017-04, RF-017-07; RF-015-08, RF-015-15 y RF-015-17).

El «verde» (``test_road_parameter_check``) lleva lo mínimo de cada arreglo (``test_i2`` y ``test_k``, < 0,05 s con los demás de la tarea: RNF-017-09, el margen del A/B es corto); aquí, con el
mismo proyecto de prueba (la cantera de la 014 con la cadena de la T21, los perfiles de V01 y del proyecto y las dos pistas libres), **todos** los casos:

- **T47-1 — el ámbito proyecto** (:class:`ProjectScopeMatrixTest`): cada valor del perfil con los valores **del proyecto** (``PROJECT_PROFILE``) rechaza lo que rechaza «Perfil de pista…» en ese ámbito
  (el radio mínimo menor que la semianchura, el radio de las curvas menor que el mínimo, el caballón que sube la semianchura, el ángulo de 90° y una métrica que no existe), con el perfil, el campo y
  el valor y el texto del diálogo; los valores buenos y la clase se admiten; el perfil con solo algunos valores del proyecto (**no se lee ninguna versión**) solo se mira en su rango, y el
  rango se comprueba siempre; sin valor, no hace nada.
- **T47-2 — ``supports`` declarado a mano** (:class:`DeclaredSupportsMatrixTest`): ninguna dependencia declarada es la propia pista, lo que parte de su superficie ni una pista que ya se apoya en ella,
  directa o por otras; una lista se rechaza por la primera que cierra el ciclo; lo que ya declaran las pistas, una cadena propia, un código que la versión no tiene, vaciarlo y ``None`` se admite.

Todo se comprueba **sin escribir nada** (el contador de cambios de la base no se mueve) y con el texto en los dos idiomas sin marcadores sin llenar.
"""

from __future__ import annotations

from typing import Any

from tests.unit.design.test_road_parameter_check import FREE_ROADS, PROFILE, PROJECT_PROFILE, WORLD, RoadParameterCase, design_params, key, messages, road_profiles


class ProjectScopeMatrixTest(RoadParameterCase):
    """RF-017-04, RF-017-07, RF-015-08 (T49; T47-1): «Cambiar parámetro…» de un valor del perfil de pista con el ámbito proyecto (sin versión): todos los casos."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.write_extra()

    def test_a_every_refusal_of_the_profile_dialog_is_refused_for_the_project_with_the_values_of_the_project(self) -> None:
        """RF-017-04, RF-017-07, RF-015-08: el radio mínimo menor que la semianchura (3 m con 5,75 m), el radio de las curvas menor que el mínimo (5 m con 12 m), el caballón de 20 m (semianchura de 15,25 m), el
        ángulo de desmonte de 90° y el de terraplén de 90° (la definición los admite y RF-017-04 los excluye) y una métrica que no existe, con el perfil, el campo y el valor y **el mismo texto que
        «Perfil de pista…»**; también el factor de calzada, el ancho del vehículo y el arcén que suben la semianchura por encima de Rmín (la regla cruzada que provoca otro valor); sin escribir nada."""
        before = self.snapshot()
        narrow = "des.road_profile_radius_narrow"
        for param, value, expected, field, shown in (("min_radius_m", 3.0, narrow, "min_radius_m", 3.0), ("curve_radius_m", 5.0, "des.road_profile_radius_order", "min_radius_m", 12.0),
                                                     ("berm_m", 20.0, narrow, "min_radius_m", 12.0), ("vehicle_width_m", 10.0, narrow, "min_radius_m", 12.0), ("lane_factor", 8.0, narrow, "min_radius_m", 12.0),
                                                     ("shoulder_m", 15.0, narrow, "min_radius_m", 12.0), ("cut_angle_deg", 90.0, "des.road_profile_value_range", "cut_angle_deg", 90.0),
                                                     ("fill_angle_deg", 90.0, "des.road_profile_value_range", "fill_angle_deg", 90.0), ("metric", "bogus", "des.road_profile_value_range", "metric", "bogus")):
            with self.subTest(param=param, value=value):
                error = self.refused_in_project(param, value, expected, field, shown)
                for text in (error.text, error.text_in("en")):
                    self.assertNotIn("{", text)
        self.assertEqual(self.snapshot(), before, "el rechazo ha escrito algo")

    def test_b_the_good_values_the_class_and_the_incomplete_profile_pass_and_the_range_is_always_checked(self) -> None:
        """RF-017-04, RF-017-07: los valores buenos (89,9°, Rmín = 6 m, R = Rmín, caballón de 2 m) y la clase se admiten; el perfil **sin los demás valores del proyecto** no tiene con qué cruzarse (esas
        reglas las dice el cálculo de la pista, que ya rechaza legible) y solo se mira su rango, que se comprueba **siempre**; los valores de V01 de ``pista_principal`` no se leen (el proyecto no tiene los
        suyos: no se mira ninguna otra versión); sin valor, no hace nada."""
        before = self.snapshot()
        for param, value in (("cut_angle_deg", 89.9), ("min_radius_m", 6.0), ("curve_radius_m", 12.0), ("berm_m", 2.0), ("class", "Otra clase")):
            with self.subTest(param=param, value=value):
                self.project_check(param, value)
        self.project_check("min_radius_m", 3.0, profile="sin_otros_valores")
        self.project_check("curve_radius_m", 5.0, profile="sin_otros_valores")
        self.project_check("min_radius_m", 3.0, profile=PROFILE)
        self.project_check("min_radius_m", None)
        for param, value in (("cut_angle_deg", 90.0), ("cut_angle_deg", -1.0), ("metric", "bogus")):
            with self.subTest(param=param, value=value), self.assertRaises(messages.DesignError) as caught:
                self.project_check(param, value, profile="sin_otros_valores")
            self.assertEqual(caught.exception.code, "des.road_profile_value_range")
        self.assertEqual(self.snapshot(), before)

    def test_c_the_same_value_is_refused_by_the_version_and_the_project_with_their_own_values(self) -> None:
        """RF-017-04, RF-017-07 (T40 y T49): el valor que rechaza el ámbito versión con los valores de V01 es el que rechaza el ámbito proyecto con los del proyecto (el mismo perfil de referencia en los dos):
        el mismo código, el mismo texto en español y en inglés; no cambia lo de la versión."""
        for param, value in (("min_radius_m", 3.0), ("curve_radius_m", 5.0), ("berm_m", 20.0), ("cut_angle_deg", 90.0)):
            with self.subTest(param=param):
                with self.assertRaises(messages.DesignError) as in_version:
                    road_profiles.check_profile_change(self.project, design_params.road_profile_key(PROFILE, param), value, version=self.v1.uid)
                with self.assertRaises(messages.DesignError) as in_project:
                    self.project_check(param, value)
                self.assertEqual(in_version.exception.code, in_project.exception.code)
                self.assertEqual(in_version.exception.values["value"], in_project.exception.values["value"])


class DeclaredSupportsMatrixTest(RoadParameterCase):
    """RF-015-15, RF-015-17, RF-017-03 (T49; T47-2): ``des.road.{e}.supports`` declarado a mano: todos los casos de la cadena y de lo que las pistas pisan."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.write_extra()

    def test_a_a_dependency_that_closes_a_cycle_is_refused_with_its_path(self) -> None:
        """RF-015-15, RF-017-03: la pista no se apoya en sí misma, en lo que parte de su superficie —aguas abajo de su cadena: el ramal y el relleno— ni en una pista que ya se apoya en ella por su origen
        (RDW-004 sale de RDW-001@40) o por otras (RDW-005 sale de RDW-004@5): ``des.entity_supports_unknown`` con la pista, el campo, el valor entero, a quién se apoyaría y el recorrido del ciclo en el
        motivo; la lista se rechaza por la primera que lo cierra; y sin escribir nada."""
        before = self.snapshot()
        cases = (("RDW-001", "RDW-002", "RDW-002", ("RDW-002", "RDW-001")), ("RDW-001", "PLT-002", "PLT-002", ("PLT-002", "RDW-002", "RDW-001")), ("RDW-002", "PLT-002", "PLT-002", ("PLT-002", "RDW-002")),
                 ("RDW-001", "RDW-001", "RDW-001", ()), ("RDW-002", "RDW-002", "RDW-002", ()), ("RDW-001", "RDW-004", "RDW-004", ("RDW-004", "RDW-001")),
                 ("RDW-001", "RDW-004, RDW-005", "RDW-004", ("RDW-004", "RDW-001")), ("RDW-001", "RDW-005", "RDW-005", ("RDW-005", "RDW-004", "RDW-001")),
                 ("RDW-001", "PLT-001, RDW-002", "RDW-002", ("RDW-002", "RDW-001")), ("RDW-001", "RDW-009,  RDW-005 ", "RDW-005", ("RDW-005", "RDW-004", "RDW-001")))
        for code, value, target, around in cases:
            with self.subTest(code=code, value=value):
                name = WORLD[code][0] if code in WORLD else FREE_ROADS[code][0]
                error = self.refused(key(code, "supports"), value, "des.entity_supports_unknown", entity=name, value=value, target=target)
                for member in around:
                    self.assertIn(member, str(error.values["reason"]))
        self.assertEqual(self.snapshot(), before)

    def test_b_what_is_not_a_cycle_is_accepted(self) -> None:
        """RF-015-15, RF-017-03: lo que ya declaran el ramal y la pista (el ramal en la pista, la pista en la plataforma de la que parte), una cadena propia (una pista libre en la principal, otra en dos), un
        código que la versión no tiene (lo dice el cálculo), vaciarlo y ``None`` se admiten."""
        for code, value in (("RDW-002", "RDW-001"), ("RDW-001", "PLT-001"), ("RDW-003", "RDW-001, PLT-001"), ("RDW-004", "RDW-001"), ("RDW-005", "RDW-004, RDW-001"), ("RDW-001", "RDW-009"),
                            ("RDW-001", ""), ("RDW-001", None)):
            with self.subTest(code=code, accepted=value):
                self.accepted(key(code, "supports"), value)

    def test_c_the_other_types_are_unchanged(self) -> None:
        """RF-015-15 (T49: solo la pista): el ``supports`` de una plataforma sigue sin pasar por una regla al cambiarlo (su ciclo lo rechaza el cálculo, como siempre): sin cambio para la 015 y la 016."""
        self.accepted(key("PLT-001", "supports"), "PLT-002")
        self.accepted(key("PLT-002", "supports"), "RDW-001")


if __name__ == "__main__":
    import unittest

    unittest.main()
