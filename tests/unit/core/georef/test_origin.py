# SPDX-License-Identifier: GPL-3.0-or-later
"""GeoOrigin, ventana de trabajo y unidad de alineación (spec 002, T03; RF-002-24;
ADR-0005, ADR-0014).

La ventana tecleada se amplía hacia fuera a múltiplos de la unidad de alineación del paso
(el menor entero de metros múltiplo del paso) y el GeoOrigin es el centro de la ventana
**ya ampliada** redondeado a 100 m, con los empates hacia arriba (``round()`` de Python
redondea al par: 700 250 daría 700 200; docs/trampas.md §1).
"""

import unittest

from tests.support.core_fixtures import EXPECTED_ORIGIN, SYNTHETIC_WINDOW
from tests.support.package import import_geoblender

georef = import_geoblender("core.georef")
errors = import_geoblender("core.errors")
Window = georef.Window
GeoOrigin = georef.GeoOrigin


def _centred(cx: float, cy: float, half: float = 100.0) -> object:
    """Una ventana (no alineada) de centro (cx, cy)."""
    return Window(cx - half, cy - half, cx + half, cy + half)


class AlignmentUnitTest(unittest.TestCase):
    def test_alignment_unit(self) -> None:
        """RF-002-24: el menor entero de metros múltiplo del paso: 0,5 y 1 → 1; 1,5 → 3;
        2 → 2; 2,5 → 5; 4,5 → 9; 5 → 5."""
        expected = {0.5: 1, 1.0: 1, 1.5: 3, 2.0: 2, 2.5: 5, 3.0: 3, 3.5: 7, 4.5: 9, 5.0: 5}
        for step, unit in expected.items():
            with self.subTest(step=step):
                self.assertEqual(georef.alignment_unit(step), unit)
                self.assertIsInstance(georef.alignment_unit(step), int)

    def test_invalid_steps(self) -> None:
        """RF-002-03: un paso fuera de 0,5–5 m o que no es múltiplo de 0,5 se rechaza
        con el campo y el valor."""
        for step in (0.3, 0.0, -1.0, 0.75, 5.5, 6.0, float("nan"), float("inf"), True, "1"):
            with self.subTest(step=step):
                with self.assertRaises(errors.ValidationError) as caught:
                    georef.alignment_unit(step)
                self.assertEqual(caught.exception.code, "core.grid_step_invalid")
                self.assertEqual(caught.exception.field, "paso de rejilla")


class AlignWindowTest(unittest.TestCase):
    def test_align_step_one(self) -> None:
        """RF-002-24: (700 000,4; 4 399 000,6; 701 000,2; 4 400 000,9) con paso 1 →
        (700 000; 4 399 000; 701 001; 4 400 001), hacia fuera."""
        window = Window(700_000.4, 4_399_000.6, 701_000.2, 4_400_000.9)
        self.assertEqual(
            georef.align_window(window, 1.0),
            Window(700_000.0, 4_399_000.0, 701_001.0, 4_400_001.0),
        )

    def test_already_aligned_is_unchanged(self) -> None:
        """RF-002-24: una ventana ya alineada no cambia (alinear dos veces es lo mismo
        que una)."""
        window = Window(699_999.0, 4_399_998.0, 700_101.0, 4_400_100.0)
        self.assertEqual(georef.align_window(window, 1.5), window)
        once = georef.align_window(Window(700_000.4, 4_399_000.6, 701_000.2, 4_400_000.9), 2.5)
        self.assertEqual(georef.align_window(once, 2.5), once)

    def test_even_and_multiple_of_three(self) -> None:
        """RF-002-24 (ADR-0014): con paso 2 m las esquinas son pares; con 1,5 m, múltiplos
        de 3; con 2,5 m, de 5; siempre contienen la ventana tecleada."""
        typed = Window(700_000.4, 4_399_000.6, 701_000.2, 4_400_000.9)
        for step, unit in ((2.0, 2), (1.5, 3), (2.5, 5), (0.5, 1)):
            with self.subTest(step=step):
                aligned = georef.align_window(typed, step)
                for corner in (aligned.xmin, aligned.ymin, aligned.xmax, aligned.ymax):
                    self.assertEqual(corner % unit, 0.0)
                    self.assertEqual(corner, int(corner))
                self.assertLessEqual(aligned.xmin, typed.xmin)
                self.assertLessEqual(aligned.ymin, typed.ymin)
                self.assertGreaterEqual(aligned.xmax, typed.xmax)
                self.assertGreaterEqual(aligned.ymax, typed.ymax)
                self.assertLess(typed.xmin - aligned.xmin, unit)
                self.assertLess(aligned.xmax - typed.xmax, unit)


class ChooseOriginTest(unittest.TestCase):
    def test_reference_centre(self) -> None:
        """RF-002-24 (ADR-0005): centro (700 234,7; 4 400 281,2) → (700 200; 4 400 300)."""
        origin = georef.choose_origin(_centred(700_234.7, 4_400_281.2))
        self.assertEqual(origin, GeoOrigin(700_200, 4_400_300, 0))

    def test_ties_go_up(self) -> None:
        """RF-002-24: centro x = 700 250 → 700 300 e y = …350 → …400 (empate hacia
        arriba, también en negativo: −250 → −200)."""
        aligned = Window(700_200.0, 4_400_300.0, 700_300.0, 4_400_400.0)
        self.assertEqual(georef.choose_origin(aligned), GeoOrigin(700_300, 4_400_400))
        negative = Window(-300.0, -300.0, -200.0, -200.0)
        self.assertEqual(georef.choose_origin(negative), GeoOrigin(-200, -200))

    def test_centre_of_widened_window(self) -> None:
        """RF-002-24: X de 700 000,0 a 700 099,6 con paso 1 → ventana 700 000–700 100 y
        X0 = 700 100 (el centro de la ventana ampliada, 700 050, sube)."""
        typed = Window(700_000.0, 4_400_000.0, 700_099.6, 4_400_100.0)
        aligned = georef.align_window(typed, 1.0)
        self.assertEqual((aligned.xmin, aligned.xmax), (700_000.0, 700_100.0))
        self.assertEqual(georef.choose_origin(aligned).x0, 700_100)

    def test_m1_and_synthetic_windows(self) -> None:
        """RF-002-24: la ventana de M1 da (700 500; 4 399 500; 0) y la sintética de las
        pruebas, (700 000; 4 400 000; 0); Z0 es el que se indica."""
        m1 = georef.align_window(Window(700_000.4, 4_399_000.6, 701_000.2, 4_400_000.9), 1)
        self.assertEqual(georef.choose_origin(m1), GeoOrigin(700_500, 4_399_500, 0))
        synthetic = georef.align_window(Window(*SYNTHETIC_WINDOW), 1.0)
        origin = georef.choose_origin(synthetic)
        self.assertEqual((origin.x0, origin.y0, origin.z0), EXPECTED_ORIGIN)
        self.assertEqual(georef.choose_origin(synthetic, z0=-180).z0, -180)


class GeoOriginTest(unittest.TestCase):
    def test_valid(self) -> None:
        """RF-002-24: X0 e Y0 múltiplos de 100 y Z0 entero; Z0 = 0 por defecto."""
        origin = GeoOrigin(700_200, 4_400_300)
        self.assertEqual((origin.x0, origin.y0, origin.z0), (700_200, 4_400_300, 0))
        self.assertEqual(GeoOrigin(0, 0, -10_000).z0, -10_000)
        self.assertEqual(GeoOrigin(0, 0, 10_000).z0, 10_000)

    def test_invalid(self) -> None:
        """RF-002-03, RF-002-24: X0 = 700 250, Z0 = 20 000, decimales, textos y valores
        que no caben en un IntProperty se rechazan con el campo y el valor."""
        cases = {
            "X0 no múltiplo de 100": ((700_250, 4_400_000, 0), "X0"),
            "Y0 no múltiplo de 100": ((700_200, 4_400_050, 0), "Y0"),
            "Z0 = 20 000": ((700_200, 4_400_000, 20_000), "Z0"),
            "Z0 = −10 001": ((700_200, 4_400_000, -10_001), "Z0"),
            "X0 decimal": ((700_200.0, 4_400_000, 0), "X0"),
            "Z0 decimal": ((700_200, 4_400_000, 0.5), "Z0"),
            "Y0 lógico": ((700_200, True, 0), "Y0"),
            "X0 texto": (("700200", 4_400_000, 0), "X0"),
            "X0 fuera de IntProperty": ((2**31 + 52, 4_400_000, 0), "X0"),
        }
        for label, (values, field) in cases.items():
            with self.subTest(label):
                with self.assertRaises(errors.ValidationError) as caught:
                    GeoOrigin(*values)
                self.assertEqual(caught.exception.field, field)
                self.assertIn(field, str(caught.exception))


class WindowTest(unittest.TestCase):
    def test_empty_or_inverted(self) -> None:
        """RF-002-03: una ventana vacía o con los ejes invertidos (mínimo ≥ máximo) se
        rechaza con el campo y el valor."""
        cases = {
            "X invertida": (701_000.0, 4_399_000.0, 700_000.0, 4_400_000.0),
            "Y invertida": (700_000.0, 4_400_000.0, 701_000.0, 4_399_000.0),
            "vacía": (700_000.0, 4_399_000.0, 700_000.0, 4_400_000.0),
            "no finita": (700_000.0, 4_399_000.0, float("inf"), 4_400_000.0),
            "texto": ("700000", 4_399_000.0, 701_000.0, 4_400_000.0),
        }
        for label, values in cases.items():
            with self.subTest(label):
                with self.assertRaises(errors.ValidationError) as caught:
                    Window(*values)
                self.assertEqual(caught.exception.obj, "Ventana de trabajo")

    def test_values_are_float64(self) -> None:
        """RF-002-24: la ventana guarda floats de Python (float64), también si se da con
        enteros, y tiene ancho, alto y centro."""
        window = Window(700_000, 4_399_000, 701_000, 4_400_000)
        self.assertIsInstance(window.xmin, float)
        self.assertEqual((window.width, window.height), (1_000.0, 1_000.0))
        self.assertEqual(window.centre, (700_500.0, 4_399_500.0))


if __name__ == "__main__":
    unittest.main()
