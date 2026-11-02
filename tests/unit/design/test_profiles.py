# SPDX-License-Identifier: GPL-3.0-or-later
"""Perfiles de banco: lo derivado y las comprobaciones del modelo (spec 013, T02; HU-013-4;
RF-013-18, RF-013-19, RF-013-20; plan 013 §5.2.2 y §5.3.1, D-7 y D-17).

``design.model.BenchProfile`` es un perfil con un código inmutable (``[a-z][a-z0-9_]*``, D-17),
un nombre libre (``EXPL_10_60_6``) y sus cinco valores (altura de banco ``h`` en m, inclinación
de la cara ``α`` en °, berma mínima ``B`` en m, cota de ancla en m y factor de malla). El avance
``a = h/tan α + B`` (m) y el talud general ``atan(h/a)`` (°) son **valores derivados**, no
parámetros, con error ≤ 10⁻⁹ relativo (RF-013-20), y el perfil se marca «no resuelto por la
rejilla» cuando la huella horizontal de su cara o su berma es menor que el paso de la rejilla
(ADR-0014). Un perfil sin nombre, con el nombre de otro, o con un valor sin valor o fuera de rango
se rechaza nombrándolo, con el campo y el valor, y no se calcula con él (RF-013-19).

Los derivados de la spec están hechos a mano con 70 cifras (``decimal``; ``tan 60°``, ``tan 35°``
y ``atan`` por series): no usan el código de ``design``.
"""

from __future__ import annotations

import dataclasses
import math
import unittest

from tests.support.package import import_geoblender

model = import_geoblender("design.model")
messages = import_geoblender("design.messages")
params = import_geoblender("design.params")
grid_mod = import_geoblender("gis.grid")

# Cálculo a mano (Decimal, 70 cifras): nombre → (altura, cara, berma, huella de la cara, avance,
# talud general).
HAND = {
    "EXPL_10_60_6": (10.0, 60.0, 6.0, 5.773502691896257645, 11.773502691896257645,
                     40.343404702690171789),
    "REST_5_35_6": (5.0, 35.0, 6.0, 7.140740033710572511, 13.140740033710572511,
                    20.831623498965657231),
    "DESD_10_45_6": (10.0, 45.0, 6.0, 10.0, 16.0, 32.005383208083495561),
}
ANCHOR = 125.0


def profile_of(which: str, /, **changes: object) -> object:
    """El perfil de la spec con ese nombre (código = nombre en minúsculas), con los cambios."""
    height, face, berm, *_ = HAND[which]
    values: dict[str, object] = dict(code=which.lower(), name=which, height_m=height,
                                     face_deg=face, berm_m=berm, anchor_m=ANCHOR)
    values.update(changes)
    return model.BenchProfile(**values)


def project_grid(step: float, step_y: float | None = None) -> object:
    """Una rejilla de proyecto de 20 × 20 celdas con ese paso (en Y, ``step_y`` si se da)."""
    return grid_mod.Grid(west=699_700.0, north=4_400_020.0, dx=step,
                         dy=step if step_y is None else step_y, ncols=20, nrows=20)


class DerivedValuesTest(unittest.TestCase):
    def test_advance_and_general_slope_of_the_spec_profiles(self) -> None:
        """RF-013-20 (CE-013-03): ``EXPL_10_60_6`` da 11,77 m y 40,3°, ``REST_5_35_6`` 13,14 m y
        20,83° y ``DESD_10_45_6`` 16,00 m y 32,0°, con error ≤ 10⁻⁹ relativo frente al
        cálculo a mano de 70 cifras."""
        # Como los escribe la spec: avance (2 decimales) y talud general (1 o 2 decimales).
        shown = {"EXPL_10_60_6": (11.77, 40.3, 1), "REST_5_35_6": (13.14, 20.83, 2),
                 "DESD_10_45_6": (16.00, 32.0, 1)}
        for name, (_h, _f, _b, footprint, advance, general) in HAND.items():
            profile = profile_of(name)
            shown_advance, shown_general, decimals = shown[name]
            with self.subTest(name=name):
                self.assertLessEqual(abs(profile.avance_m - advance) / advance, 1e-9)
                self.assertLessEqual(abs(profile.general_deg - general) / general, 1e-9)
                self.assertLessEqual(abs(profile.face_footprint_m - footprint) / footprint, 1e-9)
                self.assertEqual(round(profile.avance_m, 2), shown_advance)
                self.assertEqual(round(profile.general_deg, decimals), shown_general)

    def test_general_tangent_is_height_over_advance(self) -> None:
        """RF-013-20, RF-013-13: la tangente del talud general es ``h / a`` (exacta, no la de un
        ángulo ya redondeado), y ``general_deg`` es su arcotangente en grados."""
        for name in HAND:
            profile = profile_of(name)
            with self.subTest(name=name):
                self.assertEqual(profile.general_tan, profile.height_m / profile.avance_m)
                self.assertAlmostEqual(math.tan(math.radians(profile.general_deg)),
                                       profile.general_tan, places=14)

    def test_without_berm_the_general_slope_is_the_face(self) -> None:
        """RF-013-20: con berma 0 el avance es la huella de la cara y el talud general es la
        cara; una cara casi vertical y una berma grande dan un talud general suave."""
        flat = profile_of("EXPL_10_60_6", berm_m=0.0)
        self.assertAlmostEqual(flat.avance_m, flat.face_footprint_m, places=12)
        self.assertAlmostEqual(flat.general_deg, 60.0, places=9)
        gentle = profile_of("EXPL_10_60_6", face_deg=89.9, berm_m=100.0)
        self.assertLess(gentle.general_deg, 6.0)

    def test_derived_values_are_not_parameters(self) -> None:
        """RF-013-20: el avance y el talud general no son campos ni parámetros del perfil (no
        se guardan ni se pueden fijar: se derivan); el perfil es inmutable y los cinco campos
        de valor son los de las familias ``des.bench.{p}.*``."""
        profile = profile_of("EXPL_10_60_6")
        fields = [field.name for field in dataclasses.fields(profile)]
        self.assertEqual(fields, ["code", "name", "height_m", "face_deg", "berm_m", "anchor_m",
                                  "mesh_factor"])
        self.assertEqual(sorted(fields[2:]), sorted(str(item) for item in params.BenchParam))
        self.assertNotIn("avance_m", dataclasses.asdict(profile))
        self.assertNotIn("general_deg", dataclasses.asdict(profile))
        for name in ("avance_m", "general_deg", "height_m", "code"):
            # Un campo da FrozenInstanceError (AttributeError); un derivado, en Python 3.13 con
            # slots, TypeError: en los dos casos no se puede fijar.
            with self.subTest(name=name), self.assertRaises((AttributeError, TypeError)):
                setattr(profile, name, 1.0)
            self.assertEqual(profile, profile_of("EXPL_10_60_6"))
        self.assertEqual(profile.mesh_factor, 1.0)
        self.assertEqual(profile, profile_of("EXPL_10_60_6"))

    def test_integers_become_floats(self) -> None:
        """RF-013-18 (regla 4: float64): los valores enteros se guardan como ``float``."""
        profile = profile_of("EXPL_10_60_6", height_m=10, face_deg=60, berm_m=6,
                             anchor_m=125, mesh_factor=1)
        for name in ("height_m", "face_deg", "berm_m", "anchor_m", "mesh_factor"):
            self.assertIs(type(getattr(profile, name)), float, name)


class UnresolvedByTheGridTest(unittest.TestCase):
    def test_resolved_profile_has_no_mark(self) -> None:
        """RF-013-20 (ADR-0014): con la huella de la cara (5,77 m) y la berma (6 m) mayores o
        iguales que el paso de la rejilla del proyecto, el perfil está resuelto."""
        profile = profile_of("EXPL_10_60_6")
        for step in (0.5, 1.0, 2.0, 5.0, 5.77, 5.7735):
            with self.subTest(step=step):
                self.assertIsNone(profile.unresolved_by(project_grid(step)))

    def test_face_or_berm_narrower_than_a_cell_is_marked(self) -> None:
        """RF-013-20: si la huella de la cara (5,77 m) o la berma (6 m) es menor que el paso, el
        perfil se marca «no resuelto por la rejilla», con el texto en español (y en inglés) y las
        cifras; con paso 5,8 m es la cara; con 7 m, las dos; el paso es el mayor de dx y dy."""
        profile = profile_of("EXPL_10_60_6")
        text = profile.unresolved_by(project_grid(5.8))
        self.assertIsNotNone(text)
        self.assertIn("«EXPL_10_60_6»", text)
        self.assertIn("no está resuelto por la rejilla", text)
        self.assertIn("5,77 m", text)
        self.assertIn("6 m", text)
        self.assertIn("5,8 m", text)
        english = profile.unresolved_by(project_grid(5.8), language="en")
        self.assertIn("is not resolved by the grid", english)
        self.assertIn("5.77 m", english)
        self.assertIsNotNone(profile.unresolved_by(project_grid(7.0)))
        self.assertIsNotNone(profile.unresolved_by(project_grid(1.0, 7.0)))
        self.assertIsNone(profile.unresolved_by(project_grid(1.0, 2.0)))
        thin = profile_of("DESD_10_45_6", berm_m=0.5)
        self.assertIsNotNone(thin.unresolved_by(project_grid(1.0)))
        self.assertIsNone(thin.unresolved_by(project_grid(0.5)))
        steep = profile_of("EXPL_10_60_6", face_deg=89.0, berm_m=6.0)
        self.assertIsNotNone(steep.unresolved_by(project_grid(1.0)))

    def test_no_berm_is_nothing_to_resolve(self) -> None:
        """RF-013-20 (decisión de la T02): una berma de 0 m no tiene huella que resolver; solo
        una berma mayor que 0 y menor que el paso, o la cara, marca el perfil."""
        flat = profile_of("DESD_10_45_6", berm_m=0.0)
        self.assertIsNone(flat.unresolved_by(project_grid(2.0)))
        self.assertIsNotNone(flat.unresolved_by(project_grid(11.0)))

    def test_the_mark_is_the_warning_of_the_catalog(self) -> None:
        """RF-013-20, RF-013-30: la marca es el aviso ``des.profile_unresolved`` del catálogo,
        que se informa y no se lanza."""
        message = messages.MESSAGES["des.profile_unresolved"]
        self.assertEqual(message.severity, "warning")
        with self.assertRaises(ValueError):
            messages.DesignError("des.profile_unresolved", obj="Perfil", field="campo")


class ValidationTest(unittest.TestCase):
    def test_ranges_of_every_value(self) -> None:
        """RF-013-18, RF-013-19: la altura es de 0 (excluido) a 100 m, la cara de 0 a 90 °
        (ambos excluidos), la berma de 0 a 100 m, el ancla de -1 000 a 10 000 m y el factor de
        malla de 0 (excluido) a 1: los extremos incluidos valen y lo de fuera se rechaza
        (``des.profile_value_range``), nombrando el perfil, la clave del campo y el valor."""
        valid = (("height_m", 100.0), ("height_m", 0.5), ("face_deg", 89.999), ("face_deg", 1e-6),
                 ("berm_m", 0.0), ("berm_m", 100.0), ("anchor_m", -1000.0),
                 ("anchor_m", 10000.0), ("mesh_factor", 1.0), ("mesh_factor", 0.5))
        for field, value in valid:
            with self.subTest(field=field, value=value):
                self.assertEqual(getattr(profile_of("EXPL_10_60_6", **{field: value}), field),
                                 value)
        invalid = (("height_m", 0.0), ("height_m", -5.0), ("height_m", 100.5),
                   ("face_deg", 0.0), ("face_deg", 90.0), ("face_deg", 120.0),
                   ("berm_m", -0.001), ("berm_m", 100.001), ("anchor_m", -1000.5),
                   ("anchor_m", 10000.5), ("mesh_factor", 0.0), ("mesh_factor", 1.0001),
                   ("height_m", math.nan), ("berm_m", math.inf), ("anchor_m", -math.inf))
        for field, value in invalid:
            with self.subTest(field=field, value=value):
                with self.assertRaises(messages.DesignError) as caught:
                    profile_of("EXPL_10_60_6", **{field: value})
                error = caught.exception
                self.assertEqual(error.code, "des.profile_value_range")
                self.assertEqual(error.field, f"des.bench.expl_10_60_6.{field}")
                self.assertEqual(error.obj, "Perfil de banco «EXPL_10_60_6»")
                self.assertIn("«EXPL_10_60_6»", error.text)
                self.assertIn(f"des.bench.expl_10_60_6.{field}", error.text)
                if isinstance(value, float) and math.isfinite(value):
                    self.assertEqual(error.value, value)

    def test_a_value_without_value_is_rejected(self) -> None:
        """RF-013-19 (D-7): una altura, una cara, una berma, un ancla o un factor de malla
        «sin valor» (``None``) se rechaza con ``des.profile_value_missing``, nombrando el perfil
        y el campo, y diciendo dónde se declara; nada se calcula con él."""
        for field in ("height_m", "face_deg", "berm_m", "anchor_m", "mesh_factor"):
            with self.subTest(field=field):
                with self.assertRaises(messages.DesignError) as caught:
                    profile_of("REST_5_35_6", **{field: None})
                error = caught.exception
                self.assertEqual(error.code, "des.profile_value_missing")
                self.assertEqual(error.field, f"des.bench.rest_5_35_6.{field}")
                self.assertIsNone(error.value)
                self.assertIn("«REST_5_35_6»", error.text)
                self.assertIn("Perfiles de banco", error.text)

    def test_a_profile_without_name_is_rejected(self) -> None:
        """RF-013-19: un perfil con el nombre vacío, de espacios o que no es un texto se
        rechaza con ``des.profile_name_missing`` (nombrándolo por su código)."""
        for name in ("", "   ", "\t"):
            with self.subTest(name=name):
                with self.assertRaises(messages.DesignError) as caught:
                    profile_of("EXPL_10_60_6", name=name)
                error = caught.exception
                self.assertEqual(error.code, "des.profile_name_missing")
                self.assertEqual(error.field, "name")
                self.assertIn("«expl_10_60_6»", error.text)
        with self.assertRaises(TypeError):
            profile_of("EXPL_10_60_6", name=None)

    def test_the_code_is_an_ascii_identifier(self) -> None:
        """RF-013-18 (D-17): el código es ``[a-z][a-z0-9_]*`` (ASCII, en minúsculas); otro es
        un error del programa (``ValueError``), igual que un valor que no es un número real
        (``TypeError``: un booleano, un texto)."""
        for code in ("", "Expl", "1expl", "expl 10", "expl.10", "exploración", "expl-10"):
            with self.subTest(code=code), self.assertRaises(ValueError):
                profile_of("EXPL_10_60_6", code=code)
        for field, value in (("height_m", True), ("height_m", "10"), ("face_deg", [60.0]),
                             ("berm_m", b"6")):
            with self.subTest(field=field, value=value), self.assertRaises(TypeError):
                profile_of("EXPL_10_60_6", **{field: value})
        with self.assertRaises(TypeError):
            profile_of("EXPL_10_60_6", code=None)


class RepeatedNamesTest(unittest.TestCase):
    def test_a_repeated_name_is_rejected(self) -> None:
        """RF-013-19: un perfil que repite el nombre de otro (también en mayúsculas distintas o
        con espacios en los bordes: el código sale del nombre) se rechaza con
        ``des.profile_name_repeated``, nombrando los dos; perfiles con nombres distintos valen."""
        first = profile_of("EXPL_10_60_6")
        second = profile_of("REST_5_35_6")
        third = profile_of("DESD_10_45_6")
        model.check_profiles([first, second, third])
        model.check_profiles([])
        for repeated in (profile_of("EXPL_10_60_6", code="expl_otra"),
                         profile_of("EXPL_10_60_6", code="otra", name="expl_10_60_6"),
                         profile_of("EXPL_10_60_6", code="otra", name=" EXPL_10_60_6 ")):
            with self.subTest(name=repeated.name):
                with self.assertRaises(messages.DesignError) as caught:
                    model.check_profiles([first, second, repeated])
                error = caught.exception
                self.assertEqual(error.code, "des.profile_name_repeated")
                self.assertEqual(error.field, "name")
                self.assertIn(repeated.code, error.text)
                self.assertIn("expl_10_60_6", error.text)

    def test_a_repeated_code_is_a_program_error(self) -> None:
        """RF-013-18 (D-17): dos perfiles con el mismo código no son un error del usuario sino
        del programa (el sistema fija el código al crear el perfil y es único): ``ValueError``."""
        with self.assertRaises(ValueError):
            model.check_profiles([profile_of("EXPL_10_60_6"),
                                  profile_of("EXPL_10_60_6", name="Otro nombre")])


if __name__ == "__main__":
    unittest.main()
