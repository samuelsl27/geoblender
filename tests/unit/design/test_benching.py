# SPDX-License-Identifier: GPL-3.0-or-later
"""El escalonado en corte y en relleno (spec 013, T09; HU-013-5; RF-013-22, RF-013-23, RF-013-24;
plan 013 A8).

``design.benching`` convierte una superficie continua ``S`` en bancos y bermas anclados a las cotas
absolutas ``z₀ + n·h``: con el perfil de cada celda (``h``, ``tan α``, ``B``, ``a = h/tan α + B``),
``u = (S − z₀)/h``, ``n = ⌊u⌋`` y ``f = u − n``, el **corte** (cara primero) da
``z₀ + n·h + mín(f·a·tan α, h)`` y el **relleno** (berma primero),
``z₀ + n·h + máx((f·a − B)·tan α, 0)``. Se comprueba:

- **A mano** (RF-013-22, RF-013-23): cotas hechas a mano de la cara y de la berma de
  ``EXPL_10_60_6`` y ``REST_5_35_6`` en corte y en relleno, también bajo el ancla; y frente a la
  aritmética racional exacta del oráculo (``design_oracles.hand_stairs``, el piso ``n`` y la
  fracción ``f`` en fracciones) a ≤ 10⁻⁹ m con miles de celdas aleatorias, con un perfil único y
  con un perfil por celda.
- **Por encima y por debajo** (RF-013-22, RF-013-23): el corte queda por encima de ``S`` y a menos
  de ``h`` de ella, el relleno por debajo y a menos de ``h``, en toda celda, también con berma 0 (la
  propia superficie) y con una berma enorme; el escalonado es continuo, monótono y no pasa de la
  pendiente ``a·tan α/h`` respecto de ``S``; corte y relleno son imágenes especulares.
- **Las bermas, en las cotas de anclaje** (RF-013-24): la parte plana de cada banco es exactamente
  ``z₀ + n·h`` y ocupa la fracción ``B·tan α/(h + B·tan α)`` de la cota; el ancla es absoluta
  (recortar la rejilla no cambia nada, subir la superficie un banco sube el resultado un banco, un
  ancla desplazada un número entero de alturas da lo mismo), puede ser una rejilla (una cota por
  celda) y nada se mueve por repetir el cálculo ni por ningún dato de fuera.
- **Los datos** (RF-013-16, D-1): la superficie sin dato queda sin dato y sin avisos de numpy; una
  altura, una tangente, una berma o un ancla inválidos son un error del programa (``ValueError``);
  nada se modifica y cada llamada da un array nuevo en float64.
"""

from __future__ import annotations

import math
import unittest
import warnings
from collections.abc import Callable
from typing import Any

import numpy as np

from tests.support import design_fixtures as dfx
from tests.support import design_oracles as oracles
from tests.support.package import import_geoblender

benching = import_geoblender("design.benching")

EXPL = dfx.EXPL_10_60_6
REST = dfx.REST_5_35_6
DESD = dfx.DESD_10_45_6
SQRT3 = math.sqrt(3.0)
TOLERANCE_M = 1e-9


def tan_of(profile: Any) -> float:
    """La tangente de la cara de un perfil de pruebas."""
    return math.tan(math.radians(profile.face_deg))


def stairs(function: Callable[..., np.ndarray], surface: Any, profile: Any,
           anchor: Any = None) -> np.ndarray:
    """``function`` (corte o relleno) con los valores de un perfil de pruebas."""
    return function(surface, profile.height_m, tan_of(profile), profile.berm_m,
                    profile.anchor_m if anchor is None else anchor)


def random_profiles(shape: tuple[int, ...], seed: int) -> tuple[np.ndarray, ...]:
    """Una superficie y un perfil por celda: ``h`` de 2 a 20 m, caras de 20° a 80°, bermas de 0 a
    25 m (el 10 % sin berma) y anclas de 100 a 140 m."""
    rng = np.random.default_rng(seed)
    surface = rng.uniform(40.0, 260.0, shape)
    height = rng.uniform(2.0, 20.0, shape)
    tan_face = np.tan(np.radians(rng.uniform(20.0, 80.0, shape)))
    berm = np.where(rng.random(shape) < 0.1, 0.0, rng.uniform(0.0, 25.0, shape))
    anchor = rng.uniform(100.0, 140.0, shape)
    return surface, height, tan_face, berm, anchor


def share_on_levels(values: np.ndarray, height: float, anchor: float) -> float:
    """La fracción de ``values`` que está en una cota ``anchor + n·height`` (a ≤ 10⁻⁹ m)."""
    levels = (values - anchor) / height
    return float(np.mean(np.abs(levels - np.round(levels)) * height <= TOLERANCE_M))


class HandTest(unittest.TestCase):
    """RF-013-22, RF-013-23: cotas hechas a mano."""

    def test_expl_10_60_6_cut_by_hand(self) -> None:
        """Con ``h`` 10 m, cara de 60°, berma de 6 m y ancla de 125 m (``a·tan α`` = 10 + 6√3 =
        20,3923), el corte da: 145 en un piso (f = 0); 140,125 m (n = 1, f = 0,5125) ya en la berma
        del banco de arriba (145); 146 m (n = 2, f = 0,1) en la cara, 145 + 0,1·20,3923 = 147,0392;
        154,999 m (f = 0,9999) en la berma de 155."""
        found = stairs(benching.bench_cut, np.array([145.0, 140.125, 146.0, 154.999]), EXPL)
        np.testing.assert_allclose(found, [145.0, 145.0, 147.03923048454132, 155.0], rtol=0.0,
                                   atol=TOLERANCE_M)

    def test_expl_10_60_6_fill_by_hand(self) -> None:
        """El relleno (berma primero): 145 en un piso; 146 m (f = 0,1, antes de B/a = 0,5097) en la
        berma de 145; 140,125 m (f = 0,5125) ya en la cara, 135 + 0,5125·20,3923 − 6√3 = 135,0588;
        154,999 m, 6√3·0,0001 = 0,00104 m por debajo."""
        found = stairs(benching.bench_fill, np.array([145.0, 146.0, 140.125, 154.999]), EXPL)
        np.testing.assert_allclose(found, [145.0, 145.0, 135.05875138786104, 154.99796076951546],
                                   rtol=0.0, atol=TOLERANCE_M)

    def test_rest_5_35_6_by_hand(self) -> None:
        """``h`` 5 m, cara de 35°, berma de 6 m, ancla 125 m: a 140,125 m (n = 3, f = 0,025) el
        corte sube 0,025·(5 + 6 tan 35°) = 0,2300 sobre 140 y el relleno se queda en la berma
        (140); a 142,4 m (f = 0,48) el corte da 144,4166 y el relleno, 140,2154."""
        surface = np.array([140.125, 142.4])
        np.testing.assert_allclose(stairs(benching.bench_cut, surface, REST),
                                   [140.23003113073145, 144.41659771004396], rtol=0.0,
                                   atol=TOLERANCE_M)
        np.testing.assert_allclose(stairs(benching.bench_fill, surface, REST),
                                   [140.0, 140.2153524807857], rtol=0.0, atol=TOLERANCE_M)

    def test_floors_below_the_anchor(self) -> None:
        """RF-013-24: los pisos siguen a ``z₀ + n·h`` bajo el ancla (``n`` negativo): 100 m
        (u = −2,5) queda en la berma de 105 m en corte; 95 m (u = −3) es un piso y 94,999 m
        (u = −3,0001), el banco de abajo."""
        surface = np.array([100.0, 95.0, 94.999])
        found = stairs(benching.bench_cut, surface, EXPL)
        np.testing.assert_allclose(found[:2], [105.0, 95.0], rtol=0.0, atol=TOLERANCE_M)
        self.assertGreaterEqual(float(found[2]), 94.999)
        self.assertLess(float(found[2]), 95.0 + 1.0)
        filled = stairs(benching.bench_fill, surface, EXPL)
        np.testing.assert_allclose(filled[:2], [95.0, 95.0], rtol=0.0, atol=TOLERANCE_M)
        self.assertLessEqual(float(filled[2]), 94.999)
        self.assertGreater(float(filled[2]), 85.0)

    def test_scalar_inputs_and_shapes(self) -> None:
        """Una cota suelta, un vector y una matriz dan el mismo resultado con su forma."""
        self.assertEqual(stairs(benching.bench_cut, 146.0, EXPL).shape, ())
        self.assertAlmostEqual(float(stairs(benching.bench_cut, 146.0, EXPL)),
                               147.03923048454132, delta=TOLERANCE_M)
        grid = np.array([[146.0, 150.0], [160.0, 170.0]])
        found = stairs(benching.bench_fill, grid, EXPL)
        self.assertEqual(found.shape, (2, 2))
        np.testing.assert_array_equal(found.reshape(-1),
                                      stairs(benching.bench_fill, grid.reshape(-1), EXPL))
        self.assertEqual(stairs(benching.bench_cut, np.empty((0, 5)), EXPL).shape, (0, 5))


class ExactArithmeticTest(unittest.TestCase):
    """RF-013-22, RF-013-23: frente al oráculo de aritmética racional, a ≤ 10⁻⁹ m."""

    def test_the_three_profiles_with_random_cells(self) -> None:
        """Con cada perfil de la spec y en los dos sentidos, 1.200 cotas aleatorias de 60 a 260 m
        (muchas bajo el ancla) coinciden con ``hand_stairs``."""
        rng = np.random.default_rng(11)
        surface = rng.uniform(60.0, 260.0, 1200)
        for profile in (EXPL, REST, DESD):
            for fill, function in ((False, benching.bench_cut), (True, benching.bench_fill)):
                with self.subTest(profile=profile.name, fill=fill):
                    found = stairs(function, surface, profile)
                    expected = oracles.hand_stairs(surface, profile.height_m, tan_of(profile),
                                                   profile.berm_m, profile.anchor_m, fill=fill)
                    self.assertLessEqual(float(np.abs(found - expected).max()), TOLERANCE_M)

    def test_a_profile_per_cell(self) -> None:
        """Con una altura, una cara, una berma y un ancla distintos en cada celda (30 × 50), el
        resultado es el del oráculo celda a celda, en corte y en relleno."""
        surface, height, tan_face, berm, anchor = random_profiles((30, 50), 5)
        for fill, function in ((False, benching.bench_cut), (True, benching.bench_fill)):
            with self.subTest(fill=fill):
                found = function(surface, height, tan_face, berm, anchor)
                expected = oracles.hand_stairs(surface, height, tan_face, berm, anchor, fill=fill)
                self.assertEqual(found.shape, surface.shape)
                self.assertLessEqual(float(np.abs(found - expected).max()), TOLERANCE_M)

    def test_surface_on_and_next_to_the_levels(self) -> None:
        """Las cotas justo en un piso, un ulp por encima y un ulp por debajo, con perfiles de
        altura no entera (7,3 m), dan lo del oráculo: el corte y el relleno no saltan en el piso."""
        height = 7.3
        tan_face = math.tan(math.radians(55.0))
        levels = 118.0 + height * np.arange(-12, 13)
        surface = np.concatenate([levels, np.nextafter(levels, np.inf),
                                  np.nextafter(levels, -np.inf)])
        for fill, function in ((False, benching.bench_cut), (True, benching.bench_fill)):
            with self.subTest(fill=fill):
                found = function(surface, height, tan_face, 4.0, 118.0)
                expected = oracles.hand_stairs(surface, height, tan_face, 4.0, 118.0, fill=fill)
                self.assertLessEqual(float(np.abs(found - expected).max()), TOLERANCE_M)


class BoundsTest(unittest.TestCase):
    """RF-013-22, RF-013-23: por encima o por debajo de ``S`` y a menos de ``h``."""

    def setUp(self) -> None:
        self.surface, self.height, self.tan_face, self.berm, self.anchor = random_profiles(
            (400, 250), 21)

    def test_cut_is_above_and_less_than_one_bench_over(self) -> None:
        """En 100.000 celdas con un perfil cada una (el 10 % sin berma), el corte queda por encima
        de ``S`` (sin ninguna excepción por redondeo) y a menos de ``h`` de ella."""
        found = benching.bench_cut(self.surface, self.height, self.tan_face, self.berm, self.anchor)
        self.assertGreaterEqual(float((found - self.surface).min()), 0.0)
        self.assertTrue(np.all(found - self.surface < self.height))

    def test_fill_is_below_and_less_than_one_bench_under(self) -> None:
        """En esas mismas celdas, el relleno queda por debajo de ``S`` (sin excepciones) y a
        menos de ``h`` de ella."""
        found = benching.bench_fill(self.surface, self.height, self.tan_face, self.berm,
                                    self.anchor)
        self.assertGreaterEqual(float((self.surface - found).min()), 0.0)
        self.assertTrue(np.all(self.surface - found < self.height))

    def test_a_huge_berm_stays_under_one_bench(self) -> None:
        """Con una berma de 10⁶ m el desfase máximo se acerca a ``h`` (``h·B·tan α/(h + B·tan α)``)
        pero no la alcanza, en corte y en relleno."""
        surface = np.linspace(100.0, 200.0, 50_001)
        cut = benching.bench_cut(surface, 10.0, SQRT3, 1.0e6, 125.0)
        fill = benching.bench_fill(surface, 10.0, SQRT3, 1.0e6, 125.0)
        self.assertLess(float((cut - surface).max()), 10.0)
        self.assertGreater(float((cut - surface).max()), 9.99)
        self.assertLess(float((surface - fill).max()), 10.0)
        self.assertGreater(float((surface - fill).max()), 9.99)

    def test_without_berm_the_staircase_is_the_surface(self) -> None:
        """Con berma 0 no hay parte plana: la cara de ``h/tan α`` de huella es la propia
        superficie (``a·tan α = h``), en corte y en relleno."""
        surface = np.random.default_rng(3).uniform(50.0, 250.0, 5000)
        for function in (benching.bench_cut, benching.bench_fill):
            found = function(surface, 10.0, SQRT3, 0.0, 125.0)
            self.assertLessEqual(float(np.abs(found - surface).max()), TOLERANCE_M)

    def test_continuous_monotone_and_not_steeper_than_the_profile(self) -> None:
        """Sobre una rampa de ``S`` de 5·10⁻⁴ m de paso, el escalonado no baja nunca (monótono) y
        no salta más de ``(1 + B·tan α/h)·ΔS`` (es continuo: la cara sube como mucho
        ``a·tan α/h`` por metro de ``S``)."""
        surface = np.linspace(100.0, 200.0, 200_001)
        step = float(np.diff(surface).max())
        for profile in (EXPL, REST):
            limit = (1.0 + profile.berm_m * tan_of(profile) / profile.height_m) * step
            for function in (benching.bench_cut, benching.bench_fill):
                with self.subTest(profile=profile.name, function=function.__name__):
                    jumps = np.diff(stairs(function, surface, profile))
                    self.assertGreaterEqual(float(jumps.min()), -TOLERANCE_M)
                    self.assertLessEqual(float(jumps.max()), limit + TOLERANCE_M)
                    self.assertGreater(float(jumps.max()), 0.9 * limit)

    def test_cut_and_fill_are_mirror_images(self) -> None:
        """El relleno es el corte visto en el espejo: ``fill(S, z₀) = −cut(−S, −z₀)`` (la cara
        primero hacia arriba es la berma primero hacia abajo), celda a celda."""
        filled = benching.bench_fill(self.surface, self.height, self.tan_face, self.berm,
                                     self.anchor)
        mirrored = -benching.bench_cut(-self.surface, self.height, self.tan_face, self.berm,
                                       -self.anchor)
        self.assertLessEqual(float(np.abs(filled - mirrored).max()), TOLERANCE_M)


class AnchorTest(unittest.TestCase):
    """RF-013-24: las bermas en ``z₀ + n·h``, el ancla absoluta y nada que la mueva."""

    PROFILES = ((EXPL, "EXPL_10_60_6"), (REST, "REST_5_35_6"))

    def test_flat_part_is_on_the_anchor_levels_and_has_the_right_share(self) -> None:
        """Sobre 20 bancos de cotas equiespaciadas, la fracción de celdas en una cota ``z₀ + n·h``
        (≤ 10⁻⁹ m) es ``B·tan α/(h + B·tan α)`` (la berma; la cara no está en ninguna), en corte y
        en relleno."""
        for profile, name in self.PROFILES:
            share = profile.berm_m * tan_of(profile) / (
                profile.height_m + profile.berm_m * tan_of(profile))
            count = 200_000
            surface = profile.anchor_m + (np.arange(count) + 0.5) / count * (
                20.0 * profile.height_m)
            for function in (benching.bench_cut, benching.bench_fill):
                with self.subTest(profile=name, function=function.__name__):
                    found = share_on_levels(stairs(function, surface, profile), profile.height_m,
                                            profile.anchor_m)
                    self.assertAlmostEqual(found, share, delta=1e-3)

    def test_anchor_is_absolute_not_relative_to_the_grid(self) -> None:
        """Quitar columnas (cambia la cota mínima de la rejilla) no cambia ninguna cota que queda,
        bit a bit: el resultado de una celda solo depende de su cota, su perfil y su ancla."""
        surface = dfx.plane_case().surface()
        for function in (benching.bench_cut, benching.bench_fill):
            full = stairs(function, surface, EXPL)
            for first in (0, 37, 90):
                with self.subTest(function=function.__name__, first=first):
                    np.testing.assert_array_equal(stairs(function, surface[:, first:], EXPL),
                                                  full[:, first:])
                    np.testing.assert_array_equal(stairs(function, surface[5:17], EXPL),
                                                  full[5:17])

    def test_raising_the_surface_one_bench_raises_the_result_one_bench(self) -> None:
        """Subir ``S`` exactamente ``h`` sube el escalonado ``h``: es la misma escalera."""
        surface = np.random.default_rng(8).uniform(60.0, 250.0, 4000)
        for profile, name in self.PROFILES:
            for function in (benching.bench_cut, benching.bench_fill):
                with self.subTest(profile=name, function=function.__name__):
                    higher = stairs(function, surface + 3 * profile.height_m, profile)
                    np.testing.assert_allclose(higher, stairs(function, surface, profile)
                                               + 3 * profile.height_m, rtol=0.0, atol=TOLERANCE_M)

    def test_an_anchor_shifted_whole_heights_changes_nothing(self) -> None:
        """Un ancla desplazada un número entero de alturas (también negativo) es la misma escalera;
        una que no lo es mueve las bermas a sus nuevas cotas ``z₀' + n·h``."""
        surface = np.random.default_rng(9).uniform(60.0, 250.0, 4000)
        for function in (benching.bench_cut, benching.bench_fill):
            base = stairs(function, surface, EXPL)
            for shift in (10.0, -30.0, 240.0):
                with self.subTest(function=function.__name__, shift=shift):
                    found = stairs(function, surface, EXPL, anchor=125.0 + shift)
                    self.assertLessEqual(float(np.abs(found - base).max()), TOLERANCE_M)
            moved = stairs(function, surface, EXPL, anchor=127.5)
            self.assertGreater(share_on_levels(moved, 10.0, 127.5), 0.45)
            self.assertLess(share_on_levels(moved, 10.0, 125.0), 0.01)

    def test_anchor_grid_gives_one_anchor_per_cell(self) -> None:
        """Con una rejilla de anclas (una cota por celda), cada celda sale como con su ancla
        suelta: la mitad oeste con 125 m y la este con 127,5 m."""
        surface = dfx.plane_case().surface()
        anchors = np.full(surface.shape, 125.0)
        anchors[:, 80:] = 127.5
        for function in (benching.bench_cut, benching.bench_fill):
            with self.subTest(function=function.__name__):
                found = stairs(function, surface, EXPL, anchor=anchors)
                west = stairs(function, surface, EXPL, anchor=125.0)
                east = stairs(function, surface, EXPL, anchor=127.5)
                np.testing.assert_array_equal(found[:, :80], west[:, :80])
                np.testing.assert_array_equal(found[:, 80:], east[:, 80:])
                self.assertGreater(float(np.abs(west - east).max()), 1.0)

    def test_nothing_moves_the_anchor_or_the_height(self) -> None:
        """No hay cierre ni ajuste que la mueva (error 12): las entradas de solo lectura no se
        tocan, repetir da los mismos bits y cada llamada da un array nuevo (RF-013-24)."""
        surface, height, tan_face, berm, anchor = random_profiles((40, 50), 4)
        arrays = (surface, height, tan_face, berm, anchor)
        for array in arrays:
            array.setflags(write=False)
        copies = [array.copy() for array in arrays]
        for function in (benching.bench_cut, benching.bench_fill):
            first = function(*arrays)
            second = function(*arrays)
            np.testing.assert_array_equal(first, second)
            for array, copy in zip(arrays, copies, strict=True):
                np.testing.assert_array_equal(array, copy)
                self.assertFalse(np.shares_memory(first, array))
            first[:] = 0.0
            self.assertTrue(np.all(function(*arrays) != 0.0))


class ProfileMapsTest(unittest.TestCase):
    """Los perfiles por celda (sectores): matrices, vectores y escalares se difunden."""

    def test_map_of_profiles_equals_each_profile_alone(self) -> None:
        """Un mapa con ``EXPL_10_60_6`` al oeste y ``REST_5_35_6`` al este da lo de cada perfil
        suelto en su mitad (corte y relleno)."""
        surface = dfx.plane_case().surface()
        west = np.s_[:, :80]
        east = np.s_[:, 80:]
        height = np.where(np.arange(surface.shape[1]) < 80, EXPL.height_m, REST.height_m)
        tan_face = np.where(np.arange(surface.shape[1]) < 80, tan_of(EXPL), tan_of(REST))
        berm = np.where(np.arange(surface.shape[1]) < 80, EXPL.berm_m, REST.berm_m)
        full_height = np.broadcast_to(height, surface.shape)
        full_tan = np.broadcast_to(tan_face, surface.shape)
        full_berm = np.broadcast_to(berm, surface.shape)
        for function in (benching.bench_cut, benching.bench_fill):
            with self.subTest(function=function.__name__):
                for shapes in ((height, tan_face, berm), (full_height, full_tan, full_berm)):
                    found = function(surface, *shapes, 125.0)
                    only_expl = stairs(function, surface, EXPL)
                    only_rest = stairs(function, surface, REST)
                    np.testing.assert_array_equal(found[west], only_expl[west])
                    np.testing.assert_array_equal(found[east], only_rest[east])

    def test_scalar_and_filled_array_give_the_same_bits(self) -> None:
        """Un parámetro escalar y el mismo valor en un array lleno no cambian ni un bit."""
        surface = np.random.default_rng(2).uniform(60.0, 250.0, (30, 40))
        for function in (benching.bench_cut, benching.bench_fill):
            alone = function(surface, 10.0, SQRT3, 6.0, 125.0)
            filled = function(surface, np.full(surface.shape, 10.0), np.full(surface.shape, SQRT3),
                              np.full(surface.shape, 6.0), np.full(surface.shape, 125.0))
            np.testing.assert_array_equal(alone, filled)


class DataTest(unittest.TestCase):
    """Los datos que faltan y los inválidos."""

    def test_cells_without_data_stay_without_data_and_without_warnings(self) -> None:
        """Una celda NaN, +inf o −inf (sin envolvente) sale NaN, sin avisos de numpy y sin tocar las
        demás (D-1)."""
        surface = np.array([146.0, np.nan, np.inf, -np.inf, 150.0])
        for function in (benching.bench_cut, benching.bench_fill):
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                found = stairs(function, surface, EXPL)
            self.assertTrue(np.isnan(found[1:4]).all())
            expected = stairs(function, surface[[0, 4]], EXPL)
            np.testing.assert_array_equal(found[[0, 4]], expected)

    def test_float32_surface_is_computed_in_float64(self) -> None:
        """Una superficie en float32 se calcula en float64 (el resultado es float64 y es el de la
        superficie convertida)."""
        surface = np.array([146.0, 150.5, 163.25], dtype=np.float32)
        found = stairs(benching.bench_cut, surface, EXPL)
        self.assertEqual(found.dtype, np.float64)
        np.testing.assert_array_equal(found, stairs(benching.bench_cut,
                                                    surface.astype(np.float64), EXPL))

    def test_profile_of_cells_without_surface_is_not_checked(self) -> None:
        """Un perfil sin valor (NaN) o un ancla sin valor en una celda sin superficie no impiden
        calcular las demás: solo cuenta lo de las celdas con superficie."""
        surface = np.array([146.0, np.nan, 150.0])
        height = np.array([10.0, np.nan, 10.0])
        tan_face = np.array([SQRT3, np.nan, SQRT3])
        berm = np.array([6.0, np.nan, 6.0])
        anchor = np.array([125.0, np.nan, 125.0])
        found = benching.bench_cut(surface, height, tan_face, berm, anchor)
        self.assertTrue(np.isnan(found[1]))
        np.testing.assert_array_equal(found[[0, 2]],
                                      stairs(benching.bench_cut, surface[[0, 2]], EXPL))

    def test_invalid_parameters_are_refused(self) -> None:
        """Una altura o una tangente que no sea finita y mayor que 0, una berma negativa o no finita
        y un ancla no finita (con superficie en la celda) son ``ValueError`` que nombra el
        parámetro; también si es un array y la celda mala tiene superficie."""
        surface = np.array([146.0, 150.0])
        good = (10.0, SQRT3, 6.0, 125.0)
        cases = (("height", 0, 0.0), ("height", 0, -1.0), ("height", 0, math.nan),
                 ("height", 0, math.inf), ("tan_face", 1, 0.0), ("tan_face", 1, -2.0),
                 ("tan_face", 1, math.nan), ("berm", 2, -0.1), ("berm", 2, math.nan),
                 ("berm", 2, math.inf), ("anchor", 3, math.nan), ("anchor", 3, math.inf))
        for name, position, value in cases:
            for as_array in (False, True):
                arguments = list(good)
                arguments[position] = np.array([good[position], value]) if as_array else value
                for function in (benching.bench_cut, benching.bench_fill):
                    with self.subTest(name=name, value=value, as_array=as_array):
                        with self.assertRaisesRegex(ValueError, name):
                            function(surface, *arguments)

    def test_berm_of_zero_is_valid(self) -> None:
        """Una berma de 0 m es válida (el perfil sin berma); un ancla negativa también."""
        found = benching.bench_cut(np.array([-20.0, 5.0]), 10.0, SQRT3, 0.0, -35.0)
        np.testing.assert_allclose(found, [-20.0, 5.0], rtol=0.0, atol=TOLERANCE_M)

    def test_shape_that_does_not_fit_is_refused(self) -> None:
        """Un parámetro que no se difunde a la forma de la superficie (ni la amplía) es
        ``ValueError``."""
        surface = np.zeros((4, 5)) + 150.0
        with self.assertRaisesRegex(ValueError, "forma"):
            benching.bench_cut(surface, np.full((4, 6), 10.0), SQRT3, 6.0, 125.0)
        with self.assertRaisesRegex(ValueError, "forma"):
            benching.bench_cut(surface, 10.0, SQRT3, 6.0, np.full((2, 4, 5), 125.0))
        with self.assertRaisesRegex(ValueError, "forma"):
            benching.bench_fill(np.float64(150.0), np.full(3, 10.0), SQRT3, 6.0, 125.0)


if __name__ == "__main__":
    unittest.main()
