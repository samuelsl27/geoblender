# SPDX-License-Identifier: GPL-3.0-or-later
"""Rodajas de la cubicación por bancos (spec 011, T05; HU-011-2; RF-011-09; plan 011 A3, A4 y
D-22; RF-008-03).

``reserves.slices`` describe cómo se parte en rodajas una cubicación: con una **altura de
banco y una cota de anclaje** (las cotas son ``anclaje + k·altura``, también con el anclaje
fuera de lo cubicado) o con una **lista creciente de cotas**, que se usa tal cual.

- ``Slices``: el reparto, comprobado al crearlo (la altura en su rango, (0; 100] m, el de
  ``res.bench_height_m``; la lista, creciente y con dos cotas al menos).
- ``slices_from_text``: lo que se teclea en el diálogo (coma o punto decimal y, si se quiere,
  la unidad), con el rechazo de cada valor con su rango (``ResError``).
- ``bounds``: las cotas ``z_0 < z_1 < …`` que cubren lo cubicado, las mínimas.
- ``index``: la rodaja de cada cota, semiabierta ``[z_k, z_k+1)``: una cota justo en un
  límite va a la rodaja de arriba (D-22), y el índice siempre casa con las cotas de
  ``bounds``, también con alturas y anclajes que no son exactos en binario.
"""

from __future__ import annotations

import unittest

import numpy as np

from tests.support.package import import_geoblender

slices = import_geoblender("reserves.slices")
messages = import_geoblender("reserves.messages")
params = import_geoblender("reserves.params")

Slices = slices.Slices
ResError = messages.ResError

HEIGHT_LABEL = "Altura de banco"
ANCHOR_LABEL = "Cota de anclaje"
LEVELS_LABEL = "Lista de cotas de los bancos"


def _steps(first: float, step: float, count: int) -> list[float]:
    """``count`` cotas desde ``first`` cada ``step`` (valores exactos en binario)."""
    return [first + step * number for number in range(count)]


class BoundsTest(unittest.TestCase):
    def test_height_and_anchor_cover_the_range_in_multiples_of_the_anchor(self) -> None:
        """RF-011-09 (§8 de la spec, «cota de anclaje fuera del rango cubicado»): con altura y
        anclaje, las cotas son ``anclaje + k·altura`` y cubren lo cubicado, las mínimas (la
        primera no pasa de la cota mínima y la última no se queda por debajo de la máxima);
        con el anclaje por encima o por debajo de lo cubicado salen las mismas cotas."""
        cases = (
            # altura, anclaje, mínima, máxima, cotas esperadas
            (10.0, 0.0, 600.0, 650.0, _steps(600.0, 10.0, 6)),      # la pirámide de CE-011-01
            (10.0, 0.0, 603.2, 647.9, _steps(600.0, 10.0, 6)),
            (10.0, 2.5, 600.0, 650.0, _steps(592.5, 10.0, 7)),
            (10.0, 1002.5, 600.0, 650.0, _steps(592.5, 10.0, 7)),   # anclaje por encima
            (10.0, -97.5, 600.0, 650.0, _steps(592.5, 10.0, 7)),    # anclaje por debajo
            (7.5, 1.0, 600.0, 650.0, _steps(593.5, 7.5, 9)),
            (100.0, 0.0, -12.5, 30.0, [-100.0, 0.0, 100.0]),         # cotas negativas
        )
        for height, anchor, low, high, expected in cases:
            with self.subTest(height=height, anchor=anchor, low=low, high=high):
                levels = slices.bounds(Slices(height, anchor, None), low, high)
                self.assertEqual(levels.dtype, np.float64)
                self.assertEqual(levels.tolist(), expected)
                self.assertLessEqual(levels[0], low)
                self.assertGreater(levels[1], low)
                self.assertGreaterEqual(levels[-1], high)
                self.assertLess(levels[-2], high)

    def test_a_top_exactly_on_a_level_adds_no_empty_slice(self) -> None:
        """RF-011-09, D-22: la cota máxima justo en un límite cierra la última rodaja (no
        añade otra vacía encima: la pirámide de 600 a 650 m da sus cinco rodajas de 10 m);
        una cubicación plana, en un límite o no, da una sola rodaja."""
        ten = Slices(10.0, 0.0, None)
        self.assertEqual(slices.bounds(ten, 600.0, 650.0).tolist(), _steps(600.0, 10.0, 6))
        self.assertEqual(slices.bounds(ten, 620.0, 620.0).tolist(), [620.0, 630.0])
        self.assertEqual(slices.bounds(ten, 623.0, 623.0).tolist(), [620.0, 630.0])
        self.assertEqual(slices.bounds(ten, 600.0, 600.000001).tolist(), [600.0, 610.0])
        self.assertEqual(slices.bounds(ten, 599.999999, 610.0).tolist(),
                         [590.0, 600.0, 610.0])

    def test_a_list_is_used_as_is(self) -> None:
        """RF-011-09: una lista creciente de cotas se usa tal cual, cubra o no lo cubicado,
        y lo que devuelve ``bounds`` es una copia (cambiarla no cambia el reparto)."""
        listed = Slices(None, None, (600.0, 615.5, 650.0))
        for low, high in ((500.0, 700.0), (620.0, 621.0), (600.0, 650.0)):
            with self.subTest(low=low, high=high):
                levels = slices.bounds(listed, low, high)
                self.assertEqual(levels.dtype, np.float64)
                self.assertEqual(levels.tolist(), [600.0, 615.5, 650.0])
        levels[0] = 0.0
        self.assertEqual(listed.levels, (600.0, 615.5, 650.0))

    def test_an_inverted_or_not_finite_range_is_a_program_error(self) -> None:
        """RF-011-09: el rango cubicado lo calcula el núcleo; invertido o con NaN es un error
        del programa (``ValueError``), no del usuario."""
        ten = Slices(10.0, 0.0, None)
        for low, high in ((650.0, 600.0), (float("nan"), 650.0), (600.0, float("inf"))):
            with self.subTest(low=low, high=high), self.assertRaises(ValueError):
                slices.bounds(ten, low, high)


class IndexTest(unittest.TestCase):
    def test_half_open_slices_a_level_on_a_bound_goes_up(self) -> None:
        """RF-011-09, D-22, plan A4: con altura y anclaje, el índice es ``floor((z −
        anclaje)/altura)`` (``floor``, nunca ``round``: 15 m es la rodaja 1, no la 2): las
        rodajas son ``[z, z + h)`` y una cota justo en un límite va a la de arriba; la forma
        del array se conserva."""
        ten = Slices(10.0, 0.0, None)
        z = np.array([600.0, 605.0, 609.999, 610.0, 649.9, 650.0, 15.0, 5.0, -0.5, -10.0,
                      -10.5])
        found = slices.index(ten, z)
        self.assertEqual(found.dtype, np.int64)
        self.assertEqual(found.tolist(), [60, 60, 60, 61, 64, 65, 1, 0, -1, -1, -2])
        self.assertEqual(slices.index(ten, z.reshape(1, 11)).shape, (1, 11))
        self.assertEqual(slices.index(Slices(10.0, 2.5, None), 12.5).tolist(), 1)

    def test_a_list_by_position_and_a_level_on_a_bound_goes_up(self) -> None:
        """RF-011-09, plan A4: con una lista, ``searchsorted`` por la derecha − 1: la rodaja
        ``k`` es ``[cota_k, cota_k+1)``; por debajo de la primera, −1; desde la última, el
        número de cotas − 1 (fuera de las rodajas)."""
        listed = Slices(None, None, (600.0, 615.0, 650.0))
        z = np.array([599.9, 600.0, 614.99, 615.0, 649.99, 650.0, 700.0])
        found = slices.index(listed, z)
        self.assertEqual(found.dtype, np.int64)
        self.assertEqual(found.tolist(), [-1, 0, 0, 1, 1, 2, 2])

    def test_the_index_agrees_with_the_bounds(self) -> None:
        """RF-011-09, D-22: el índice casa siempre con las cotas de ``bounds``, también con
        alturas y anclajes que no son exactos en binario (0,3 m, 0,1 m): cada cota de
        ``bounds`` va a su propia rodaja y cada cota ``z`` de lo cubicado cumple
        ``bounds[k] <= z < bounds[k + 1]`` con ``k = index(z) − index(bounds[0])``."""
        generator = np.random.default_rng(11)
        cases = ((0.3, 0.1, 600.05, 640.17), (0.7, -1234.567, -3.3, 81.9),
                 (99.9, 0.01, 12.0, 905.0), (0.001, 0.0003, 600.0, 600.5),
                 (10.0, 0.0, 600.0, 650.0))
        for height, anchor, low, high in cases:
            with self.subTest(height=height, anchor=anchor):
                cut = Slices(height, anchor, None)
                levels = slices.bounds(cut, low, high)
                first = slices.index(cut, levels[0])
                self.assertEqual((slices.index(cut, levels) - first).tolist(),
                                 list(range(len(levels))))
                z = np.concatenate([generator.uniform(low, high, 2000), [low, high]])
                position = slices.index(cut, z) - first
                self.assertTrue(np.all(levels[position] <= z))
                inside = position + 1 < len(levels)
                self.assertTrue(np.all(z[inside] < levels[position[inside] + 1]))
                self.assertTrue(np.all(z[~inside] == levels[-1]))  # solo la máxima, en un límite

    def test_a_non_finite_level_is_a_program_error(self) -> None:
        """RF-011-09: el núcleo solo pide la rodaja de las celdas con dato; una cota NaN o
        infinita es un error del programa (``ValueError``)."""
        for cut in (Slices(10.0, 0.0, None), Slices(None, None, (600.0, 650.0))):
            for bad in (float("nan"), float("-inf")):
                with self.subTest(cut=cut, bad=bad), self.assertRaises(ValueError):
                    slices.index(cut, np.array([600.0, bad]))


class SlicesTest(unittest.TestCase):
    def test_the_height_is_checked_with_its_range(self) -> None:
        """RF-011-09, RF-008-03: la altura de banco fuera de (0; 100] m se rechaza con
        ``res.bench_height_range``, el valor, la clave ``res.bench_height_m`` y su rango; los
        dos extremos admitidos (100 m y algo más de 0) valen."""
        for height in (0.0, -5.0, 100.5, 150.0):
            with self.subTest(height=height), self.assertRaises(ResError) as caught:
                Slices(height, 0.0, None)
            error = caught.exception
            self.assertEqual(error.code, "res.bench_height_range")
            self.assertEqual(error.value, height)
            self.assertEqual(error.values["range"], "(0; 100] m")
            self.assertEqual(error.values["key"], params.BENCH_HEIGHT)
            self.assertIn("(0; 100] m", error.text)
        for height in (100.0, 0.001):
            with self.subTest(height=height):
                self.assertEqual(Slices(height, 0.0, None).height_m, height)

    def test_the_list_is_increasing_with_two_levels_at_least(self) -> None:
        """RF-011-09, RF-008-03: una lista que no crece (o repite una cota) se rechaza con
        ``res.bench_levels_not_increasing``, la cota y la anterior; con menos de dos cotas no
        hay rodaja (``res.bench_levels_too_few``). Se guarda como tupla de float."""
        with self.assertRaises(ResError) as caught:
            Slices(None, None, (600.0, 610.0, 605.0))
        self.assertEqual(caught.exception.code, "res.bench_levels_not_increasing")
        self.assertEqual((caught.exception.value, caught.exception.values["previous"]),
                         (605.0, 610.0))
        self.assertIn("605 va después de 610", caught.exception.text)
        with self.assertRaises(ResError) as caught:
            Slices(None, None, (600.0, 600.0))
        self.assertEqual(caught.exception.code, "res.bench_levels_not_increasing")
        for few in ((), (600.0,)):
            with self.subTest(levels=few), self.assertRaises(ResError) as caught:
                Slices(None, None, few)
            self.assertEqual(caught.exception.code, "res.bench_levels_too_few")
        listed = Slices(None, None, [600, 650.5])
        self.assertEqual(listed.levels, (600.0, 650.5))
        self.assertTrue(all(type(level) is float for level in listed.levels))

    def test_one_way_and_finite_values_or_a_program_error(self) -> None:
        """RF-011-09: o altura y anclaje, o lista; mezclarlos, dejar uno a medias o un valor
        NaN o infinito es un error del programa (``ValueError``): lo que teclea el usuario
        lo comprueba antes ``slices_from_text``."""
        nan = float("nan")
        for height, anchor, levels in ((10.0, None, None), (None, 0.0, None),
                                       (None, None, None), (10.0, 0.0, (600.0, 650.0)),
                                       (nan, 0.0, None), (10.0, float("inf"), None),
                                       (None, None, (600.0, nan))):
            with self.subTest(height=height, anchor=anchor, levels=levels):
                with self.assertRaises(ValueError):
                    Slices(height, anchor, levels)


class FromTextTest(unittest.TestCase):
    def test_height_and_anchor_typed(self) -> None:
        """RF-011-09, RF-008-03: la altura y el anclaje tecleados, con coma o punto decimal,
        espacios de miles y, si se quiere, la unidad (en metros); en float64."""
        cases = (("10", "0", (10.0, 0.0)), ("2,5", "602,5", (2.5, 602.5)),
                 (" 7.5 ", "-97,5", (7.5, -97.5)), ("10 m", "1 002,5 m", (10.0, 1002.5)))
        for height, anchor, expected in cases:
            with self.subTest(height=height, anchor=anchor):
                cut = slices.slices_from_text(height, anchor, "")
                self.assertEqual(cut, Slices(*expected, None))
                self.assertIs(type(cut.height_m), float)
                self.assertIs(type(cut.anchor_m), float)

    def test_a_typed_list(self) -> None:
        """RF-011-09: la lista, sus cotas separadas por «;» (la coma es decimal), con o sin
        espacios y en metros."""
        for text in ("600; 615,5; 650", "600;615.5;650", " 600 m ; 615,5 ; 650 "):
            with self.subTest(text=text):
                self.assertEqual(slices.slices_from_text("", "", text),
                                 Slices(None, None, (600.0, 615.5, 650.0)))

    def test_nothing_typed_is_no_slices(self) -> None:
        """RF-011-09: sin altura, anclaje ni lista no se reparte por bancos (``None``)."""
        self.assertIsNone(slices.slices_from_text("", "  ", ""))

    def test_rejections_with_their_range(self) -> None:
        """RF-011-09, RF-008-03 (§8 de la spec): una altura ≤ 0 o > 100 m y una lista no
        creciente se rechazan con su rango y su valor; con menos de dos cotas, también."""
        for height in ("0", "-5", "100,5", "150", "0 m"):
            with self.subTest(height=height), self.assertRaises(ResError) as caught:
                slices.slices_from_text(height, "0", "")
            self.assertEqual(caught.exception.code, "res.bench_height_range")
            self.assertEqual(caught.exception.values["range"], "(0; 100] m")
            self.assertEqual(caught.exception.field, "bench_height")
        self.assertEqual(slices.slices_from_text("100", "0", "").height_m, 100.0)
        with self.assertRaises(ResError) as caught:
            slices.slices_from_text("", "", "600; 610; 605")
        self.assertEqual(caught.exception.code, "res.bench_levels_not_increasing")
        self.assertEqual(caught.exception.field, "bench_levels")
        self.assertEqual((caught.exception.value, caught.exception.values["previous"]),
                         (605.0, 610.0))
        with self.assertRaises(ResError) as caught:
            slices.slices_from_text("", "", "600")
        self.assertEqual(caught.exception.code, "res.bench_levels_too_few")
        self.assertEqual(caught.exception.value, "600")

    def test_what_is_not_a_number_of_metres(self) -> None:
        """RF-011-09, RF-008-03: lo que no es un número de metros (letras, NaN, infinito, una
        unidad que no es de longitud, una cota vacía en la lista) se rechaza con
        ``res.bench_value_not_number``, el nombre del campo y lo tecleado."""
        cases = (
            (("diez", "0", ""), "bench_height", HEIGHT_LABEL, "diez"),
            (("10 kg", "0", ""), "bench_height", HEIGHT_LABEL, "10 kg"),
            (("10", "6O0", ""), "bench_anchor", ANCHOR_LABEL, "6O0"),
            (("10", "nan", ""), "bench_anchor", ANCHOR_LABEL, "nan"),
            (("", "", "600; 6l0"), "bench_levels", LEVELS_LABEL, "6l0"),
            (("", "", "600; inf"), "bench_levels", LEVELS_LABEL, "inf"),
            (("", "", "600;; 650"), "bench_levels", LEVELS_LABEL, ""),
        )
        for typed, field, label, value in cases:
            with self.subTest(typed=typed), self.assertRaises(ResError) as caught:
                slices.slices_from_text(*typed)
            error = caught.exception
            self.assertEqual(error.code, "res.bench_value_not_number")
            self.assertEqual((error.field, error.values["label"], error.value),
                             (field, label, value))
            self.assertTrue(error.text.startswith(f"{label}: «{value}» no es un número"))

    def test_half_typed_or_both_ways(self) -> None:
        """RF-011-09: la altura sin anclaje (o al revés) se rechaza nombrando lo que falta
        (``res.bench_value_missing``); altura y anclaje a la vez que una lista, con
        ``res.bench_both_ways``: nada se ignora en silencio."""
        for typed, field, label in ((("10", "", ""), "bench_anchor", ANCHOR_LABEL),
                                    (("", "0", ""), "bench_height", HEIGHT_LABEL)):
            with self.subTest(typed=typed), self.assertRaises(ResError) as caught:
                slices.slices_from_text(*typed)
            self.assertEqual(caught.exception.code, "res.bench_value_missing")
            self.assertEqual((caught.exception.field, caught.exception.values["label"]),
                             (field, label))
        for typed in (("10", "0", "600; 650"), ("10", "", "600; 650"), ("", "0", "600; 650")):
            with self.subTest(typed=typed), self.assertRaises(ResError) as caught:
                slices.slices_from_text(*typed)
            self.assertEqual(caught.exception.code, "res.bench_both_ways")


if __name__ == "__main__":
    unittest.main()
