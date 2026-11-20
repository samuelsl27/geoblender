# SPDX-License-Identifier: GPL-3.0-or-later
"""La sección tipo de la pista: huella, lados y cotas (spec 017, T12; HU-017-1; RF-017-20 y RF-017-06; CE-017-06; RNF-017-06; plan 017 §5.4 A6 y A7, §5.7
P-10 y §5.8 H-3): ``road_section.section_cells`` (la huella de la calzada, el arcén y el caballón sobre ``quarry.axis_abscissa`` del eje denso, con extremos
planos, la distancia lateral con signo de cada celda, el lado del arcén —el de mayor cota del terreno de partida— y la cota de la rasante en su abscisa).

Los valores esperados salen **a mano** (``tests.support.road_data.straight_section_by_hand``: fórmulas cerradas de un eje recto de oeste a este) y por
**fuerza bruta** (``road_data.oracle_section``: el tramo más próximo de la poligonal densa uno a uno, sin teselas ni ``searchsorted``) en las mismas celdas,
**no** de llamar al código bajo prueba. Todo es sintético, en el dominio y sin Blender; el caso de referencia, en ``tests/referencia/des/test_ref_road_section``
y lo que pasa de 1 s (2 km, 61 curvas, en la rejilla de 2,81 M celdas), en ``milestone_road_section``.
"""

from __future__ import annotations

import hashlib
import math
import unittest
from collections.abc import Callable
from typing import Any
from unittest import mock

import numpy as np

from tests.support import road_data as rd
from tests.support.package import import_geoblender

road_axis = import_geoblender("design.road_axis")
road_section = import_geoblender("design.road_section")

TOL = rd.SECTION_CHECK_TOL_M
"""Metros: lo que RF-017-20 pide de la sección frente al cálculo a mano en las mismas celdas."""
GRID = rd.GRID
PROFILE = rd.PROFILE
"""El perfil de referencia: calzada 10,5 m (3,5 × 3), arcén 0 m y caballón 1 m (sección de 11,5 m)."""
WIDE = rd.profile_with(shoulder_m=1.5)
"""El mismo con un arcén de 1,5 m: para distinguir el arcén del caballón por su ancho."""
Z_OF = Callable[[np.ndarray, np.ndarray], np.ndarray]


def flat(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Un terreno llano: cotas iguales a los dos lados."""
    return np.full(np.shape(x), 150.0)


def tilted(cross_pct: float) -> Z_OF:
    """El plano de la rampa (4 % al este) con una pendiente transversal ``cross_pct`` % al norte (positiva: el norte, a la izquierda del eje, más alto)."""
    return lambda x, y: rd.RAMP_Z0_M + rd.RAMP_SLOPE_PCT / 100.0 * x + cross_pct / 100.0 * (y - rd.RAMP_AXIS_Y_M)


SADDLE_X_M = 200.505
"""La x donde cambia de signo la pendiente transversal de la silla: a 5 mm del centro de una columna de celdas (x = 200,5), para que ni un corrimiento de 1 cm del
punto del eje donde se compara el terreno pase inadvertido."""


def saddle(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Una silla (bilineal, que la interpolación bilineal reproduce exacta): la pendiente transversal del eje de la rampa cambia de signo en x = 200,505."""
    return 150.0 + 0.1 * (x - SADDLE_X_M) * (y - rd.RAMP_AXIS_Y_M)


def diagonal(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Un plano que sube al noreste: en un eje que gira de este a norte, el lado más alto pasa de la izquierda a la derecha."""
    return 100.0 + 0.2 * (x + y)


def diagonal_nw(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Un plano que sube al noroeste: en un eje que gira de este a sur, el lado más alto pasa de la izquierda a la derecha."""
    return 100.0 + 0.2 * (y - x)


def ground(z_of: Z_OF, grid: Any = GRID) -> np.ndarray:
    """El terreno de fórmula ``z_of`` (locales) en los centros de ``grid``."""
    return np.asarray(z_of(*rd.local_centers(grid)), dtype=np.float64)


def straight_axis(start: tuple[float, float] = rd.RAMP_ORIGIN, end: tuple[float, float] = rd.RAMP_DESTINATION) -> Any:
    """El eje recto de ``start`` a ``end`` (locales) como el de una pista (radio 20 m, Rmín 12 m, estaciones cada metro)."""
    return road_axis.axis_of(rd.absolute((start, end)), 20.0, 12.0, 1.0)


def section_of(axis: Any, z_of: Z_OF, profile: Any = PROFILE, *, window: Any = None, grid: Any = GRID) -> Any:
    """La sección de ``axis`` con el perfil ``profile`` sobre el terreno ``z_of`` (``window`` ``None``: la caja del corredor)."""
    return road_section.section_cells(axis, profile.carriageway_m, profile.shoulder_m, profile.berm_m, ground(z_of, grid), grid, window)


def crop(found: Any, window: tuple[slice, slice]) -> Any:
    """Lo calculado a mano en toda la rejilla, recortado a ``window``."""
    return rd.SectionByHand(found.kind[window], found.side[window], found.sigma[window], found.lateral[window])


def digest(array: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


class SectionAssertions(unittest.TestCase):
    def assert_same_section(self, section: Any, expected: Any, *, tolerance: float = TOL) -> None:
        """Las mismas celdas, clases y lados que ``expected`` y la abscisa y la distancia lateral a ``tolerance`` m (``nan`` fuera de la huella)."""
        np.testing.assert_array_equal(section.kind, expected.kind)
        np.testing.assert_array_equal(section.side, expected.side)
        np.testing.assert_array_equal(section.cells, expected.cells)
        np.testing.assert_allclose(section.sigma, expected.sigma, rtol=0.0, atol=tolerance, equal_nan=True)
        np.testing.assert_allclose(section.lateral, expected.lateral, rtol=0.0, atol=tolerance, equal_nan=True)


class StraightAxisTest(SectionAssertions):
    def test_the_footprint_of_a_200_m_axis_measures_200_m_and_not_the_211_5_m_of_a_buffer(self) -> None:
        """RF-017-20, CE-017-06 (error 20): con la sección de 11,5 m, la huella de un eje recto de 200 m mide, a lo largo del eje, 200 m con un error ≤ 1
        celda —con extremos planos— y no los 211,5 m (200 + 2 × 5,75) de un *buffer* de extremos redondos."""
        axis = straight_axis()
        section = section_of(axis, flat)
        self.assertAlmostEqual(axis.length_m, 200.0, delta=1e-9)
        self.assertLessEqual(abs(section.length_m - 200.0), GRID.dx)
        self.assertGreater(abs(section.length_m - 211.5), 10.0)
        columns = np.flatnonzero(section.cells.any(axis=0)) + section.window[1].start
        self.assertEqual((int(columns.min()), int(columns.max())), (100, 299))  # los centros de 100,5 a 299,5 m: 200 columnas con ±1 celda de error
        self.assertEqual(section.cell_count, 11 * 200)

    def test_the_classes_the_sides_and_the_distances_are_the_ones_of_the_hand_calculation_in_every_cell(self) -> None:
        """RF-017-20, CE-017-06: la calzada, el arcén y el caballón del perfil, el lado, la abscisa y la distancia lateral son, a ≤ 10⁻⁹ m, los del cálculo
        a mano **en las mismas celdas** (fórmulas cerradas de un eje recto) con terrenos llanos, con pendiente transversal a un lado y al otro y con una
        silla que cambia el lado a media pista, y con un arcén de 0 y de 1,5 m."""
        axis = straight_axis()
        terrains = {"llano": flat, "norte más alto": tilted(20.0), "sur más alto": tilted(-20.0), "silla": saddle}
        for name, z_of in terrains.items():
            for label, profile in (("arcén 0 m", PROFILE), ("arcén 1,5 m", WIDE)):
                with self.subTest(terreno=name, perfil=label):
                    section = section_of(axis, z_of, profile)
                    by_hand = rd.straight_section_by_hand(GRID, z_of, profile.carriageway_m, profile.shoulder_m, profile.berm_m)
                    self.assert_same_section(section, crop(by_hand, section.window))
                    self.assertEqual(int(section.cells.sum()), int(by_hand.cells.sum()), "la sección entera cabe en la ventana")

    def test_with_equal_heights_on_both_sides_the_berm_goes_on_the_right_in_the_direction_of_travel(self) -> None:
        """RF-017-20, D-12, CE-017-06: con cotas iguales a ambos lados, el caballón a la derecha en el sentido de la marcha (la marcha, hacia el este: la
        derecha es el sur) y el arcén —con 1,5 m— a la izquierda; ningún caballón a la izquierda."""
        axis = straight_axis()
        section = section_of(axis, flat, WIDE)
        berm = section.kind == road_section.SectionClass.BERM
        shoulder = section.kind == road_section.SectionClass.SHOULDER
        self.assertEqual(int(berm.sum()), 200)  # una fila de 1 m de caballón
        self.assertEqual(int(shoulder.sum()), 400)  # dos filas de arcén (1,5 m, con centros a 5,5 y 6,5 m)
        self.assertTrue(bool((section.side[berm] == road_section.RIGHT).all()))
        self.assertTrue(bool((section.side[shoulder] == road_section.LEFT).all()))
        row, _ = rd.cell_of((150.0, 194.5))  # el centro del caballón: 5,5 m al sur del eje
        self.assertEqual(int(berm[row - section.window[0].start, :].sum()), 200)  # toda la fila de 200 celdas es caballón

    def test_with_a_cross_slope_the_shoulder_goes_on_the_higher_side_at_the_foot_of_the_slope(self) -> None:
        """RF-017-20, D-12, CE-017-06: con una pendiente transversal, el arcén en el lado de mayor cota del terreno de partida (al pie del talud) y el
        caballón en el otro: el norte más alto (a la izquierda en la marcha hacia el este) da el arcén a la izquierda; el sur más alto, a la derecha."""
        axis = straight_axis()
        for cross, shoulder_side, berm_side in ((20.0, road_section.LEFT, road_section.RIGHT), (-20.0, road_section.RIGHT, road_section.LEFT)):
            with self.subTest(cross_pct=cross):
                section = section_of(axis, tilted(cross), WIDE)
                shoulder = section.kind == road_section.SectionClass.SHOULDER
                berm = section.kind == road_section.SectionClass.BERM
                self.assertEqual((int(shoulder.sum()), int(berm.sum())), (400, 200))
                self.assertTrue(bool((section.side[shoulder] == shoulder_side).all()))
                self.assertTrue(bool((section.side[berm] == berm_side).all()))

    def test_the_widths_are_the_carriageway_the_shoulder_and_the_berm_of_the_profile(self) -> None:
        """RF-017-20, P-10: el eje es el centro de la calzada: de −(f·A/2 + a) a +(f·A/2 + c) en el lado que toque. Con calzada 10,5 m, arcén 1,5 m y caballón
        1 m y el norte más alto: la distancia lateral (positiva a la derecha) va de −6,5 m (el arcén, a la izquierda) a +5,5 m (el caballón, a la derecha), con
        2.000 celdas de calzada (|d| ≤ 5,25 m), 400 de arcén y 200 de caballón."""
        section = section_of(straight_axis(), tilted(20.0), WIDE)
        lateral = section.lateral[section.cells]
        self.assertAlmostEqual(float(lateral.min()), -6.5, delta=TOL)
        self.assertAlmostEqual(float(lateral.max()), 5.5, delta=TOL)
        counts = {kind: section.count_of(kind) for kind in road_section.SectionClass}
        self.assertEqual(counts[road_section.SectionClass.CARRIAGEWAY], 2000)
        self.assertEqual(counts[road_section.SectionClass.SHOULDER], 400)
        self.assertEqual(counts[road_section.SectionClass.BERM], 200)
        self.assertEqual(counts[road_section.SectionClass.OUTSIDE], section.kind.size - 2600)
        carriageway = section.kind == road_section.SectionClass.CARRIAGEWAY
        self.assertLessEqual(float(np.abs(section.lateral[carriageway]).max()), 5.25 + TOL)
        self.assertAlmostEqual(section.area_m2, 2600.0 * GRID.cell_area, delta=TOL)

    def test_the_cells_outside_the_footprint_have_no_class_side_abscissa_or_distance(self) -> None:
        """RF-017-20: fuera de la huella, la clase es 0 (fuera), el lado 0 y la abscisa y la distancia son NaN; dentro, finitas."""
        section = section_of(straight_axis(), flat)
        outside = ~section.cells
        self.assertTrue(bool(outside.any()))
        self.assertTrue(bool((section.kind[outside] == road_section.SectionClass.OUTSIDE).all()))
        self.assertTrue(bool((section.side[outside] == 0).all()))
        self.assertTrue(bool(np.isnan(section.sigma[outside]).all()) and bool(np.isnan(section.lateral[outside]).all()))
        self.assertTrue(bool(np.isfinite(section.sigma[section.cells]).all()) and bool(np.isfinite(section.lateral[section.cells]).all()))


class SideDecisionTest(SectionAssertions):
    def test_the_side_of_the_shoulder_is_decided_at_the_abscissa_of_each_cell(self) -> None:
        """RF-017-20: en cada abscisa, el lado de mayor cota del terreno lleva el arcén: con una silla cuya pendiente transversal cambia de signo en x =
        200,505 (σ = 100,505 m, a 5 mm del centro de una columna), el caballón va a la izquierda antes de ella (el sur es más alto: arcén a la derecha) y a la derecha
        después, y ninguna columna mezcla los dos lados."""
        section = section_of(straight_axis(), saddle, WIDE)
        berm = section.kind == road_section.SectionClass.BERM
        sigma = section.sigma
        self.assertTrue(bool((section.side[berm & (sigma < SADDLE_X_M - 100.0)] == road_section.LEFT).all()))
        self.assertTrue(bool((section.side[berm & (sigma > SADDLE_X_M - 100.0)] == road_section.RIGHT).all()))
        self.assertEqual(int((berm & (sigma < SADDLE_X_M - 100.0)).sum()), 101)  # los centros de σ = 0,5 a 100,5 m
        self.assertEqual(int((berm & (sigma > SADDLE_X_M - 100.0)).sum()), 99)  # y los de 101,5 a 199,5 m
        for column in range(section.cells.shape[1]):
            sides = set(section.side[berm[:, column], column].tolist())
            self.assertLessEqual(len(sides), 1)

    def test_a_side_without_data_counts_as_equal_heights_and_the_berm_goes_on_the_right(self) -> None:
        """RF-017-20, D-12: si falta el terreno a un lado (sin dato) no se puede comparar y se trata como cotas iguales: el caballón a la derecha, aunque
        con dato el sur fuera más alto (el arcén iría a la derecha)."""
        axis = straight_axis()
        terrain = ground(tilted(-20.0))
        with_data = road_section.section_cells(axis, WIDE.carriageway_m, WIDE.shoulder_m, WIDE.berm_m, terrain, GRID, None)
        berm = with_data.kind == road_section.SectionClass.BERM
        self.assertTrue(bool((with_data.side[berm] == road_section.LEFT).all()))
        gap = terrain.copy()
        gap[rd.cell_of((150.0, 197.0))[0]:, :] = np.nan  # el sur, desde 3 m del eje, sin dato
        found = road_section.section_cells(axis, WIDE.carriageway_m, WIDE.shoulder_m, WIDE.berm_m, gap, GRID, with_data.window)
        berm = found.kind == road_section.SectionClass.BERM
        self.assertEqual(int(berm.sum()), 200)
        self.assertTrue(bool((found.side[berm] == road_section.RIGHT).all()))

    def test_the_terrain_is_interpolated_between_the_cell_centres(self) -> None:
        """RF-017-20: «también por interpolación»: el terreno a ±f·A/2 del eje no es el de la celda que contiene el punto sino el interpolado entre cuatro
        centros. A 5,25 m al sur del eje (y = 194,75) la celda que lo contiene es la de centro 194,5; solo se sube 2 cm la fila de centro 195,5, que pesa
        un cuarto en la interpolación: el sur gana por 5 mm (arcén a la derecha); con el valor de la celda más próxima habría un empate (arcén a la
        izquierda)."""
        terrain = ground(flat)
        terrain[rd.cell_of((150.0, 195.5))[0], :] += 0.02
        axis = straight_axis()
        found = road_section.section_cells(axis, WIDE.carriageway_m, WIDE.shoulder_m, WIDE.berm_m, terrain, GRID, None)
        shoulder = found.kind == road_section.SectionClass.SHOULDER
        self.assertEqual(int(shoulder.sum()), 400)
        self.assertTrue(bool((found.side[shoulder] == road_section.RIGHT).all()))


    def test_the_terrain_is_compared_at_the_edge_of_the_carriageway_and_not_further_out(self) -> None:
        """RF-017-20: «comparando las celdas a ±f·A/2 del eje»: la comparación se hace en el borde de la calzada (a 5,25 m) y no en el del arcén o el caballón (a
        6,75 m y 6,25 m). Un terreno con una cuneta a más de 5 m al sur y una ladera suave al norte: a 5,25 m el sur es más alto (el arcén, a la derecha); más
        afuera, el norte lo sería."""
        terrain = ground(flat)
        for k in range(10):  # d = k + 0,5 m al sur y al norte del eje (y = 200): el sur sube 0,1 m por metro hasta 4,5 m y es una cuneta de 5,5 m en adelante
            south, north = rd.cell_of((150.0, 199.5 - k))[0], rd.cell_of((150.0, 200.5 + k))[0]
            terrain[south, :] += 0.1 * (k + 0.5) if k < 5 else 0.0
            terrain[north, :] += 0.01 * (k + 0.5)
        found = road_section.section_cells(straight_axis(), WIDE.carriageway_m, WIDE.shoulder_m, WIDE.berm_m, terrain, GRID, None)
        shoulder = found.kind == road_section.SectionClass.SHOULDER
        self.assertEqual(int(shoulder.sum()), 400)
        self.assertTrue(bool((found.side[shoulder] == road_section.RIGHT).all()))

    def test_a_side_outside_the_grid_counts_as_equal_heights_and_the_berm_goes_on_the_right(self) -> None:
        """RF-017-20, D-12: un eje a 3 m del borde norte de la rejilla tiene su lado izquierdo (a 5,25 m) fuera de ella, sin terreno: no se puede comparar y se
        trata como cotas iguales: el caballón a la derecha en toda la pista (y no el lado con dato, más alto que «nada»)."""
        axis = straight_axis((100.0, 397.0), (300.0, 397.0))
        section = section_of(axis, flat, WIDE)
        berm = section.kind == road_section.SectionClass.BERM
        self.assertEqual(int(berm.sum()), 200)
        self.assertTrue(bool((section.side[berm] == road_section.RIGHT).all()))
        self.assertEqual(section.cell_count, 9 * 200)  # tres filas al norte (hasta el borde de la rejilla) y seis al sur

    def test_an_axis_through_the_cell_centres_gives_the_hand_calculation_and_the_axis_cells_go_to_the_right(self) -> None:
        """RF-017-20: con el eje por los centros de una fila (y = 200,5 m), las celdas de distancia lateral 0 son calzada y se cuentan del lado derecho
        (``d ≥ 0``); la calzada (|d| ≤ 5,25 m: once filas), el arcén y el caballón son, a ≤ 10⁻⁹ m, los del cálculo a mano en las mismas celdas."""
        start, end = (100.0, 200.5), (300.0, 200.5)
        axis = straight_axis(start, end)
        for name, z_of in (("llano", flat), ("norte más alto", tilted(20.0))):
            with self.subTest(terreno=name):
                section = section_of(axis, z_of, WIDE)
                by_hand = rd.straight_section_by_hand(GRID, z_of, WIDE.carriageway_m, WIDE.shoulder_m, WIDE.berm_m, start=start, end=end)
                self.assert_same_section(section, crop(by_hand, section.window))
                on_axis = np.isclose(section.lateral, 0.0, atol=TOL)
                self.assertEqual(int(on_axis.sum()), 200)
                self.assertTrue(bool((section.side[on_axis] == road_section.RIGHT).all()))
                self.assertTrue(bool((section.kind[on_axis] == road_section.SectionClass.CARRIAGEWAY).all()))
                self.assertEqual(section.count_of(road_section.SectionClass.CARRIAGEWAY), 11 * 200)


class ObliqueAxisTest(SectionAssertions):
    START = (100.0, 100.0)
    END = (250.0, 180.0)

    def axis_and_path(self) -> tuple[Any, np.ndarray, np.ndarray]:
        axis = straight_axis(self.START, self.END)
        stations = rd.stations_by_hand(axis.length_m, 1.0)
        path, _ = axis.sample(stations)
        return axis, path, stations

    def test_an_oblique_axis_gives_the_brute_force_section_in_the_same_cells(self) -> None:
        """RF-017-20: un eje recto oblicuo (170 m a 62° del norte) da, a ≤ 10⁻⁹ m, la sección de la fuerza bruta (el tramo más próximo uno a uno) en las mismas
        celdas, con el lado del arcén de un plano inclinado."""
        axis, path, stations = self.axis_and_path()
        z_of = tilted(25.0)
        section = section_of(axis, z_of, WIDE)
        expected = rd.oracle_section(GRID, section.window, path, stations, z_of, WIDE.carriageway_m, WIDE.shoulder_m, WIDE.berm_m)
        self.assert_same_section(section, expected)
        self.assertGreater(section.cell_count, 170 * 12)

    def test_the_ends_are_flat_and_perpendicular_to_the_axis(self) -> None:
        """RF-017-20 (error 20): extremos planos perpendiculares al eje: todas las celdas de la huella tienen su proyección sobre el eje entre sus dos
        extremos (0 ≤ (p − A)·u ≤ L) y la longitud de la huella es la del eje, con un error ≤ 1 celda (diagonal incluida: ≤ √2 celdas)."""
        axis, _path, _ = self.axis_and_path()
        section = section_of(axis, flat, PROFILE)
        a = rd.absolute((self.START,))[0]
        b = rd.absolute((self.END,))[0]
        length = float(np.hypot(*(b - a)))
        u = (b - a) / length
        rows, cols = np.nonzero(section.cells)
        x = GRID.west + (cols + section.window[1].start + 0.5) * GRID.dx
        y = GRID.north - (rows + section.window[0].start + 0.5) * GRID.dy
        along = (x - a[0]) * u[0] + (y - a[1]) * u[1]
        self.assertGreaterEqual(float(along.min()), -TOL)
        self.assertLessEqual(float(along.max()), length + TOL)
        self.assertLessEqual(abs(section.length_m - length), math.sqrt(2.0) * GRID.dx)
        self.assertLessEqual(abs(float(along.max() - along.min()) - length), math.sqrt(2.0) * GRID.dx)


class CurvedAxisTest(SectionAssertions):
    LEFT_TURN = ((60.0, 60.0), (100.0, 60.0), (100.0, 100.0))  # de este a norte: giro a la izquierda, centro en (80, 80)
    RIGHT_TURN = ((60.0, 140.0), (100.0, 140.0), (100.0, 100.0))  # de este a sur: giro a la derecha, centro en (80, 120)

    def corner(self, points: tuple[tuple[float, float], ...]) -> Any:
        return road_axis.axis_of(rd.absolute(points), 20.0, 12.0, 1.0)

    def test_a_curved_axis_gives_the_brute_force_section_in_the_same_cells_with_the_side_changing_along_the_curve(self) -> None:
        """RF-017-20: un eje de 71,416 m con un arco de 90° y R = 20 m (a izquierda y a derecha), sobre un plano que sube al noreste (giro a la izquierda) o al
        noroeste (a la derecha), de modo que el lado más alto pasa de un lado al otro a lo largo de la curva, da, a ≤ 10⁻⁹ m, la sección de la fuerza bruta en las
        mismas celdas: clases, lados, abscisa y distancia."""
        for name, points, z_of in (("izquierda", self.LEFT_TURN, diagonal), ("derecha", self.RIGHT_TURN, diagonal_nw)):
            with self.subTest(giro=name):
                axis = self.corner(points)
                stations = rd.stations_by_hand(axis.length_m, 1.0)
                path, _ = axis.sample(stations)
                section = section_of(axis, z_of, WIDE)
                expected = rd.oracle_section(GRID, section.window, path, stations, z_of, WIDE.carriageway_m, WIDE.shoulder_m, WIDE.berm_m)
                self.assert_same_section(section, expected)
                berm = section.kind == road_section.SectionClass.BERM
                self.assertEqual(len(set(section.side[berm].tolist())), 2, "el caballón cambia de lado a lo largo de la curva")

    def test_the_sign_is_positive_to_the_right_of_the_direction_of_travel_around_a_curve(self) -> None:
        """RF-017-20: en el arco, la distancia lateral con signo es positiva a la derecha: en un giro a la izquierda el centro de curvatura (80, 80) queda a
        la izquierda y las celdas más cerca de él que el radio son negativas (y las de fuera, positivas); en un giro a la derecha, al revés. La distancia
        al eje es |R − r| (a ≤ la flecha de la cuerda de 1 m, 6,25 mm, y la unión de los vértices: 1 cm)."""
        for name, points, centre, inside in (("izquierda", self.LEFT_TURN, (80.0, 80.0), -1.0), ("derecha", self.RIGHT_TURN, (80.0, 120.0), 1.0)):
            with self.subTest(giro=name):
                section = section_of(self.corner(points), flat, WIDE)
                rows, cols = np.nonzero(section.cells)
                x = (cols + section.window[1].start + 0.5) * GRID.dx
                y = GRID.nrows * GRID.dy - (rows + section.window[0].start + 0.5) * GRID.dy
                radius = np.hypot(x - centre[0], y - centre[1])
                on_arc = (section.sigma[rows, cols] > 20.0 + 1.0) & (section.sigma[rows, cols] < 20.0 + 0.5 * math.pi * 20.0 - 1.0)
                lateral = section.lateral[rows, cols]
                clear = on_arc & (np.abs(radius - 20.0) > 0.05)
                self.assertGreater(int(clear.sum()), 100)
                self.assertTrue(bool((np.sign(lateral[clear]) == np.where(radius[clear] < 20.0, inside, -inside)).all()))
                np.testing.assert_allclose(np.abs(lateral[on_arc]), np.abs(radius[on_arc] - 20.0), rtol=0.0, atol=0.01)

    def test_the_abscissa_is_the_arc_length_of_the_axis_not_the_length_of_its_chords(self) -> None:
        """RF-017-20, A7: la abscisa σ de una celda es la del eje (la longitud de arco, la de las estaciones de la rasante) y no la de la poligonal de cuerdas
        de 1 m, que en 31,4 m de arco de R = 20 m es 3,2 mm más corta: en el tramo recto tras el arco (el norte desde (100, 80)), σ = 20 + π·20/2 + (y − 80)
        a ≤ 10⁻⁶ m; y la longitud de la huella es la del eje con un error ≤ 1 celda."""
        axis = self.corner(self.LEFT_TURN)
        section = section_of(axis, flat, PROFILE)
        rows, cols = np.nonzero(section.cells)
        x = (cols + section.window[1].start + 0.5) * GRID.dx
        y = GRID.nrows * GRID.dy - (rows + section.window[0].start + 0.5) * GRID.dy
        after = (y > 82.0) & (np.abs(x - 100.0) < 5.0)
        self.assertGreater(int(after.sum()), 50)
        np.testing.assert_allclose(section.sigma[rows, cols][after], 20.0 + 0.5 * math.pi * 20.0 + (y[after] - 80.0), rtol=0.0, atol=1e-6)
        self.assertAlmostEqual(axis.length_m, 71.415927, delta=1e-6)
        # una celda de menos que el eje (los centros de las primeras y de las últimas celdas caen a 0,5 m de sus extremos), medida sobre el **arco** y no sobre las
        # cuerdas (que la acortarían 3,2 mm), con el ruido de 10⁻⁹ m de las coordenadas absolutas
        self.assertAlmostEqual(section.length_m, axis.length_m - GRID.dx, delta=1e-6)


class LevelsTest(SectionAssertions):
    def test_the_level_of_every_cell_is_the_grade_line_at_its_abscissa_and_the_berm_has_no_height(self) -> None:
        """RF-017-20: la cota de cada celda es la rasante en su abscisa (``np.interp``) a ≤ 10⁻⁹ m; el caballón es solo una anchura (su cordón no cabe en la
        rejilla): las celdas del caballón y las de la calzada de la misma abscisa tienen la misma cota. Fuera de la huella, NaN."""
        axis = straight_axis()
        section = section_of(axis, tilted(20.0), WIDE)
        stations = axis.stations
        line = 120.0 + 0.04 * stations + 0.001 * stations ** 2 / 200.0  # una rasante que no es una recta
        levels = section.levels(stations, line)
        sigma = section.sigma[section.cells]
        np.testing.assert_allclose(levels[section.cells], 120.0 + 0.04 * sigma + 0.001 * sigma ** 2 / 200.0, rtol=0.0, atol=1e-5)
        np.testing.assert_allclose(levels[section.cells], np.interp(sigma, stations, line), rtol=0.0, atol=TOL)
        self.assertTrue(bool(np.isnan(levels[~section.cells]).all()))
        berm = section.kind == road_section.SectionClass.BERM
        carriageway = section.kind == road_section.SectionClass.CARRIAGEWAY
        used = np.flatnonzero(section.cells.any(axis=0))  # las 200 columnas de la huella dentro de la ventana, que es algo mayor
        self.assertEqual(used.size, 200)
        for column in (int(used[0]), int(used[57]), int(used[120]), int(used[-1])):
            rows = berm[:, column]
            same = carriageway[:, column]
            self.assertEqual(int(rows.sum()), 1)
            np.testing.assert_allclose(levels[rows, column], levels[same, column][0], rtol=0.0, atol=0.0)
            self.assertEqual(float(np.ptp(levels[section.cells[:, column], column])), 0.0)

    def test_levels_need_stations_and_a_grade_line_of_the_same_length(self) -> None:
        """RF-017-20: las estaciones y la rasante de una cota por estación (``ValueError``: error del programa)."""
        section = section_of(straight_axis(), flat)
        with self.assertRaises(ValueError):
            section.levels(np.array([0.0, 100.0, 200.0]), np.array([1.0, 2.0]))
        with self.assertRaises(ValueError):
            section.levels(np.array([0.0]), np.array([1.0]))


class WindowAndStepsTest(SectionAssertions):
    def test_a_smaller_window_clips_the_section_to_the_same_cells(self) -> None:
        """RF-017-20: con una ventana que corta la huella (la mitad este de la pista), la sección es, byte a byte, la parte de la de la rejilla entera: la
        abscisa, el lado y la clase de cada celda no dependen de la ventana."""
        axis = straight_axis()
        whole = section_of(axis, tilted(20.0), WIDE, window=(slice(0, GRID.nrows), slice(0, GRID.ncols)))
        half = (slice(150, 250), slice(200, 320))
        clipped = section_of(axis, tilted(20.0), WIDE, window=half)
        self.assertEqual(clipped.window, half)
        for name in ("kind", "side"):
            np.testing.assert_array_equal(getattr(clipped, name), getattr(whole, name)[half])
        for name in ("sigma", "lateral"):
            self.assertEqual(digest(getattr(clipped, name)), digest(getattr(whole, name)[half]))
        self.assertLess(clipped.cell_count, whole.cell_count)

    def test_the_default_window_is_the_corridor_window_of_the_axis(self) -> None:
        """RF-017-20: sin ventana, la caja del corredor (la de la huella: la del eje ± la semianchura máxima, recortada a la rejilla), que contiene toda la
        huella: la misma que :func:`section_window` y la misma sección que con la rejilla entera."""
        axis = straight_axis()
        box = road_section.section_window(axis, WIDE.carriageway_m, WIDE.shoulder_m, WIDE.berm_m, GRID)
        section = section_of(axis, flat, WIDE)
        self.assertEqual(section.window, box)
        whole = section_of(axis, flat, WIDE, window=(slice(0, GRID.nrows), slice(0, GRID.ncols)))
        self.assertEqual(section.cell_count, whole.cell_count)
        self.assertLess(section.cells.size, whole.cells.size)
        self.assertLessEqual(box[0].stop - box[0].start, 20)  # 12 m de ancho más la ampliación a las celdas
        self.assertGreaterEqual(box[1].stop - box[1].start, 200)

    def test_by_steps_it_is_the_same_section_and_it_cedes_the_thread(self) -> None:
        """RF-017-20, RNF-017-06: ``section_steps`` cede el hilo varias veces (por teselas) y da, en ``StopIteration.value``, la misma sección que
        ``section_cells``, bit a bit; cerrarlo a mitad no deja nada ni toca el terreno, el eje ni la rejilla."""
        axis = straight_axis()
        terrain = ground(tilted(20.0))
        before = digest(terrain)
        arguments = (axis, WIDE.carriageway_m, WIDE.shoulder_m, WIDE.berm_m, terrain, GRID, None)
        steps = road_section.section_steps(*arguments)
        yields, found = 0, None
        while True:
            try:
                next(steps)
                yields += 1
            except StopIteration as done:
                found = done.value
                break
        self.assertGreater(yields, 3)
        whole = road_section.section_cells(*arguments)
        for name in ("kind", "side", "sigma", "lateral", "cells"):
            self.assertEqual(digest(getattr(found, name)), digest(getattr(whole, name)), name)
        half = road_section.section_steps(*arguments)
        next(half)
        next(half)
        half.close()
        self.assertEqual(digest(terrain), before)

    def test_the_blocks_of_cells_do_not_change_the_result(self) -> None:
        """RF-017-20, RNF-017-06: el reparto de la huella en bloques de celdas (una unidad de trabajo cada uno) no cambia nada: con bloques de 100 celdas, en un
        eje curvo sobre un plano que cambia el lado del arcén, la misma sección que con los de siempre, bit a bit, y la longitud medida es la misma."""
        axis = road_axis.axis_of(rd.absolute(CurvedAxisTest.LEFT_TURN), 20.0, 12.0, 1.0)
        whole = section_of(axis, diagonal, WIDE)
        with mock.patch.object(road_section, "_BLOCK_CELLS", 100):
            blocks = section_of(axis, diagonal, WIDE)
        for name in ("cells", "kind", "side", "sigma", "lateral"):
            self.assertEqual(digest(getattr(blocks, name)), digest(getattr(whole, name)), name)
        self.assertEqual(blocks.length_m, whole.length_m)
        self.assertGreater(whole.cell_count, 100 * 8)

    def test_blocks_of_one_cell_give_the_same_section_on_a_short_axis(self) -> None:
        """RF-017-20: con bloques de una sola celda (el último también), una pista corta de 12 m da la misma sección que con los bloques de siempre."""
        axis = straight_axis((100.0, 200.0), (112.0, 200.0))  # de oeste a este: con el sur más alto el arcén va al sur y la última celda de la huella (la del sureste) es de la sección
        whole = section_of(axis, tilted(-25.0), WIDE)
        with mock.patch.object(road_section, "_BLOCK_CELLS", 1):
            cells = section_of(axis, tilted(-25.0), WIDE)
        for name in ("cells", "kind", "side", "sigma", "lateral"):
            self.assertEqual(digest(getattr(cells, name)), digest(getattr(whole, name)), name)
        self.assertEqual(cells.length_m, whole.length_m)
        self.assertEqual(whole.cell_count, 12 * 13)  # 12 columnas y las 13 filas de 10,5 + 1,5 + 1 m

    def test_the_section_is_read_only_and_does_not_modify_its_inputs(self) -> None:
        """RF-017-20: el terreno y el eje no cambian (principio 7) y las rejillas de la sección son de solo lectura (una vista que nadie debe modificar)."""
        axis = straight_axis()
        terrain = ground(tilted(20.0))
        before, points = digest(terrain), digest(axis.points)
        section = road_section.section_cells(axis, WIDE.carriageway_m, WIDE.shoulder_m, WIDE.berm_m, terrain, GRID, None)
        self.assertEqual(digest(terrain), before)
        self.assertEqual(digest(axis.points), points)
        for name in ("cells", "kind", "side", "sigma", "lateral"):
            self.assertFalse(getattr(section, name).flags.writeable, name)


class InputsTest(unittest.TestCase):
    def call(self, **changes: Any) -> Any:
        base: dict[str, Any] = {"axis": straight_axis(), "carriageway_m": 10.5, "shoulder_m": 0.0, "berm_m": 1.0, "terrain": ground(flat), "grid": GRID,
                                "window": None}
        base.update(changes)
        return road_section.section_cells(base["axis"], base["carriageway_m"], base["shoulder_m"], base["berm_m"], base["terrain"], base["grid"],
                                          base["window"])

    def test_a_carriageway_that_is_not_positive_or_a_negative_width_is_a_program_error(self) -> None:
        """RF-017-20: la calzada es un número real finito y positivo; el arcén y el caballón, finitos y no negativos (``ValueError`` o ``TypeError``: errores
        del programa, que la preparación de la pista rechazó antes con su perfil, su campo y su valor)."""
        for changes in ({"carriageway_m": 0.0}, {"carriageway_m": -1.0}, {"carriageway_m": math.nan}, {"shoulder_m": -0.1}, {"berm_m": -0.1},
                        {"berm_m": math.inf}):
            with self.subTest(**changes), self.assertRaises(ValueError):
                self.call(**changes)
        for changes in ({"carriageway_m": "10,5"}, {"shoulder_m": None}, {"berm_m": True}):
            with self.subTest(**changes), self.assertRaises(TypeError):
                self.call(**changes)

    def test_the_axis_the_grid_the_terrain_and_the_window_must_be_of_their_shape(self) -> None:
        """RF-017-20: un eje que no es de :mod:`design.road_axis`, una rejilla que no es la de ``gis``, un terreno que no es de la forma de la rejilla y una
        ventana fuera de ella son errores del programa."""
        with self.assertRaises(TypeError):
            self.call(axis=rd.absolute(((100.0, 200.0), (300.0, 200.0))))
        with self.assertRaises(TypeError):
            self.call(grid=(400, 400))
        with self.assertRaises(ValueError):
            self.call(terrain=np.zeros((10, 10)))
        for window in ((slice(-1, 10), slice(0, 10)), (slice(0, 401), slice(0, 10)), (slice(5, 2), slice(0, 10)), (slice(0, 10, 2), slice(0, 10))):
            with self.subTest(window=window), self.assertRaises(ValueError):
                self.call(window=window)
        with self.assertRaises(TypeError):
            self.call(window=(0, 10))

    def test_a_window_without_the_axis_gives_an_empty_section(self) -> None:
        """RF-017-20: una ventana que no toca la huella da una sección vacía (sin celdas, longitud 0), no un error: el rechazo, si lo hay, es de quien la
        pide con su pista y su capa."""
        section = self.call(window=(slice(0, 20), slice(0, 20)))
        self.assertEqual(section.cell_count, 0)
        self.assertEqual(section.length_m, 0.0)
        self.assertFalse(bool(section.cells.any()))


if __name__ == "__main__":
    unittest.main()
