# SPDX-License-Identifier: GPL-3.0-or-later
"""El perfil de pista (spec 017, T04; HU-017-1; RF-017-04, RF-017-07, RF-017-08; plan 017 §5.1, §5.2.2, §5.3.1 y §5.7 P-2;
ADR-0027; RF-008-01, RF-009-24).

Un perfil de pista son **dos cosas**, como el de banco de la 013 (``test_profiles.py``, de donde se copia la mecánica, no se
generaliza: P-2): su fila en la tabla del proyecto ``des_road_profile`` (``code``, ``name``, quién y cuándo; ni un valor)
y sus quince valores, que son parámetros de ``core.params`` (familias ``des.roadprofile.{p}.…``, :mod:`design.params`)
con su tipo, origen, decisor e historial: el ``code`` (``[a-z][a-z0-9_]*``) sale del nombre al crear el perfil y **no
cambia nunca**; el ``name`` (``PISTA_PRINCIPAL``) es libre y único sin distinguir mayúsculas. La operación de proyecto
``des.edit_road_profiles`` (declarada en ``provenance``; no se repite sola) crea, completa y renombra perfiles en **una**
transacción; todo se mira **antes** de escribir (un perfil sin nombre, con el nombre de otro, incompleto, con un valor
fuera de su rango o con un radio mínimo menor que la semianchura de su sección se rechaza nombrando el perfil, el campo y
el valor, sin registrar nada: RF-017-04, RF-017-07).

Los derivados (RF-017-08) —la calzada f·A, la anchura de la sección, su semianchura y la longitud mínima H/pd— **no son
parámetros** y salen con error ≤ 10⁻⁹ relativo; el cálculo a mano está hecho aquí con ``decimal`` (70 cifras) y no usa el
código de ``design``. Los valores de referencia de IMGA (``road_data.PROFILE``) son **solo de las pruebas**.

**Qué queda aquí (T48, RNF-017-09).** El «verde» deja lo puro: los derivados con su cálculo a mano de 70 cifras (RF-017-08), las comprobaciones
del perfil (RF-017-04, RF-017-07) y el código del nombre (RF-017-07), que suman ≈ 10 ms. Lo que **monta un proyecto** (la tabla, la
operación que crea, completa y renombra, los rechazos y la declaración de la operación: ≈ 0,9 s con el proyecto compartido) pasó al paso «hito»
como ``milestone_road_profiles_operation``; esa parte la sigue cubriendo en el «verde», con el proyecto de Blender,
``tests/blender/test_road_profile_ops.py`` (RF-017-07).
"""

from __future__ import annotations

import dataclasses
import math
import unittest
from decimal import Decimal, localcontext
from typing import Any

from tests.support import road_data as rd
from tests.support.package import import_geoblender

params = import_geoblender("design.params")
messages = import_geoblender("design.messages")
road_profiles = import_geoblender("design.road_profiles")

Param = params.RoadProfileParam
MAIN, OTHER = "PISTA_PRINCIPAL", "ACCESO_TAJO"
NOBODY = "Samuel (IMGA)"
OPTIONAL = ("mesh_factor", "metric")
"""Los dos valores con valor por defecto (D-2): el resto de los 15 se declara siempre al crear."""


def values_of(data: Any = rd.PROFILE, **changes: object) -> dict[str, object]:
    """Los quince valores de ``data`` (``road_data.ProfileData``) por último segmento de su clave (la clase es ``class``),
    con ``changes`` encima."""
    found: dict[str, object] = {
        param.value: getattr(data, "class_name" if param is Param.CLASS else param.value) for param in Param}
    found.update(changes)
    return found


def profile_of(code: str = "pista_principal", name: str = MAIN, **changes: object) -> Any:
    """El ``RoadProfile`` de referencia con ``changes`` encima."""
    return road_profiles.RoadProfile.from_values(code, name, values_of(**changes))


# --- Los derivados (RF-017-08) y el perfil como dato -----------------------------------------------------------------

# Cálculo a mano (Decimal, 70 cifras): (A, f, arcén, caballón, pd %, H) → (calzada f·A, sección, semianchura, H/pd).
HAND = {
    ("3.5", "3", "0", "1", "10", "30"): ("10.5", "11.5", "5.75", "300"),  # el de la spec: RF-017-08
    ("3.2", "2.5", "0.7", "1.1", "8.25", "17.3"): ("8.0", "9.8", "4.9", "209.696969696969696969696969696969696969"),
    ("4.2", "2", "0.5", "1.5", "12.5", "9.1"): ("8.4", "10.4", "5.2", "72.8"),
    ("2.55", "3.3", "0.35", "0.15", "7", "0"): ("8.415", "8.915", "4.4575", "0"),
}


def relative(found: float, expected: str) -> Decimal:
    """El error relativo de ``found`` frente al valor exacto ``expected`` (a 70 cifras; el error absoluto si es 0)."""
    with localcontext() as context:
        context.prec = 70
        exact = Decimal(expected)
        if exact == 0:
            return abs(Decimal(found))
        return abs(Decimal(found) - exact) / abs(exact)


class DerivedValuesTest(unittest.TestCase):
    def test_the_derived_values_of_the_reference_profile(self) -> None:
        """RF-017-08 (CE de la spec §11): con A = 3,5 m, f = 3, arcén 0 m y caballón 1 m la calzada es 10,5 m, la sección
        11,5 m y su semianchura 5,75 m, y con pd = 10 % y un desnivel de 30 m la longitud mínima es 300 m."""
        found = road_profiles.derived(profile_of())
        self.assertIsInstance(found, road_profiles.RoadDerived)
        self.assertEqual((found.carriageway_m, found.section_m, found.half_width_m), (10.5, 11.5, 5.75))
        self.assertEqual(found.min_length_m(30.0), 300.0)
        self.assertEqual(found.max_gradient_pct, 10.0)

    def test_the_derived_values_against_a_hand_calculation(self) -> None:
        """RF-017-08: la calzada, la sección, la semianchura y H/pd de varios perfiles coinciden con el cálculo a mano de 70
        cifras con error ≤ 10⁻⁹ relativo (también un desnivel nulo)."""
        for (a, f, arc, cab, pd, drop), (carriageway, section, half, length) in HAND.items():
            with self.subTest(vehicle=a, factor=f, gradient=pd):
                profile = profile_of(vehicle_width_m=float(a), lane_factor=float(f), shoulder_m=float(arc),
                                     berm_m=float(cab), max_gradient_pct=float(pd))
                found = road_profiles.derived(profile)
                self.assertLessEqual(relative(found.carriageway_m, carriageway), Decimal("1e-9"))
                self.assertLessEqual(relative(found.section_m, section), Decimal("1e-9"))
                self.assertLessEqual(relative(found.half_width_m, half), Decimal("1e-9"))
                self.assertLessEqual(relative(found.min_length_m(float(drop)), length), Decimal("1e-9"))

    def test_the_semi_width_is_the_one_that_limits_the_minimum_radius(self) -> None:
        """RF-017-04, RF-017-08: la semianchura derivada es la de ``params.road_half_width_m`` (una sola fuente: la que
        limita el radio mínimo) y la sección es la calzada más el arcén y el caballón."""
        profile = profile_of(shoulder_m=0.5, berm_m=1.5)
        found = road_profiles.derived(profile)
        self.assertEqual(found.half_width_m, params.road_half_width_m(3.5, 3.0, 0.5, 1.5))
        self.assertEqual(found.section_m, found.carriageway_m + 0.5 + 1.5)
        self.assertEqual(found.half_width_m, found.section_m / 2.0)

    def test_the_length_needs_a_finite_number_and_uses_the_magnitude(self) -> None:
        """RF-017-08: la longitud mínima para salvar un desnivel es la del desnivel en valor absoluto (subir o bajar
        cuesta lo mismo); un valor que no es un número real finito es un error del programa (``TypeError`` si no es un
        número, ``ValueError`` si es NaN o infinito)."""
        found = road_profiles.derived(profile_of())
        self.assertEqual(found.min_length_m(-30.0), 300.0)
        self.assertEqual(found.min_length_m(0), 0.0)
        self.assertEqual(found.min_length_m(30), 300.0)
        for bad in ("30", None, True, [1.0]):
            with self.subTest(value=bad), self.assertRaises(TypeError):
                found.min_length_m(bad)  # type: ignore[arg-type]
        for bad in (math.nan, math.inf, -math.inf):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                found.min_length_m(bad)

    def test_derived_values_are_not_parameters(self) -> None:
        """RF-017-08: la calzada, la sección, la semianchura y H/pd no son campos ni parámetros del perfil (no se guardan
        ni se pueden fijar: se derivan); el perfil y lo derivado son inmutables y los quince campos de valor son los de
        las familias ``des.roadprofile.{p}.*`` (la clase normativa es ``class_name``)."""
        profile = profile_of()
        fields = [field.name for field in dataclasses.fields(profile)]
        self.assertEqual(fields[:2], ["code", "name"])
        self.assertEqual([("class" if name == "class_name" else name) for name in fields[2:]],
                         [str(param) for param in Param])
        for name in ("carriageway_m", "section_m", "half_width_m", "min_length_m", "derived"):
            self.assertNotIn(name, dataclasses.asdict(profile))
        for name in ("code", "vehicle_width_m", "carriageway_m"):
            with self.subTest(name=name), self.assertRaises((AttributeError, TypeError)):
                setattr(profile, name, 1.0)
        found = road_profiles.derived(profile)
        with self.assertRaises((AttributeError, TypeError)):
            found.carriageway_m = 1.0  # type: ignore[misc]
        self.assertEqual(profile, profile_of())

    def test_defaults_and_float64(self) -> None:
        """RF-017-07 (D-2; regla 4: float64): sin factor de malla ni métrica toma 1,0 y la exacta (los únicos valores por
        defecto del perfil); los enteros se guardan como ``float`` y la clase, sin los espacios de los extremos."""
        profile = profile_of(mesh_factor=None, metric=None)
        self.assertEqual((profile.mesh_factor, profile.metric), (1.0, "exact"))
        whole = profile_of(vehicle_width_m=4, lane_factor=2, shoulder_m=0, berm_m=1, max_gradient_pct=10,
                           station_step_m=1, max_mean_gradient_pct=10, curve_radius_m=20, min_radius_m=12,
                           cut_angle_deg=60, fill_angle_deg=35, reach_m=60, mesh_factor=1,
                           **{"class": "  Pista de acceso "})
        for param in Param:
            if param.value not in ("class", "metric"):
                self.assertIs(type(getattr(whole, param.value)), float, param.value)
        self.assertEqual(whole.class_name, "Pista de acceso")


class ProfileChecksTest(unittest.TestCase):
    """Un ``RoadProfile`` no se crea con un valor fuera de su rango, sin valor, con un radio que no cabe o sin nombre: nada se
    calcula con él (RF-017-04, RF-017-07)."""

    def rejected(self, **changes: object) -> Any:
        with self.assertRaises(messages.DesignError) as caught:
            profile_of(**changes)
        return caught.exception

    def test_every_range_names_the_profile_the_field_and_the_value(self) -> None:
        """RF-017-04, RF-017-07: A, f, pd, w, pm, R y Rmín > 0, arcén y caballón ≥ 0, los ángulos de (0; 90)°, el alcance > 0 y
        el factor de malla de (0; 1] se rechazan fuera de su rango con ``des.road_profile_value_range`` nombrando el
        perfil por su nombre, la clave del campo y el valor; la métrica, fuera de sus opciones."""
        bad = (("vehicle_width_m", 0.0), ("vehicle_width_m", -3.5), ("lane_factor", 0.0), ("shoulder_m", -0.001),
               ("berm_m", -1.0), ("max_gradient_pct", 0.0), ("station_step_m", 0.0), ("max_mean_gradient_pct", -1.0),
               ("curve_radius_m", 0.0), ("min_radius_m", 0.0), ("cut_angle_deg", 0.0), ("cut_angle_deg", 90.0),
               ("fill_angle_deg", 95.0), ("reach_m", 0.0), ("mesh_factor", 0.0), ("mesh_factor", 1.5),
               ("vehicle_width_m", math.nan), ("reach_m", math.inf), ("metric", "chamfer7"))
        for field, value in bad:
            with self.subTest(field=field, value=value):
                error = self.rejected(**{field: value})
                self.assertEqual(error.code, "des.road_profile_value_range")
                self.assertEqual(error.field, f"des.roadprofile.pista_principal.{field}")
                self.assertEqual(error.obj, "Perfil de pista «PISTA_PRINCIPAL»")
                self.assertIn("«PISTA_PRINCIPAL»", error.text)
                self.assertIn(error.field, error.text)
                if isinstance(value, float) and math.isfinite(value):
                    self.assertEqual(error.value, value)
        for field, value in (("shoulder_m", 0.0), ("berm_m", 0.0), ("mesh_factor", 1.0), ("cut_angle_deg", 89.999),
                             ("reach_m", 0.001)):
            with self.subTest(field=field, value=value):  # los extremos incluidos valen
                self.assertEqual(getattr(profile_of(**{field: value}), field), value)

    def test_a_value_without_value_is_rejected_and_nothing_is_chosen(self) -> None:
        """RF-017-04 (un perfil incompleto), D-2 (sin valor por defecto): cada uno de los trece valores sin valor (``None``;
        la clase, también en blanco) se rechaza con ``des.road_profile_value_missing`` nombrando el perfil y el campo; solo
        el factor de malla y la métrica toman el valor de siempre."""
        for param in Param:
            if param.value in OPTIONAL:
                continue
            for value in ((None, "  ") if param is Param.CLASS else (None,)):
                with self.subTest(field=param.value, value=value):
                    error = self.rejected(**{param.value: value})
                    self.assertEqual((error.code, error.field, error.value),
                                     ("des.road_profile_value_missing", f"des.roadprofile.pista_principal.{param.value}",
                                      None))
                    self.assertIn("«PISTA_PRINCIPAL»", error.text)
                    self.assertIn("Perfil de pista…", error.text)
        for name in OPTIONAL:
            with self.subTest(default=name):
                self.assertEqual(getattr(profile_of(**{name: None}), name), {"mesh_factor": 1.0, "metric": "exact"}[name])

    def test_the_minimum_radius_must_fit_the_curve_and_the_section(self) -> None:
        """RF-017-04, RF-017-07: ``Rmín`` mayor que ``R`` (``des.road_profile_radius_order``) y ``Rmín`` menor que la
        semianchura de la sección (``des.road_profile_radius_narrow``: el borde interior de una curva se plegaría) se
        rechazan nombrando el perfil, el campo del radio mínimo y su valor; ``Rmín`` igual a la semianchura (5,75 m) vale, y
        con una sección más ancha el mínimo sube con ella."""
        error = self.rejected(min_radius_m=21.0)
        self.assertEqual((error.code, error.field, error.value),
                         ("des.road_profile_radius_order", "des.roadprofile.pista_principal.min_radius_m", 21.0))
        error = self.rejected(min_radius_m=5.0)
        self.assertEqual((error.code, error.field, error.value),
                         ("des.road_profile_radius_narrow", "des.roadprofile.pista_principal.min_radius_m", 5.0))
        self.assertIn("«PISTA_PRINCIPAL»", error.text)
        self.assertEqual(profile_of(min_radius_m=5.75).min_radius_m, 5.75)
        self.assertEqual(self.rejected(min_radius_m=5.75, berm_m=3.0).code, "des.road_profile_radius_narrow")  # semianchura 6,75 m
        self.assertEqual(self.rejected(curve_radius_m=10.0).code, "des.road_profile_radius_order")  # Rmín 12 > R 10
        self.assertEqual(profile_of(min_radius_m=6.75, berm_m=3.0).min_radius_m, 6.75)

    def test_a_profile_without_a_name_or_with_a_wrong_code(self) -> None:
        """RF-017-04, RF-017-07: un nombre vacío o de espacios se rechaza con ``des.road_profile_name_missing`` (nombrando el
        perfil por su código); un nombre que no es un texto, un valor que no es un número real o un código que no es
        ``[a-z][a-z0-9_]*`` son errores del programa."""
        for name in ("", "   ", "\t"):
            with self.subTest(name=name):
                with self.assertRaises(messages.DesignError) as caught:
                    profile_of(name=name)
                self.assertEqual((caught.exception.code, caught.exception.field), ("des.road_profile_name_missing", "name"))
                self.assertIn("«pista_principal»", caught.exception.text)
        with self.assertRaises(TypeError):
            profile_of(name=None)  # type: ignore[arg-type]
        for code in ("", "Pista", "1pista", "pista principal", "pista.1", "pístá"):
            with self.subTest(code=code), self.assertRaises(ValueError):
                profile_of(code=code)
        for field, value in (("vehicle_width_m", True), ("lane_factor", "3"), ("reach_m", [60.0]), ("class", 3)):
            with self.subTest(field=field), self.assertRaises(TypeError):
                profile_of(**{field: value})
        with self.assertRaises(ValueError):
            road_profiles.RoadProfile.from_values("pista", "Pista", {**values_of(), "protect": 1.0})  # no es de un perfil

    def test_the_profiles_built_from_the_resolved_values(self) -> None:
        """RF-017-07, RF-017-04: ``road_profiles_from`` arma los perfiles de unos códigos con los valores que resuelve el
        cálculo (clave ``des.roadprofile.{p}.…`` → valor), con el nombre de la tabla (o el código si no se da) y sin
        repetir; un valor que falta, o fuera de rango, es el rechazo del perfil nombrándolo por su nombre."""
        resolved = {params.road_profile_key(code, last): value
                    for code in ("pista_principal", "acceso_tajo") for last, value in values_of().items()}
        found = road_profiles.road_profiles_from(resolved, ["pista_principal", "acceso_tajo", "pista_principal"],
                                                 {"pista_principal": MAIN})
        self.assertEqual(list(found), ["pista_principal", "acceso_tajo"])
        self.assertEqual((found["pista_principal"].name, found["acceso_tajo"].name), (MAIN, "acceso_tajo"))
        self.assertEqual(found["pista_principal"], profile_of())
        del resolved["des.roadprofile.acceso_tajo.reach_m"]
        with self.assertRaises(messages.DesignError) as caught:
            road_profiles.road_profiles_from(resolved, ["acceso_tajo"], {"acceso_tajo": OTHER})
        self.assertEqual((caught.exception.code, caught.exception.field),
                         ("des.road_profile_value_missing", "des.roadprofile.acceso_tajo.reach_m"))
        self.assertIn("«ACCESO_TAJO»", caught.exception.text)

    def test_the_names_of_the_profiles_must_be_different(self) -> None:
        """RF-017-04: un perfil que repite el nombre de otro (sin distinguir mayúsculas ni espacios en los bordes) se rechaza
        con ``des.road_profile_name_repeated`` nombrando los dos; dos con el mismo código son un error del programa."""
        first, second = profile_of(), profile_of("acceso_tajo", OTHER)
        road_profiles.check_names([first, second])
        road_profiles.check_names([])
        for repeated in (profile_of("otro", MAIN), profile_of("otro", "pista_principal"), profile_of("otro", " pista_PRINCIPAL ")):
            with self.subTest(name=repeated.name), self.assertRaises(messages.DesignError) as caught:
                road_profiles.check_names([first, second, repeated])
            error = caught.exception
            self.assertEqual((error.code, error.field), ("des.road_profile_name_repeated", "name"))
            self.assertIn("«otro»", error.text)
            self.assertIn("«pista_principal»", error.text)
        with self.assertRaises(ValueError):
            road_profiles.check_names([first, profile_of(name="Otro nombre")])


class CodeTest(unittest.TestCase):
    def test_the_code_is_the_ascii_name_in_lowercase(self) -> None:
        """RF-017-07 (D-17 de la 013): el código es el nombre en ASCII y en minúsculas, sin tildes y con «_» en lugar de lo
        demás (``PISTA_PRINCIPAL`` da ``pista_principal``); sin letra delante lleva ``p_`` y sin nada, ``p``; si el del
        nombre ya es de otro perfil se le pone ``_2``, ``_3``… y dura como mucho 32 caracteres."""
        cases = {MAIN: "pista_principal", "Acceso al tajo": "acceso_al_tajo", "Rampa 2 (norte)": "rampa_2_norte", "10-60": "p_10_60",
                 "": "p", "¡¿?!": "p"}
        for name, code in cases.items():
            with self.subTest(name=name):
                self.assertEqual(road_profiles.profile_code(name, ()), code)
                self.assertTrue(params.is_code(code))
        self.assertEqual(road_profiles.profile_code(MAIN, {"pista_principal"}), "pista_principal_2")
        self.assertEqual(road_profiles.profile_code("pista principal", {"pista_principal", "pista_principal_2"}),
                         "pista_principal_3")
        long = "perfil de pista con un nombre larguisimo de acceso al tajo"
        code = road_profiles.profile_code(long, ())
        self.assertLessEqual(len(code), 32)
        again = road_profiles.profile_code(long, {code})
        self.assertNotEqual(again, code)
        self.assertLessEqual(len(again), 32)


if __name__ == "__main__":
    unittest.main()
