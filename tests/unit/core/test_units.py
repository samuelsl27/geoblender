# SPDX-License-Identifier: GPL-3.0-or-later
"""Catálogo de unidades de Geoblender (spec 008, T02; RF-008-03, RF-008-30; plan 008 §5.3.1
y D11).

Cada parámetro y cada cifra lleva una unidad **del catálogo**: un código ASCII estable
(``m2``, ``t/m3``, ``-``) que es lo que se guarda, y un símbolo en español para leerla
(m², t/m³, —). Un valor tecleado con una unidad convertible a la declarada (% y fracción,
t y kt) se convierte exactamente; entre magnitudes distintas no hay conversión. NaN e
infinito tecleados nunca son un valor. La spec 011 (T03; RF-011-18) añade las relaciones
estéril/útil en m³/m³ y en t/t, que no se convierten entre sí ni con «%».
"""

import math
import random
import unittest
from fractions import Fraction

from tests.support.package import import_geoblender

units = import_geoblender("core.units")

# El catálogo mínimo de la tarea, con el factor exacto de cada unidad respecto a otra de su
# misma magnitud, escrito aquí a mano (no se lee del módulo): (código, símbolo, magnitud,
# factor respecto a la unidad de referencia de la prueba).
REQUIRED = (
    ("m", "m", "longitud", Fraction(1)),
    ("km", "km", "longitud", Fraction(1000)),
    ("m2", "m²", "superficie", Fraction(1)),
    ("ha", "ha", "superficie", Fraction(10_000)),
    ("km2", "km²", "superficie", Fraction(1_000_000)),
    ("m3", "m³", "volumen", Fraction(1)),
    ("hm3", "hm³", "volumen", Fraction(1_000_000)),
    ("t", "t", "masa", Fraction(1)),
    ("kt", "kt", "masa", Fraction(1000)),
    ("Mt", "Mt", "masa", Fraction(1_000_000)),
    ("kg", "kg", "masa", Fraction(1, 1000)),
    ("t/m3", "t/m³", "densidad", Fraction(1)),
    ("kg/m3", "kg/m³", "densidad", Fraction(1, 1000)),
    ("-", "—", "proporción", Fraction(1)),
    ("%", "%", "proporción", Fraction(1, 100)),
    ("g/t", "g/t", "proporción", Fraction(1, 1_000_000)),
    ("ppm", "ppm", "proporción", Fraction(1, 1_000_000)),
    ("ppb", "ppb", "proporción", Fraction(1, 1_000_000_000)),
    ("deg", "°", "ángulo", Fraction(1)),
    ("deg/30m", "°/30 m", "cambio de dirección", Fraction(1)),
    ("s", "s", "tiempo", Fraction(1)),
    ("min", "min", "tiempo", Fraction(60)),
    ("h", "h", "tiempo", Fraction(3600)),
    ("d", "d", "tiempo", Fraction(86_400)),
    ("yr", "año", "años", Fraction(1)),
    ("t/yr", "t/año", "masa por año", Fraction(1)),
    ("m3/yr", "m³/año", "volumen por año", Fraction(1)),
    ("B", "B", "datos", Fraction(1)),
    ("MB", "MB", "datos", Fraction(10**6)),
    ("GB", "GB", "datos", Fraction(10**9)),
)


class CatalogTest(unittest.TestCase):
    def test_required_units_and_spanish_symbols(self) -> None:
        """RF-008-30: el catálogo tiene al menos las unidades de la tarea, con el código
        ASCII que se guarda y el símbolo en español que se muestra: «m³», «t/m³», «°»,
        «t/año» y «—» para lo adimensional."""
        for code, shown, _dimension, _factor in REQUIRED:
            with self.subTest(unidad=code):
                self.assertIn(code, units.UNITS)
                unit = units.UNITS[code]
                self.assertEqual(unit.code, code)
                self.assertTrue(code.isascii())
                self.assertEqual(unit.symbol_es, shown)
                self.assertEqual(units.symbol(code), shown)
        self.assertEqual(units.symbol("m3"), "m³")
        self.assertEqual(units.symbol("-"), "—")
        self.assertEqual(units.DIMENSIONLESS, "-")

    def test_same_magnitude_as_the_table(self) -> None:
        """RF-008-03: dos unidades del catálogo son convertibles si y solo si son de la misma
        magnitud de la tabla (% y fracción sí; masa y volumen no), y la razón entre sus
        factores es la de la tabla, exacta (``Fraction``); MB = 10⁶ B, no 2²⁰."""
        for code_a, _, dim_a, factor_a in REQUIRED:
            for code_b, _, dim_b, factor_b in REQUIRED:
                unit_a, unit_b = units.UNITS[code_a], units.UNITS[code_b]
                same = unit_a.dimension == unit_b.dimension
                with self.subTest(de=code_a, a=code_b):
                    self.assertEqual(same, dim_a == dim_b)
                    if same:
                        self.assertIsInstance(unit_a.factor, Fraction)
                        self.assertEqual(unit_a.factor / unit_b.factor, factor_a / factor_b)
        self.assertEqual(units.UNITS["MB"].factor / units.UNITS["B"].factor, 10**6)

    def test_symbol_of_unknown_unit(self) -> None:
        """RF-008-30: una unidad fuera del catálogo no tiene símbolo: ``ValueError`` que la
        nombra (una cifra sin unidad del catálogo no se registra)."""
        for code in ("furlong", "", "m^3", "M3", "Ha"):
            with self.subTest(unidad=code):
                with self.assertRaises(ValueError) as caught:
                    units.symbol(code)
                self.assertEqual(caught.exception.code, "core.unit_unknown")
                self.assertIn(f"«{code}»", str(caught.exception))


class ParseQuantityTest(unittest.TestCase):
    def test_number_and_optional_unit(self) -> None:
        """RF-008-03: «35 %» → (35, «%»); coma o punto decimal, espacios de miles, con o sin
        espacio antes de la unidad, y la unidad por su código o por su símbolo (también «º»
        del teclado español y «años»); sin unidad, ``None``."""
        cases = {
            "35 %": (35.0, "%"),
            "35%": (35.0, "%"),
            "1,23": (1.23, None),
            "1.23": (1.23, None),
            "  -12,5  ": (-12.5, None),
            "2,65 t/m3": (2.65, "t/m3"),
            "2,65 t/m³": (2.65, "t/m3"),
            "1 500 m³": (1500.0, "m3"),
            "1 500 m3": (1500.0, "m3"),
            "1500m3": (1500.0, "m3"),
            "12 ha": (12.0, "ha"),
            "13,43\u00a0ha": (13.43, "ha"),
            "30°": (30.0, "deg"),
            "30º": (30.0, "deg"),
            "45 deg": (45.0, "deg"),
            "0,35 -": (0.35, "-"),
            "0,35 —": (0.35, "-"),
            "-5 m": (-5.0, "m"),
            "5 años": (5.0, "yr"),
            "1 año": (1.0, "yr"),
            "2 Mt": (2.0, "Mt"),
            "120 000 t/año": (120000.0, "t/yr"),
            "200 MB": (200.0, "MB"),
            "0,5 g/t": (0.5, "g/t"),
        }
        for text, expected in cases.items():
            with self.subTest(texto=text):
                value, unit = units.parse_quantity(text)
                self.assertIs(type(value), float)
                self.assertEqual((value, unit), expected)

    def test_point_only_when_asked(self) -> None:
        """RF-008-03: con ``decimal="."`` solo vale el punto (la coma sería de miles en la
        interfaz en inglés); otro separador es un error del programa."""
        self.assertEqual(units.parse_quantity("1.5 m", decimal="."), (1.5, "m"))
        with self.assertRaises(ValueError) as caught:
            units.parse_quantity("1,5 m", decimal=".")
        self.assertEqual(caught.exception.code, "core.quantity_not_number")
        with self.assertRaises(ValueError):
            units.parse_quantity("1,5", decimal=";")

    def test_nan_and_infinity_rejected(self) -> None:
        """RF-008-03, RF-008-30: «NaN» e «inf» tecleados (con o sin unidad o signo) y un
        número que no cabe en un float64 se rechazan: nunca son un valor."""
        overflow = "1" + "0" * 400
        for text in ("NaN", "nan", "inf", "-inf", "+inf", "Infinity", "nan %", "inf m",
                     overflow, overflow + " m"):
            with self.subTest(texto=text[:20]):
                with self.assertRaises(ValueError) as caught:
                    units.parse_quantity(text)
                self.assertIn(caught.exception.code,
                              ("core.quantity_not_number", "core.quantity_not_finite"))

    def test_rejected_texts(self) -> None:
        """RF-008-03: vacío, texto, coma y punto a la vez o dos separadores no son un
        número; una unidad fuera del catálogo se nombra en el rechazo."""
        rejected = {
            "": "core.quantity_missing",
            "   ": "core.quantity_missing",
            "abc": "core.quantity_not_number",
            "%": "core.quantity_not_number",
            "700.000,4 m": "core.quantity_not_number",
            "1,2,3": "core.quantity_not_number",
            "--5": "core.quantity_not_number",
            "35 kg/ha": "core.unit_unknown",
            "35 Ha": "core.unit_unknown",
            "12 m^2": "core.unit_unknown",
            "1e3": "core.unit_unknown",
        }
        for text, code in rejected.items():
            with self.subTest(texto=text):
                with self.assertRaises(ValueError) as caught:
                    units.parse_quantity(text)
                self.assertEqual(caught.exception.code, code)
        with self.assertRaises(ValueError) as caught:
            units.parse_quantity("35 kg/ha")
        self.assertIn("«kg/ha»", str(caught.exception))
        with self.assertRaises(TypeError):
            units.parse_quantity(35)


class ConvertTest(unittest.TestCase):
    def test_percent_and_fraction(self) -> None:
        """RF-008-03: «35 %» en un parámetro declarado en fracción da 0,35, y al revés."""
        value, unit = units.parse_quantity("35 %")
        self.assertEqual(units.convert(value, unit, "-"), 0.35)
        self.assertEqual(units.convert(35, "%", "-"), 0.35)
        self.assertEqual(units.convert(0.35, "-", "%"), 35.0)
        self.assertEqual(units.convert(1, "%", "g/t"), 10_000.0)
        self.assertEqual(units.convert(5, "ppm", "g/t"), 5.0)

    def test_grades_with_ppb(self) -> None:
        """RF-005-29 (spec 005, T04; D-18 del plan 005): las leyes en g/t, ppm, ppb y % son
        una misma proporción con factores exactos (1 g/t = 1 ppm = 1000 ppb = 10⁻⁴ %); el
        cambio de dirección entre estaciones (DH-W04) va en «°/30 m», una magnitud propia que
        no se convierte a grados."""
        cases = (
            (4860, "ppb", "g/t", 4.86),
            (350, "ppb", "ppm", 0.35),
            (1, "ppm", "ppb", 1000.0),
            (1, "%", "ppb", 10_000_000.0),
            (25_000_000, "ppb", "%", 2.5),
            (1050, "ppm", "%", 0.105),
            (0.35, "g/t", "ppb", 350.0),
            (2.9, "g/t", "ppm", 2.9),
        )
        for value, source, target, expected in cases:
            with self.subTest(valor=value, de=source, a=target):
                self.assertEqual(units.convert(value, source, target), expected)
        self.assertEqual(units.parse_quantity("3 °/30 m"), (3.0, "deg/30m"))
        self.assertEqual(units.parse_quantity("2,5 deg/30m"), (2.5, "deg/30m"))
        self.assertEqual(units.parse_quantity("120 ppb"), (120.0, "ppb"))
        with self.assertRaises(ValueError) as caught:
            units.convert(3.0, "deg/30m", "deg")
        self.assertEqual(caught.exception.code, "core.unit_not_convertible")

    def test_exact_conversions(self) -> None:
        """RF-008-03: t ↔ kt, m² ↔ ha y B ↔ MB (10⁶) exactos: el resultado es el número
        decimal que se espera, sin el error de un factor en coma flotante."""
        cases = (
            (1500, "t", "kt", 1.5),
            (1, "t", "kt", 0.001),
            (0.001, "kt", "t", 1.0),
            (0.3, "kt", "t", 300.0),
            (2.5, "Mt", "kt", 2500.0),
            (2650, "kg/m3", "t/m3", 2.65),
            (120_000, "m2", "ha", 12.0),
            (14_300, "m2", "ha", 1.43),
            (13.43, "ha", "m2", 134_300.0),
            (1, "km2", "ha", 100.0),
            (1, "MB", "B", 1_000_000.0),
            (1_500_000, "B", "MB", 1.5),
            (200, "MB", "B", 200_000_000.0),
            (1, "GB", "MB", 1000.0),
            (1, "d", "h", 24.0),
            (90, "min", "h", 1.5),
            (1, "hm3", "m3", 1_000_000.0),
            (2.5, "km", "m", 2500.0),
        )
        for value, source, target, expected in cases:
            with self.subTest(valor=value, de=source, a=target):
                result = units.convert(value, source, target)
                self.assertIs(type(result), float)
                self.assertEqual(result, expected)

    def test_correctly_rounded(self) -> None:
        """RF-008-03: para cualquier valor, la conversión es la exacta redondeada una sola
        vez a float64 (la de la tabla con ``Fraction``), y la misma unidad no cambia el
        valor."""
        rng = random.Random(8002)
        by_dimension: dict[str, list[tuple[str, Fraction]]] = {}
        for code, _, dimension, factor in REQUIRED:
            by_dimension.setdefault(dimension, []).append((code, factor))
        pairs = [(a, b) for group in by_dimension.values() for a in group for b in group]
        for _ in range(400):
            (source, f_source), (target, f_target) = rng.choice(pairs)
            value = rng.uniform(-1e7, 1e7) * 10.0 ** rng.randint(-6, 3)
            expected = float(Fraction(value) * f_source / f_target)
            self.assertEqual(units.convert(value, source, target), expected,
                             (value, source, target))
        self.assertEqual(units.convert(0.1, "m", "m"), 0.1)
        self.assertIs(type(units.convert(3, "m", "m")), float)

    def test_different_dimensions(self) -> None:
        """RF-008-03: entre magnitudes distintas no hay conversión: ``ValueError`` que nombra
        las dos unidades (por su símbolo) y lo que mide cada una; un año tampoco se convierte
        a días (dependería del calendario de trabajo)."""
        for source, target in (("t", "m3"), ("%", "m"), ("B", "s"), ("t/m3", "t"),
                               ("yr", "d"), ("t/yr", "t"), ("deg", "-")):
            with self.subTest(de=source, a=target):
                with self.assertRaises(ValueError) as caught:
                    units.convert(1.0, source, target)
                error = caught.exception
                self.assertEqual(error.code, "core.unit_not_convertible")
                self.assertEqual((error.from_unit, error.to_unit), (source, target))
                self.assertIn(f"«{units.symbol(source)}»", str(error))
                self.assertIn(f"«{units.symbol(target)}»", str(error))
        with self.assertRaises(ValueError) as caught:
            units.convert(1.0, "t", "m3")
        self.assertIn("masa", str(caught.exception))
        self.assertIn("volumen", str(caught.exception))

    def test_volume_and_mass_ratios(self) -> None:
        """RF-011-18 (spec 011, T03; plan 011 §5.6): la relación estéril/útil en m³/m³ (in
        situ) y en t/t son unidades del catálogo (``m3/m3``, «m³/m³», una relación entre
        volúmenes; ``t/t``, «t/t», una relación entre masas); cada una solo se convierte a sí
        misma: ni entre ellas ni con ``%`` o ``-`` (una relación de 2,5 m³/m³ no es un 250 %
        ni 2,5 t/t), y el rechazo nombra las dos unidades y lo que mide cada una."""
        expected = {"m3/m3": ("m³/m³", "volúmenes"), "t/t": ("t/t", "masas")}
        for code, (shown, measured) in expected.items():
            with self.subTest(unidad=code):
                unit = units.get_unit(code)
                self.assertEqual((unit.code, unit.symbol_es, unit.factor),
                                 (code, shown, Fraction(1)))
                self.assertEqual(units.symbol(code), shown)
                self.assertEqual(units.convert(2.5, code, code), 2.5)
                self.assertEqual(units.parse_quantity(f"2,5 {shown}"), (2.5, code))
                self.assertEqual(units.parse_quantity(f"2,5 {code}"), (2.5, code))
                others = [other for other in units.UNITS if other != code]
                self.assertEqual([other for other in others
                                  if units.UNITS[other].dimension == unit.dimension], [])
                with self.assertRaises(ValueError) as caught:
                    units.convert(2.5, code, "-")
                self.assertIn(measured, str(caught.exception))
        self.assertNotEqual(units.UNITS["m3/m3"].dimension, units.UNITS["t/t"].dimension)
        for source, target in (("m3/m3", "t/t"), ("t/t", "m3/m3"), ("m3/m3", "%"),
                               ("%", "m3/m3"), ("t/t", "%"), ("%", "t/t"), ("t/t", "-"),
                               ("-", "m3/m3"), ("m3/m3", "m3"), ("t/t", "t")):
            with self.subTest(de=source, a=target):
                with self.assertRaises(ValueError) as caught:
                    units.convert(1.0, source, target)
                error = caught.exception
                self.assertEqual(error.code, "core.unit_not_convertible")
                self.assertEqual((error.from_unit, error.to_unit), (source, target))
                self.assertIn(f"«{units.symbol(source)}»", str(error))
                self.assertIn(f"«{units.symbol(target)}»", str(error))

    def test_unknown_unit_and_non_finite_value(self) -> None:
        """RF-008-03, RF-008-30: una unidad fuera del catálogo o un valor NaN o infinito no
        se convierten; un sí/no o un texto no son un número."""
        with self.assertRaises(ValueError) as caught:
            units.convert(1.0, "m", "furlong")
        self.assertEqual(caught.exception.code, "core.unit_unknown")
        self.assertIn("«furlong»", str(caught.exception))
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(valor=value):
                with self.assertRaises(ValueError) as caught:
                    units.convert(value, "t", "kt")
                self.assertEqual(caught.exception.code, "core.quantity_not_finite")
        for value in (True, "35", None):
            with self.subTest(valor=value):
                with self.assertRaises(TypeError):
                    units.convert(value, "t", "kt")


if __name__ == "__main__":
    unittest.main()
