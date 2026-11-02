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

La T10 añade tres piezas (plan 013 A7 y A9, D-11):

- **La berma impuesta** (``sector_berm``, RF-013-25): ``B_s = máx(B, h/tan β − h/tan α)``, hecha a
  mano (el sector de 10,6° con ``REST_5_35_6`` da 19,5765237 m), nunca menor que la mínima del
  perfil, con el talud general de los bancos que resulta ≤ β, sin depender de ninguna superficie
  (error 13) y comprobada en una rampa que escalona con ella.
- **La regularización entre sectores** (``implicated_cells`` y ``regularize_steps``, RF-013-26, A7):
  la envolvente ascendente de la propia envolvente con la tangente más empinada de los sectores
  implicados es la del oráculo (Dijkstra) a ≤ 10⁻⁹ m, nunca sube la superficie, quita las paredes
  del borde entre sectores, no cambia una envolvente que ya es regular, deja sin tocar lo que no
  tiene dato y no modifica nada de lo que recibe.
- **El recorte final** (``final_trim_steps``, RF-013-27, A9): la envolvente ascendente del
  escalonado con la tangente de la cara por el factor de malla de cada celda es la del oráculo,
  ninguna inclinación entre vecinas pasa de la cara, el corte no baja de ``S`` ni el relleno sube de
  ella (aun con un escalonado que no cumple), y nada se mueve si no hacía falta.
"""

from __future__ import annotations

import inspect
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
envelopes = import_geoblender("design.envelopes")
design_model = import_geoblender("design.model")
gis = import_geoblender("gis")
progress_mod = import_geoblender("core.project.model")

EXPL = dfx.EXPL_10_60_6
REST = dfx.REST_5_35_6
DESD = dfx.DESD_10_45_6
SQRT3 = math.sqrt(3.0)
TOLERANCE_M = 1e-9
SCALE = 0.98644
"""La escala del *chamfer* 5×5 (ADR-0014): una celda vecina de eje cuesta ``SCALE·t·h``."""


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


# --- T10: la berma impuesta, la regularización y el recorte final -------------------------------

TAN_REST = tan_of(REST)
WIDTH = 5
"""El ancho, en columnas, de cada franja de sector de las superficies de las pruebas."""


def model_profile(fixture: Any) -> Any:
    """Un ``BenchProfile`` de ``design.model`` con los números de un perfil de pruebas."""
    return design_model.BenchProfile(fixture.code, fixture.name, fixture.height_m,
                                     fixture.face_deg, fixture.berm_m, fixture.anchor_m)


def finish(steps: Any) -> tuple[list[Any], Any]:
    """Los ``Progress`` de unos pasos (menos el último) y el resultado del último."""
    found = list(steps)
    return found[:-1], found[-1].result


def pair_views(grid: np.ndarray, d_row: int, d_col: int) -> tuple[np.ndarray, np.ndarray]:
    """Los trozos de ``grid`` que son cada celda y su vecina desplazada ``(d_row, d_col)``
    (``d_row ≥ 0``), para medir la inclinación entre vecinas sin bucles."""
    rows, cols = grid.shape
    first = grid[0:rows - d_row, max(0, -d_col):cols - max(0, d_col)]
    second = grid[d_row:rows, max(0, d_col):cols - max(0, -d_col)]
    return first, second


def max_slope(grid: np.ndarray, step: float = 1.0) -> float:
    """La mayor inclinación (tangente) entre celdas vecinas a 8 vecinos, sin contar las parejas
    en las que alguna celda no tiene cota finita."""
    worst = 0.0
    for d_row, d_col in ((0, 1), (1, 0), (1, 1), (1, -1)):
        first, second = pair_views(grid, d_row, d_col)
        with np.errstate(invalid="ignore"):
            slope = np.abs(first - second) / (step * math.hypot(d_row, d_col))
        slope = slope[np.isfinite(slope)]
        if slope.size:
            worst = max(worst, float(slope.max()))
    return worst


def bands(shape: tuple[int, int], values: tuple[float, ...], width: int = WIDTH) -> np.ndarray:
    """Un mapa de pendientes en franjas de ``width`` columnas con los ``values`` en orden (la
    última se repite hasta el final)."""
    index = np.minimum(np.arange(shape[1]) // width, len(values) - 1)
    return np.broadcast_to(np.asarray(values)[index], shape).copy()


def walled(values: tuple[float, ...] = (0.2, 0.5), rows: int = 24, width: int = 20
           ) -> tuple[np.ndarray, Any, Any]:
    """Una superficie con una pared en el borde entre sectores: franjas de ``width`` columnas
    cuya cota sube ``t`` por fila (``100 + t·fila``), con la ``t`` de cada franja (la pendiente del
    sector); la pared crece con la fila. Da la superficie, su ``SlopeField`` y la rejilla."""
    cols = width * len(values)
    tangents = bands((rows, cols), values, width)
    surface = 100.0 + tangents * np.arange(rows)[:, None]
    return surface, envelopes.SlopeField(tangents), dfx.grid_from(rows, cols, 1.0)


class SectorBermTest(unittest.TestCase):
    """RF-013-25 (D-11): la berma de un sector con talud general máximo impuesto."""

    def test_rest_5_35_6_with_10_6_degrees_is_19_576(self) -> None:
        """A mano: ``5/tan 10,6° − 5/tan 35°`` = 26,7173 − 7,1407 = **19,5765237 m** (el «19,576 m»
        de la spec es ese valor truncado al milímetro), a ≤ 10⁻⁹ relativo; sin talud impuesto, la
        mínima del perfil (6 m)."""
        profile = model_profile(REST)
        found = benching.sector_berm(profile, 10.6)
        self.assertAlmostEqual(found / 19.5765237, 1.0, delta=1e-9)
        self.assertAlmostEqual(found / dfx.imposed_berm_m(REST, 10.6), 1.0, delta=1e-9)
        self.assertAlmostEqual(found / dfx.IMPOSED_BERM_M, 1.0, delta=1e-9)
        self.assertEqual(math.floor(found * 1000.0) / 1000.0, 19.576)
        self.assertEqual(benching.sector_berm(profile, None), 6.0)
        self.assertIsInstance(found, float)

    def test_other_profiles_and_slopes_by_hand(self) -> None:
        """``EXPL_10_60_6`` (10 m, 60°) con 10,6°: ``10/tan 10,6° − 10/tan 60°`` = 53,4345 − 5,7735
        = 47,6610 m; ``REST_5_35_6`` con 18°: 8,2477 m; ``DESD_10_45_6`` con 20°: 27,4748 − 10 =
        17,4748 m."""
        cases = ((EXPL, 10.6, 47.661025), (REST, 18.0, 8.2476777), (DESD, 20.0, 17.474774))
        for fixture, beta, expected in cases:
            with self.subTest(profile=fixture.name, beta=beta):
                found = benching.sector_berm(model_profile(fixture), beta)
                self.assertAlmostEqual(found, expected, delta=5e-6)
                self.assertAlmostEqual(found / dfx.imposed_berm_m(fixture, beta), 1.0,
                                       delta=1e-9)

    def test_never_less_than_the_minimum_of_the_profile(self) -> None:
        """RF-013-25: un talud impuesto igual o más empinado que el general del perfil (20,83° en
        ``REST_5_35_6``) deja la berma mínima, 6 m; justo en el general la fórmula da la mínima
        (≤ 10⁻⁹ m) y un poco más tendido, más."""
        profile = model_profile(REST)
        for beta in (89.0, 60.0, 35.0, 30.0, 25.0, 21.0):
            with self.subTest(beta=beta):
                self.assertEqual(benching.sector_berm(profile, beta), 6.0)
        self.assertAlmostEqual(benching.sector_berm(profile, profile.general_deg), 6.0,
                               delta=TOLERANCE_M)
        self.assertGreater(benching.sector_berm(profile, profile.general_deg - 0.01), 6.0)

    def test_general_slope_of_the_benches_does_not_pass_beta(self) -> None:
        """RF-013-25: con la berma dada, el talud general de los bancos ``atan(h/(h/tan α + B_s))``
        no pasa de β (y es β cuando la fórmula manda), en 300 perfiles y taludes aleatorios."""
        rng = np.random.default_rng(10)
        for _ in range(300):
            height, face, berm, beta = (float(rng.uniform(low, high)) for low, high in
                                        ((2.0, 20.0), (20.0, 80.0), (0.0, 25.0), (1.0, 85.0)))
            profile = design_model.BenchProfile("p", "P", height, face, berm, 100.0)
            found = benching.sector_berm(profile, beta)
            general = math.degrees(math.atan(
                height / (height / math.tan(math.radians(face)) + found)))
            self.assertGreaterEqual(found, berm)
            self.assertLessEqual(general, beta + 1e-9)
            if found > berm:
                self.assertAlmostEqual(general, beta, delta=1e-9)

    def test_fixture_profile_and_model_profile_agree(self) -> None:
        """Vale cualquier perfil con altura, cara y berma: el de ``design.model`` y el de pruebas
        dan el mismo número."""
        self.assertEqual(benching.sector_berm(REST, 10.6),
                         benching.sector_berm(model_profile(REST), 10.6))

    def test_does_not_look_at_the_surface(self) -> None:
        """Error 13: la berma no se deduce de la pendiente local de la envolvente; la función solo
        recibe el perfil y el talud impuesto."""
        self.assertEqual(list(inspect.signature(benching.sector_berm).parameters),
                         ["profile", "imposed_deg"])

    def test_invalid_imposed_slope_is_refused(self) -> None:
        """Un talud que no sea un número de 0 a 90 grados (ambos excluidos) es un error del
        programa (``ValueError``); la persona lo ve antes, en ``check_sector_slope``."""
        profile = model_profile(REST)
        for beta in (0.0, -5.0, 90.0, 120.0, math.nan, math.inf, -math.inf):
            with self.subTest(beta=beta):
                with self.assertRaises(ValueError):
                    benching.sector_berm(profile, beta)

    def test_a_ramp_of_beta_degrees_keeps_the_face_and_the_berm(self) -> None:
        """Medido en la rejilla: una rampa de 10,6° (1 × 2.000 celdas de 1 m, 74,8 bancos)
        escalonada en corte con la berma impuesta conserva la cara a 35° (la inclinación máxima
        entre celdas es ``tan α``, ≤ 10⁻⁹) y una parte plana de 19,58 m por banco (a ≤ 0,15 m); con
        la mínima de 6 m la cara se tendería a ``tan β·(1 + B·tan α/h)`` = 0,3443 (19°): el perfil
        ya no se cumple en ese talud (error 13)."""
        beta = 10.6
        ramp = dfx.PlaneCase(dfx.grid_from(1, 2000, 1.0), 140.0,
                             math.tan(math.radians(beta))).surface()
        benches = float(ramp.max() - ramp.min()) / REST.height_m
        berm = benching.sector_berm(model_profile(REST), beta)
        row = benching.bench_cut(ramp, REST.height_m, TAN_REST, berm, REST.anchor_m)
        levels = (row[0] - REST.anchor_m) / REST.height_m
        flat = np.abs(levels - np.round(levels)) * REST.height_m <= TOLERANCE_M
        self.assertAlmostEqual(max_slope(row), TAN_REST, delta=TOLERANCE_M)
        self.assertAlmostEqual(float(flat.sum()) / benches, berm, delta=0.15)
        narrow = benching.bench_cut(ramp, REST.height_m, TAN_REST, REST.berm_m, REST.anchor_m)
        self.assertAlmostEqual(max_slope(narrow),
                               math.tan(math.radians(beta)) * (1.0 + 6.0 * TAN_REST / 5.0),
                               delta=TOLERANCE_M)
        self.assertLess(max_slope(narrow), 0.35)


class ImplicatedCellsTest(unittest.TestCase):
    """RF-013-26, A7: las celdas cuyo sector tiene un talud distinto del de algún vecino."""

    def test_constant_map_has_none(self) -> None:
        """Con la misma pendiente en toda la rejilla no hay celdas implicadas."""
        found = benching.implicated_cells(np.full((6, 8), 0.5))
        self.assertEqual(found.dtype, np.bool_)
        self.assertEqual(found.shape, (6, 8))
        self.assertFalse(found.any())

    def test_two_and_three_bands(self) -> None:
        """Con dos franjas de 5 columnas, las dos columnas del borde (4 y 5), en todas las filas;
        con tres franjas (0,2, 0,5 y 0,2), las cuatro columnas de los dos bordes."""
        two = benching.implicated_cells(bands((6, 10), (0.2, 0.5)))
        self.assertEqual(sorted(set(np.nonzero(two)[1].tolist())), [4, 5])
        self.assertEqual(int(two.sum()), 12)
        three = benching.implicated_cells(bands((6, 15), (0.2, 0.5, 0.2)))
        self.assertEqual(sorted(set(np.nonzero(three)[1].tolist())), [4, 5, 9, 10])

    def test_row_border(self) -> None:
        """Un borde horizontal entre sectores implica las dos filas que lo tocan."""
        tangents = np.where(np.arange(8)[:, None] < 4, 0.2, 0.5) * np.ones((8, 6))
        found = benching.implicated_cells(tangents)
        self.assertEqual(sorted(set(np.nonzero(found)[0].tolist())), [3, 4])

    def test_domain_limits_the_cells_and_their_neighbours(self) -> None:
        """Solo cuentan las celdas del dominio y sus vecinas del dominio: con tres franjas
        (0,2, 0,5 y 0,9) y la tercera fuera del dominio, el borde entre la segunda y la tercera no
        implica nada."""
        tangents = bands((6, 15), (0.2, 0.5, 0.9))
        domain = np.ones((6, 15), dtype=bool)
        domain[:, 10:] = False
        found = benching.implicated_cells(tangents, domain)
        self.assertEqual(sorted(set(np.nonzero(found)[1].tolist())), [4, 5])
        self.assertTrue(domain[:, :10].all())  # el dominio no se toca

    def test_inputs_are_not_modified_and_the_result_is_new(self) -> None:
        """Principio 7: el mapa y el dominio no cambian y la máscara es un array nuevo."""
        tangents = bands((6, 10), (0.2, 0.5))
        domain = np.ones((6, 10), dtype=bool)
        before = (tangents.copy(), domain.copy())
        found = benching.implicated_cells(tangents, domain)
        self.assertTrue(np.array_equal(tangents, before[0]))
        self.assertTrue(np.array_equal(domain, before[1]))
        self.assertFalse(np.shares_memory(found, domain))

    def test_bad_input_is_a_program_error(self) -> None:
        """Un mapa que no es de 2 dimensiones, un dominio de otra forma o que no es booleano son
        ``ValueError``."""
        tangents = bands((6, 10), (0.2, 0.5))
        with self.assertRaises(ValueError):
            benching.implicated_cells(tangents[0])
        with self.assertRaises(ValueError):
            benching.implicated_cells(tangents, np.ones((6, 9), dtype=bool))
        with self.assertRaises(ValueError):
            benching.implicated_cells(tangents, np.ones((6, 10), dtype=np.int8))


def regularize(surface: np.ndarray, geometry: Any, slope: Any, **options: Any) -> Any:
    """La regularización de ``surface`` (el resultado del último paso)."""
    return finish(benching.regularize_steps(surface, geometry, slope, name="e1", **options))[1]


class RegularizeTest(unittest.TestCase):
    """RF-013-26, A7: la envolvente ascendente de la propia envolvente con la tangente más
    empinada de los sectores implicados."""

    def test_matches_the_oracle(self) -> None:
        """Con una pared entre un sector de 0,2 y otro de 0,5 (de hasta 6,9 m), el resultado es el
        del oráculo (Dijkstra sobre los 16 desplazamientos) con la pendiente 0,5 a ≤ 10⁻⁹ m."""
        surface, slope, geometry = walled()
        found = regularize(surface, geometry, slope)
        expected = oracles.dijkstra(surface, 0.5, 1.0, direction="up")
        self.assertLessEqual(float(np.abs(found.grid - expected).max()), TOLERANCE_M)
        self.assertEqual(found.tan, 0.5)
        self.assertEqual(found.cells, 2 * surface.shape[0])
        self.assertGreaterEqual(found.iterations, 1)
        self.assertLessEqual(found.violation, TOLERANCE_M)

    def test_removes_the_wall_and_never_raises_the_surface(self) -> None:
        """No pasa de la cota de ninguna celda (es la mayor superficie ``t``-Lipschitz por debajo
        de ella) y entre vecinas no pasa de ``t`` (por la escala 0,98644 del *chamfer*); antes
        había una pared de 6,9 m en 1 m."""
        surface, slope, geometry = walled()
        self.assertGreater(max_slope(surface), 6.0)
        found = regularize(surface, geometry, slope)
        self.assertLessEqual(float((found.grid - surface).max()), 0.0)
        self.assertLessEqual(max_slope(found.grid), SCALE * 0.5 + 1e-12)
        lowered = int(np.count_nonzero(found.grid < surface - TOLERANCE_M))
        self.assertEqual(found.lowered, lowered)
        self.assertGreater(found.lowered, 100)

    def test_regular_envelope_is_not_changed(self) -> None:
        """La envolvente de los sectores del *chamfer* (entrar cuesta con la pendiente de la celda
        de llegada) ya es 0,5-Lipschitz: la regularización no cambia ninguna celda más de 10⁻⁹ m ni
        baja ninguna, y repetirla tampoco."""
        _surface, slope, geometry = walled()
        crest = np.full(geometry.shape, np.inf)
        crest[0, :] = 150.0
        envelope = finish(envelopes.chamfer_steps(crest, geometry, slope, "down", name="e1"))[1]
        found = regularize(envelope.grid, geometry, slope)
        self.assertEqual(found.lowered, 0)
        self.assertLessEqual(float(np.abs(found.grid - envelope.grid).max()), TOLERANCE_M)
        again = regularize(found.grid, geometry, slope)
        self.assertEqual(again.lowered, 0)
        self.assertLessEqual(float(np.abs(again.grid - found.grid).max()), 1e-12)

    def test_idempotent_on_a_walled_surface(self) -> None:
        """Regularizar lo ya regularizado no cambia nada más de 10⁻¹² m ni baja ninguna celda."""
        surface, slope, geometry = walled()
        once = regularize(surface, geometry, slope)
        twice = regularize(once.grid, geometry, slope)
        self.assertEqual(twice.lowered, 0)
        self.assertLessEqual(float(np.abs(twice.grid - once.grid).max()), 1e-12)

    def test_one_slope_everywhere_has_nothing_to_do(self) -> None:
        """Con la misma pendiente en toda la rejilla (un escalar o un mapa constante) no hay
        sectores distintos: la superficie sale igual (copia), sin tangente, celdas ni vueltas."""
        surface, _slope, geometry = walled()
        for slope in (envelopes.SlopeField(0.5),
                      envelopes.SlopeField(np.full(surface.shape, 0.5))):
            with self.subTest(uniform=slope.uniform):
                found = regularize(surface, geometry, slope)
                self.assertIsNone(found.tan)
                self.assertEqual((found.cells, found.lowered, found.iterations), (0, 0, 0))
                self.assertTrue(np.array_equal(found.grid, surface))
                self.assertFalse(np.shares_memory(found.grid, surface))

    def test_steepest_of_the_implicated_sectors(self) -> None:
        """La tangente es la mayor de las celdas implicadas del dominio: con tres sectores (0,2,
        0,5 y 0,9) es 0,9; si el dominio deja fuera al tercero, 0,5 (y el resultado es el del
        oráculo con 0,5)."""
        surface, slope, geometry = walled((0.2, 0.5, 0.9), width=15)
        whole = regularize(surface, geometry, slope)
        self.assertEqual(whole.tan, 0.9)
        domain = np.ones(surface.shape, dtype=bool)
        domain[:, 30:] = False
        limited = regularize(surface, geometry, slope, domain=domain)
        self.assertEqual(limited.tan, 0.5)
        self.assertEqual(limited.cells, 2 * surface.shape[0])
        expected = oracles.dijkstra(surface, 0.5, 1.0, direction="up")
        self.assertLessEqual(float(np.abs(limited.grid - expected).max()), TOLERANCE_M)
        self.assertGreater(float(np.abs(whole.grid - limited.grid).max()), 0.1)

    def test_cells_without_data_stay_as_they_are(self) -> None:
        """Una celda sin dato (NaN), sin envolvente (``+inf``/``−inf``) o fuera del alcance sale
        como entró, sin avisos de numpy y sin propagar nada a las demás: las celdas con cota son las
        del oráculo con esas celdas sin semilla."""
        surface, slope, geometry = walled()
        surface[3:6, 8:12] = np.nan
        surface[10, 15:18] = np.inf
        surface[12, 2:4] = -np.inf
        before = surface.copy()
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            found = regularize(surface, geometry, slope)
        finite = np.isfinite(surface)
        self.assertTrue(np.array_equal(found.grid[~finite], surface[~finite], equal_nan=True))
        expected = oracles.dijkstra(surface, 0.5, 1.0, direction="up")
        self.assertLessEqual(float(np.abs(found.grid[finite] - expected[finite]).max()),
                             TOLERANCE_M)
        self.assertTrue(np.array_equal(surface, before, equal_nan=True))

    def test_inputs_are_not_modified(self) -> None:
        """Principio 7: la superficie, el mapa y el dominio no se tocan; el resultado es float64 y
        no comparte memoria; una superficie float32 se calcula como float64."""
        surface, slope, geometry = walled()
        tangents = np.array(slope.tan)
        domain = np.ones(surface.shape, dtype=bool)
        before = (surface.copy(), tangents.copy(), domain.copy())
        found = regularize(surface, geometry, slope, domain=domain)
        self.assertTrue(np.array_equal(surface, before[0]))
        self.assertTrue(np.array_equal(slope.tan, before[1]))
        self.assertTrue(np.array_equal(domain, before[2]))
        self.assertEqual(found.grid.dtype, np.float64)
        self.assertFalse(np.shares_memory(found.grid, surface))
        narrow = surface.astype(np.float32)
        same = regularize(narrow, geometry, slope)
        self.assertEqual(same.grid.dtype, np.float64)
        self.assertTrue(np.array_equal(same.grid, regularize(narrow.astype(np.float64), geometry,
                                                             slope).grid))

    def test_by_steps_and_closing_midway(self) -> None:
        """D-20: los ``Progress`` son de la fase «regularize», con avance creciente, y solo el
        último lleva la ``Regularization``; el presupuesto no cambia el resultado; cerrar a mitad
        no deja nada."""
        surface, slope, geometry = walled()
        steps, found = finish(benching.regularize_steps(surface, geometry, slope, name="e1",
                                                        budget_s=1e-9, cells_per_unit=100))
        self.assertGreater(len(steps), 20)
        done = [item.done for item in steps]
        self.assertEqual(done, sorted(done))
        for item in steps:
            self.assertIsInstance(item, progress_mod.Progress)
            self.assertEqual(item.phase, "regularize")
            self.assertIsNone(item.result)
            self.assertTrue(item.message)
        self.assertIsInstance(found, benching.Regularization)
        self.assertTrue(np.array_equal(found.grid, regularize(surface, geometry, slope).grid))
        before = surface.copy()
        half_way = benching.regularize_steps(surface, geometry, slope, budget_s=1e-9,
                                             cells_per_unit=100)
        self.assertIsNone(next(half_way).result)
        half_way.close()
        self.assertTrue(np.array_equal(surface, before))

    def test_bad_input_is_a_program_error(self) -> None:
        """Una superficie que no es de la forma de la rejilla, una rejilla de celdas no cuadradas,
        un mapa de pendientes u un dominio de otra forma, o un dominio no booleano son
        ``ValueError``."""
        surface, slope, geometry = walled()
        wide = gis.Grid(0.0, 24.0, 2.0, 1.0, 40, 24)
        domain = np.ones(surface.shape, dtype=bool)
        cases: list[tuple[Any, Any, Any, dict[str, Any]]] = [
            (surface[0], geometry, slope, {}),
            (surface[:, :-1], geometry, slope, {}),
            (surface, wide, slope, {}),
            (surface, geometry, envelopes.SlopeField(np.full((24, 39), 0.5)), {}),
            (surface, geometry, slope, {"domain": domain[:, :-1]}),
            (surface, geometry, slope, {"domain": domain.astype(np.int8)}),
        ]
        for index, (cells, grid, field, options) in enumerate(cases):
            with self.subTest(case=index):
                with self.assertRaises(ValueError):
                    list(benching.regularize_steps(cells, grid, field, **options))


def banded_stairs(*, berms: tuple[float, float] = (6.0, 20.0), rows: int = 24, cols: int = 48,
                  fill: bool = False, tan_face: Any = TAN_REST
                  ) -> tuple[np.ndarray, np.ndarray, Any]:
    """Un plano de pendiente 0,25 escalonado con ``REST_5_35_6`` y dos bermas, una por mitad
    (dos sectores con taludes distintos): da la superficie, el escalonado y la rejilla. En el borde
    entre las dos mitades el escalonado tiene una pared."""
    geometry = dfx.grid_from(rows, cols, 1.0)
    surface = dfx.PlaneCase(geometry, 140.0, 0.25).surface()
    berm_map = np.broadcast_to(np.where(np.arange(cols) < cols // 2, berms[0], berms[1]),
                               surface.shape)
    function = benching.bench_fill if fill else benching.bench_cut
    return surface, function(surface, REST.height_m, tan_face, berm_map, REST.anchor_m), geometry


def trim(stairs: np.ndarray, surface: np.ndarray, geometry: Any, tan_face: Any = TAN_REST,
         mesh_factor: Any = 1.0, sense: str = "cut", **options: Any) -> Any:
    """El recorte final de ``stairs`` (el resultado del último paso)."""
    return finish(benching.final_trim_steps(stairs, surface, geometry, tan_face, mesh_factor,
                                            sense, name="d1", **options))[1]


class FinalTrimTest(unittest.TestCase):
    """RF-013-27, A9: la envolvente ascendente del escalonado con la tangente de la cara por el
    factor de malla de cada celda."""

    def test_the_wall_is_there_before_the_trim(self) -> None:
        """Condición de partida: el escalonado de dos sectores tiene una pared de más de 60°."""
        _surface, stairs, _geometry = banded_stairs()
        self.assertGreater(max_slope(stairs), math.tan(math.radians(60.0)))

    def test_matches_the_oracle_and_no_face_passes_the_profile(self) -> None:
        """El resultado es el del oráculo (Dijkstra) con ``tan α`` a ≤ 10⁻⁹ m, no baja de ``S`` ni
        sube de lo escalonado, y la inclinación máxima entre vecinas es ``0,98644·tan α`` (< 35°),
        que es la cara del perfil."""
        surface, stairs, geometry = banded_stairs()
        found = trim(stairs, surface, geometry)
        expected = oracles.dijkstra(stairs, TAN_REST, 1.0, direction="up")
        self.assertLessEqual(float(np.abs(found.grid - expected).max()), TOLERANCE_M)
        self.assertGreaterEqual(float((found.grid - surface).min()), 0.0)
        self.assertLessEqual(float((found.grid - stairs).max()), 0.0)
        self.assertLessEqual(max_slope(found.grid), SCALE * TAN_REST + 1e-12)
        self.assertLess(math.degrees(math.atan(max_slope(found.grid))), REST.face_deg)
        self.assertEqual(found.clamped, 0)
        self.assertEqual(found.lowered, int(np.count_nonzero(found.grid < stairs - TOLERANCE_M)))
        self.assertGreater(found.lowered, 10)
        self.assertGreaterEqual(found.iterations, 1)
        self.assertLessEqual(found.violation, TOLERANCE_M)

    def test_fill_stays_below_the_surface(self) -> None:
        """En relleno (berma primero) el recorte también es la ascendente del escalonado: queda
        por debajo de lo escalonado y de ``S``, y sin caras de más de la cara del perfil."""
        surface, stairs, geometry = banded_stairs(fill=True)
        self.assertGreater(max_slope(stairs), TAN_REST)  # la pared pasa de la cara del perfil
        found = trim(stairs, surface, geometry, sense="fill")
        expected = oracles.dijkstra(stairs, TAN_REST, 1.0, direction="up")
        self.assertLessEqual(float(np.abs(found.grid - expected).max()), TOLERANCE_M)
        self.assertLessEqual(float((found.grid - stairs).max()), 0.0)
        self.assertLessEqual(float((found.grid - surface).max()), 0.0)
        self.assertLessEqual(max_slope(found.grid), SCALE * TAN_REST + 1e-12)
        self.assertEqual(found.clamped, 0)

    def test_mesh_factor_scales_the_face(self) -> None:
        """RF-013-27: la tangente es ``tan α·factor de malla`` por celda: con 0,8 en toda la
        rejilla, el oráculo con ``0,8·tan α`` y ninguna cara por encima; con 1 en la mitad oeste y
        0,8 en la este (un mapa; el recorte baja la mitad alta, la este), el oráculo con el mapa,
        distinto del de factor 1."""
        surface, stairs, geometry = banded_stairs()
        plain = trim(stairs, surface, geometry)
        for mesh in (0.8, bands(surface.shape, (1.0, 0.8), 24)):
            with self.subTest(uniform=np.ndim(mesh) == 0):
                found = trim(stairs, surface, geometry, mesh_factor=mesh)
                expected = oracles.dijkstra(stairs, TAN_REST * np.asarray(mesh), 1.0,
                                            direction="up")
                self.assertLessEqual(float(np.abs(found.grid - expected).max()), TOLERANCE_M)
                self.assertGreater(float(np.abs(found.grid - plain.grid).max()), 0.1)
        uniform = trim(stairs, surface, geometry, mesh_factor=0.8)
        self.assertLessEqual(max_slope(uniform.grid), SCALE * 0.8 * TAN_REST + 1e-12)

    def test_face_of_each_sector(self) -> None:
        """Con una cara por celda (60° en la mitad oeste, 35° en la este) la tangente sigue al mapa
        (oráculo con el mapa): el escalonado con las dos caras se recorta con cada una; la mitad
        este no pasa de 35° y se distingue del recorte con la cara de la oeste en todas partes."""
        face = bands((24, 48), (SQRT3, TAN_REST), 24)
        surface, stairs, geometry = banded_stairs(tan_face=face)
        found = trim(stairs, surface, geometry, tan_face=face)
        expected = oracles.dijkstra(stairs, face, 1.0, direction="up")
        self.assertLessEqual(float(np.abs(found.grid - expected).max()), TOLERANCE_M)
        self.assertLessEqual(max_slope(found.grid[:, 24:]), SCALE * TAN_REST + 1e-12)
        self.assertLessEqual(max_slope(found.grid), SCALE * SQRT3 + 1e-12)
        every_west = trim(stairs, surface, geometry, tan_face=SQRT3)
        self.assertGreater(float(np.abs(found.grid - every_west.grid).max()), 0.1)

    def test_cut_never_goes_below_the_surface(self) -> None:
        """RF-013-27: si la propia ``S`` tiene una pared que el recorte quitaría (``S`` de 150 m a
        la izquierda y 160 m a la derecha), el corte se devuelve a ``S`` en esas celdas: nunca por
        debajo, el resultado es ``máx(recorte, S)`` y se cuentan las celdas corregidas."""
        geometry = dfx.grid_from(12, 60, 1.0)
        surface = np.where(np.arange(60) < 30, 150.0, 160.0) * np.ones((12, 1))
        stairs = benching.bench_cut(surface, 5.0, TAN_REST, 6.0, 125.0)
        np.testing.assert_allclose(stairs, surface, rtol=0.0, atol=TOLERANCE_M)
        found = trim(stairs, surface, geometry)
        plain = oracles.dijkstra(stairs, TAN_REST, 1.0, direction="up")
        self.assertLessEqual(float(np.abs(found.grid - np.maximum(plain, surface)).max()),
                             TOLERANCE_M)
        self.assertGreaterEqual(float((found.grid - surface).min()), 0.0)
        self.assertEqual(found.clamped, int(np.count_nonzero(plain < surface - TOLERANCE_M)))
        self.assertGreater(found.clamped, 100)

    def test_fill_never_goes_above_the_surface(self) -> None:
        """RF-013-27: aunque el escalonado que llega esté por encima de ``S`` (no debería), el
        relleno sale ``mín(recorte, S)``: nunca por encima de ``S``."""
        geometry = dfx.grid_from(12, 60, 1.0)
        surface = np.where(np.arange(60) < 30, 150.0, 160.0) * np.ones((12, 1))
        stairs = surface + 3.0
        found = trim(stairs, surface, geometry, sense="fill")
        plain = oracles.dijkstra(stairs, TAN_REST, 1.0, direction="up")
        self.assertLessEqual(float(np.abs(found.grid - np.minimum(plain, surface)).max()),
                             TOLERANCE_M)
        self.assertLessEqual(float((found.grid - surface).max()), 0.0)
        self.assertEqual(found.clamped, int(np.count_nonzero(plain > surface + TOLERANCE_M)))
        self.assertGreater(found.clamped, 100)

    def test_nothing_moves_if_it_was_not_needed(self) -> None:
        """Un escalonado que ya no pasa de la cara (aquí, un plano de pendiente 0,25) sale igual,
        bit a bit, sin celdas bajadas ni corregidas."""
        surface, _stairs, geometry = banded_stairs()
        found = trim(surface, surface, geometry)
        self.assertTrue(np.array_equal(found.grid, surface))
        self.assertEqual((found.lowered, found.clamped), (0, 0))

    def test_cells_without_stairs_stay_without_data(self) -> None:
        """Las celdas sin escalonado (NaN) siguen sin dato, sin avisos de numpy, aunque su perfil
        tampoco tenga valor (NaN en los mapas); las demás son las del oráculo con esas celdas sin
        semilla. Si el perfil de una celda con escalonado no tiene valor, es ``ValueError``."""
        surface, stairs, geometry = banded_stairs()
        stairs[4:7, 10:14] = np.nan
        surface[4:7, 10:14] = np.nan
        face = np.full(stairs.shape, TAN_REST)
        mesh = np.ones(stairs.shape)
        face[4:7, 10:14] = np.nan
        mesh[4:7, 10:14] = np.nan
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            found = trim(stairs, surface, geometry, tan_face=face, mesh_factor=mesh)
        hole = np.isnan(stairs)
        self.assertTrue(np.isnan(found.grid[hole]).all())
        expected = oracles.dijkstra(stairs, TAN_REST, 1.0, direction="up")
        self.assertLessEqual(float(np.abs(found.grid[~hole] - expected[~hole]).max()),
                             TOLERANCE_M)
        face[0, 0] = np.nan
        with self.assertRaisesRegex(ValueError, "tan_face"):
            list(benching.final_trim_steps(stairs, surface, geometry, face, 1.0, "cut"))
        mesh[0, 1] = np.nan
        with self.assertRaisesRegex(ValueError, "mesh_factor"):
            list(benching.final_trim_steps(stairs, surface, geometry, TAN_REST, mesh, "cut"))

    def test_nothing_to_trim_without_stairs(self) -> None:
        """Sin ninguna celda escalonada (todo NaN) no hay nada que recortar: sale una copia sin
        dato, sin avisos de numpy, aunque el perfil tampoco tenga valor."""
        surface, stairs, geometry = banded_stairs()
        empty = np.full(stairs.shape, np.nan)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            found = trim(empty, surface, geometry, tan_face=math.nan, mesh_factor=math.nan)
        self.assertTrue(np.isnan(found.grid).all())
        self.assertFalse(np.shares_memory(found.grid, empty))
        self.assertEqual((found.iterations, found.lowered, found.clamped), (0, 0, 0))

    def test_inputs_are_not_modified(self) -> None:
        """Principio 7: el escalonado, la superficie y los mapas no se tocan; el resultado es
        float64 y no comparte memoria con ellos."""
        surface, stairs, geometry = banded_stairs()
        face = np.full(stairs.shape, TAN_REST)
        mesh = np.ones(stairs.shape)
        before = (surface.copy(), stairs.copy(), face.copy(), mesh.copy())
        found = trim(stairs, surface, geometry, tan_face=face, mesh_factor=mesh)
        for original, kept in zip((surface, stairs, face, mesh), before, strict=True):
            self.assertTrue(np.array_equal(original, kept))
            self.assertFalse(np.shares_memory(found.grid, original))
        self.assertEqual(found.grid.dtype, np.float64)

    def test_by_steps_and_closing_midway(self) -> None:
        """D-20: los ``Progress`` son de la fase «trim»; solo el último lleva el ``Trim``; el
        presupuesto no cambia el resultado; cerrar a mitad no deja nada."""
        surface, stairs, geometry = banded_stairs()
        steps, found = finish(benching.final_trim_steps(stairs, surface, geometry, TAN_REST, 1.0,
                                                        "cut", name="d1", budget_s=1e-9,
                                                        cells_per_unit=100))
        self.assertGreater(len(steps), 20)
        done = [item.done for item in steps]
        self.assertEqual(done, sorted(done))
        for item in steps:
            self.assertIsInstance(item, progress_mod.Progress)
            self.assertEqual(item.phase, "trim")
            self.assertIsNone(item.result)
            self.assertTrue(item.message)
        self.assertIsInstance(found, benching.Trim)
        self.assertTrue(np.array_equal(found.grid, trim(stairs, surface, geometry).grid))
        before = (surface.copy(), stairs.copy())
        half_way = benching.final_trim_steps(stairs, surface, geometry, TAN_REST, 1.0, "cut",
                                             budget_s=1e-9, cells_per_unit=100)
        self.assertIsNone(next(half_way).result)
        half_way.close()
        self.assertTrue(np.array_equal(surface, before[0]) and np.array_equal(stairs, before[1]))

    def test_sense_as_enum_or_text(self) -> None:
        """El sentido llega como ``BenchSense`` o como su texto («cut», «fill»)."""
        surface, stairs, geometry = banded_stairs()
        by_enum = trim(stairs, surface, geometry, sense=design_model.BenchSense.CUT)
        by_text = trim(stairs, surface, geometry, sense="cut")
        self.assertTrue(np.array_equal(by_enum.grid, by_text.grid))

    def test_bad_input_is_a_program_error(self) -> None:
        """Un sentido desconocido, un escalonado o una superficie que no son de la forma de la
        rejilla, celdas no cuadradas, un mapa de otra forma, una tangente de cara que no sea
        finita y mayor que 0 y un factor de malla fuera de (0; 1] son ``ValueError``."""
        surface, stairs, geometry = banded_stairs()
        wide = gis.Grid(0.0, 24.0, 2.0, 1.0, 48, 24)
        cases: list[tuple[Any, ...]] = [
            (stairs, surface, geometry, TAN_REST, 1.0, "sideways"),
            (stairs[0], surface, geometry, TAN_REST, 1.0, "cut"),
            (stairs, surface[:, :-1], geometry, TAN_REST, 1.0, "cut"),
            (stairs, surface, wide, TAN_REST, 1.0, "cut"),
            (stairs, surface, geometry, np.full((24, 47), TAN_REST), 1.0, "cut"),
            (stairs, surface, geometry, TAN_REST, np.full((24, 47), 1.0), "cut"),
            (stairs, surface, geometry, 0.0, 1.0, "cut"),
            (stairs, surface, geometry, -1.0, 1.0, "cut"),
            (stairs, surface, geometry, math.inf, 1.0, "cut"),
            (stairs, surface, geometry, TAN_REST, 0.0, "cut"),
            (stairs, surface, geometry, TAN_REST, 1.5, "cut"),
            (stairs, surface, geometry, TAN_REST, math.nan, "cut"),
            (stairs, surface, geometry, np.full(stairs.shape, 0.0), 1.0, "cut"),
            (stairs, surface, geometry, np.full(stairs.shape, -1.0), 1.0, "cut"),
            (stairs, surface, geometry, TAN_REST, np.full(stairs.shape, 0.0), "cut"),
            (stairs, surface, geometry, TAN_REST, np.full(stairs.shape, 1.5), "cut"),
        ]
        for index, args in enumerate(cases):
            with self.subTest(case=index):
                with self.assertRaises(ValueError):
                    list(benching.final_trim_steps(*args))


if __name__ == "__main__":
    unittest.main()
