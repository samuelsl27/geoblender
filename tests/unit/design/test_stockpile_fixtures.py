# SPDX-License-Identifier: GPL-3.0-or-later
"""La cantera de los acopios, el contrafuerte y los cuerpos apoyados (spec 016, T01; plan 016 §7.1 y §7.4;
RF-016-01, 02, 03, 06, 07, 08, 17, 20, 21; CE-016-01 a 07 y 10; E1 y E5).

Recorre ``tests.support.stockpile_data`` antes de que la usen las pruebas de la 016 (que aún no existen),
con cuentas a mano: los montones de forma conocida (tronco de pirámide, de enteros, y de cono, analítico)
con su volumen y su altura, sobre planos de 0°, 3° y 8° con celdas atípicas en la corona; el levantamiento
con 5 acopios marcados y 20 montículos sin marca (8 que pasan los filtros y 12 que no); los dos acopios que
se tocan; el acopio de 12 m junto a un relleno; las zonas de coronación junto a una zona de solo restauración,
al límite legal y a una plataforma; la ladera con espesores en tres secciones (puntos, líneas con su Z y con
su M, polígonos); los datos de escala que no pesan (la rejilla de 2,81 M celdas, solo bajo demanda); que el
proyecto se construye en ≤ 2 s de CPU y se lee de vuelta; y que los nombres de ``main`` en los que se apoya
el plan 016 (§5) siguen ahí.

Las cuentas del volumen de una pirámide son las de **anillos concéntricos de celdas** (en una pirámide de
semilado ``R`` y celdas de 1 m, el anillo ``r`` desde fuera tiene ``8·(R − r) − 4`` celdas a la altura
``mín(H, pendiente·(r + 0,5))``), hechas aquí con enteros y un solo bucle, no con el código que genera los
montones. Ningún dato de cliente: todo es sintético.
"""

from __future__ import annotations

import ast
import math
import time
import unittest

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import constraints_project as cp
from tests.support import design_fixtures as dfx
from tests.support import entity_fixtures as efx
from tests.support import quarry_fixtures as qfx
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.support.repo import EXTENSION_DIR

gis = import_geoblender("gis")
gis_store = import_geoblender("gis.store")

COPY_BUDGET_S = 1.0
"""Una copia del proyecto por clase, en menos de 1 s de CPU."""
THRESHOLD_M = 0.3
"""El umbral de huella de la 011 (``res.anthropic_presence_m``, D-17), con el que se cuenta a mano."""
TILT_MAX_DEG = 4.0
"""La inclinación máxima de la detección (HIPÓTESIS, plan §5.2.2): entre 3° y 8°."""
MIN_HEIGHT_M, MIN_AREA_M2 = 2.0, 150.0
"""La altura mínima y el área mínima de un candidato (D-3): con ellos se clasifican los montículos."""


def ring_volume(foot: int, top: int, height: float, *, above: float = 0.0) -> float:
    """El volumen (m³) sobre el plano de un tronco de pirámide de semilado ``foot`` en el pie y ``top`` en la
    cima, de altura ``height``, con celdas de 1 m y el centro en una esquina de celda, **por anillos**: el
    anillo ``r`` desde fuera tiene ``8·(foot − r) − 4`` celdas a ``mín(height, pendiente·(r + 0,5))``. Solo
    cuenta las celdas más altas que ``above``."""
    slope = height / (foot - top)
    return math.fsum((8 * (foot - ring) - 4) * min(height, slope * (ring + 0.5)) for ring in range(foot)
                     if min(height, slope * (ring + 0.5)) > above)


def ring_cells(foot: int, top: int, height: float, *, above: float = 0.0) -> int:
    """Las celdas de ese tronco de pirámide más altas que ``above``."""
    slope = height / (foot - top)
    return sum(8 * (foot - ring) - 4 for ring in range(foot)
               if min(height, slope * (ring + 0.5)) > above)


def scalar_cone_volume(foot: int, top: int, height: float, *, above: float = 0.0) -> float:
    """El volumen del tronco de cono por celdas de 1 m con el centro en una esquina, con dos bucles de
    Python y ``math.hypot`` (sin numpy)."""
    slope = height / (foot - top)
    found = []
    for i in range(-foot - 1, foot + 1):
        for j in range(-foot - 1, foot + 1):
            h = min(height, max(0.0, slope * (foot - math.hypot(i + 0.5, j + 0.5))))
            if h > above:
                found.append(h)
    return math.fsum(found)


def box_cells(box: tuple[float, float, float, float], grid: object = qfx.GRID) -> int:
    """Las celdas de ``grid`` con el centro dentro de la caja local."""
    return int(sdata.in_box(box, grid).sum())


def gap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """La separación entre dos cajas (m; negativa si se solapan, la mayor de las cuatro)."""
    return max(b[0] - a[2], a[0] - b[2], b[1] - a[3], a[1] - b[3])


class FrameTest(unittest.TestCase):
    """Las coordenadas locales y las rejillas de los casos."""

    def test_local_centers(self) -> None:
        """Con celdas de 1 m, el centro de la celda de la esquina noroeste es (0,5; 399,5) y con las de 2 m,
        (1; 399); la ventana de 120 m, 120 × 120 celdas con el norte en 119,5."""
        x, y = sdata.local_centers(qfx.GRID)
        self.assertEqual((float(x[0, 0]), float(y[0, 0]), float(x[-1, -1]), float(y[-1, -1])),
                         (0.5, 399.5, 399.5, 0.5))
        x2, y2 = sdata.local_centers(qfx.grid_of(2.0))
        self.assertEqual((x2.shape, float(x2[0, 0]), float(y2[0, 0])), ((200, 200), 1.0, 399.0))
        window = sdata.window_grid()
        xw, yw = sdata.local_centers(window)
        self.assertEqual((window.shape, float(xw[0, 0]), float(yw[0, 0])), ((120, 120), 0.5, 119.5))
        self.assertEqual((window.west, window.north - 120.0), (cfx.BASE[0], cfx.BASE[1]))

    def test_a_grid_outside_the_frame_is_an_error(self) -> None:
        """Una rejilla que no parte de la esquina de los casos no tiene coordenadas locales."""
        with self.assertRaises(ValueError):
            sdata.local_centers(gis.Grid(0.0, 100.0, 1.0, 1.0, 10, 10))

    def test_in_box_matches_the_quarry(self) -> None:
        """La caja local da las mismas celdas que la de la cantera de la 014 (misma convención)."""
        box = (100.0, 150.0, 140.0, 190.0)
        np.testing.assert_array_equal(sdata.in_box(box), qfx.in_box(box))
        self.assertEqual(box_cells(box), 1_600)
        self.assertEqual(box_cells(box, qfx.grid_of(2.0)), 400)


class PlaneTest(unittest.TestCase):
    """Los planos de 0°, 3° y 8° con el azimut de su máxima pendiente (desde el norte, en sentido horario)."""

    def test_tilt_and_azimuth(self) -> None:
        """La inclinación (``atan`` de la pendiente) y el azimut (``atan2(este, norte)``) son los pedidos, a
        ≤ 10⁻¹² °; el plano de 0° es llano y 3° < 4° < 8° (el límite de la detección de RF-016-07)."""
        self.assertEqual(sdata.TILTS_DEG, (0.0, 3.0, 8.0))
        flat = sdata.plane(0.0)
        self.assertEqual((flat.east_slope, flat.north_slope), (0.0, 0.0))
        for tilt in (3.0, 8.0):
            found = sdata.plane(tilt)
            self.assertAlmostEqual(math.degrees(math.atan(math.hypot(found.east_slope, found.north_slope))),
                                   tilt, delta=1e-12)
            self.assertAlmostEqual(math.degrees(math.atan2(found.east_slope, found.north_slope)), 30.0,
                                   delta=1e-12)
        self.assertLess(3.0, TILT_MAX_DEG)
        self.assertLess(TILT_MAX_DEG, 8.0)
        self.assertEqual(sdata.AZIMUTH_DEG, 30.0)

    def test_values_by_hand(self) -> None:
        """``z = z_pivote + b·(x − xp) + c·(y − yp)`` con ``b = tan·sin(az)`` y ``c = tan·cos(az)``, evaluado
        aquí celda a celda con ``math``; en el pivote es exacto."""
        found = sdata.plane(8.0, pivot=(60.0, 60.0), z_pivot=115.0)
        self.assertEqual(found.at(60.0, 60.0), 115.0)
        grid = sdata.window_grid()
        values = found.values(grid)
        tan, az = math.tan(math.radians(8.0)), math.radians(30.0)
        for row, col in ((0, 0), (119, 119), (30, 90), (60, 60)):
            x, y = col + 0.5, 119.5 - row
            by_hand = 115.0 + tan * math.sin(az) * (x - 60.0) + tan * math.cos(az) * (y - 60.0)
            self.assertAlmostEqual(float(values[row, col]), by_hand, delta=1e-12)
        self.assertEqual(values.shape, grid.shape)

    def test_a_tilt_out_of_range_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            sdata.plane(-1.0)
        with self.assertRaises(ValueError):
            sdata.plane(45.0)


class MoundShapeTest(unittest.TestCase):
    """Los dos troncos de referencia, con su volumen y su altura a mano (RF-016-02; CE-016-02)."""

    def setUp(self) -> None:
        self.grid = sdata.window_grid()
        self.x, self.y = sdata.local_centers(self.grid)

    def test_the_pyramid_by_hand(self) -> None:
        """Un tronco de pirámide de semilado 20 m en el pie y 12 m en la cima, de 4 m de altura (pendiente
        0,5, exacta en binario): anillos 0 a 7 a 0,25 + 0,5·r m con 156 − 8·r celdas
        (Σ (39 + 76·r − 4·r²) = 312 + 2.128 − 560 = **1.880 m³**) y una cima de 24 × 24 = 576 celdas a 4 m
        (**2.304 m³**): **4.184 m³** en 1.600 celdas (el analítico, 4/3·(1.600 + 576 + 960) = 4.181,33 m³);
        el anillo exterior, a 0,25 m, queda por debajo del umbral de 0,3 m: la huella es de 38 × 38 = 1.444
        celdas y **4.145 m³** (4.184 − 156·0,25)."""
        pyramid = sdata.PYRAMID
        self.assertEqual((pyramid.shape, pyramid.foot, pyramid.top, pyramid.height, pyramid.slope),
                         ("pyramid", 20.0, 12.0, 4.0, 0.5))
        h = pyramid.heights(self.x, self.y)
        self.assertEqual((h.shape, h.dtype), (self.grid.shape, np.float64))
        self.assertEqual(float(h.max()), 4.0)
        self.assertEqual(int((h == 4.0).sum()), 24 * 24)
        self.assertEqual(int((h > 0.0).sum()), 40 * 40)
        self.assertEqual(int((h > THRESHOLD_M).sum()), 38 * 38)
        self.assertEqual(float(h.sum()), 4_184.0)
        self.assertEqual(float(h[h > THRESHOLD_M].sum()), 4_145.0)
        self.assertEqual(ring_volume(20, 12, 4.0), 4_184.0)
        self.assertEqual(ring_volume(20, 12, 4.0, above=THRESHOLD_M), 4_145.0)
        self.assertEqual(ring_cells(20, 12, 4.0, above=THRESHOLD_M), 1_444)
        self.assertAlmostEqual(4_184.0 / (4.0 / 3.0 * (1_600.0 + 576.0 + 960.0)) - 1.0, 0.0, delta=1e-3)
        np.testing.assert_array_equal(h, h[::-1, ::-1])
        np.testing.assert_array_equal(h, h.T)
        self.assertEqual(float(h[0, 0]), 0.0)  # fuera de la huella

    def test_the_cone_by_hand(self) -> None:
        """Un tronco de cono de 20 m de radio en el pie y 10 m en la cima, de 5 m de altura (pendiente 0,5):
        el analítico es π·5/3·(400 + 200 + 100) = **3.665,19 m³**; las celdas de 1 m lo dan a menos del 1 %
        (D-11) y **igual a la cuenta con dos bucles de Python** a ≤ 10⁻¹²; por encima del umbral de 0,3 m
        se descuenta el anillo de 0,6 m del pie, 2·π·0,5·(20·0,6²/2 − 0,6³/3) = **11,08 m³**, y quedan
        3.654,11 m³."""
        cone = sdata.CONE
        self.assertEqual((cone.shape, cone.foot, cone.top, cone.height, cone.slope),
                         ("cone", 20.0, 10.0, 5.0, 0.5))
        h = cone.heights(self.x, self.y)
        self.assertEqual(float(h.max()), 5.0)
        analytic = math.pi * 5.0 / 3.0 * (400.0 + 200.0 + 100.0)
        self.assertAlmostEqual(analytic, 3_665.19, places=2)
        ring = 2.0 * math.pi * 0.5 * (20.0 * 0.6 ** 2 / 2.0 - 0.6 ** 3 / 3.0)
        self.assertAlmostEqual(ring, 11.08, places=2)
        self.assertLess(abs(float(h.sum()) / analytic - 1.0), 0.01)
        self.assertLess(abs(float(h[h > THRESHOLD_M].sum()) / (analytic - ring) - 1.0), 0.01)
        self.assertAlmostEqual(float(h.sum()) / scalar_cone_volume(20, 10, 5.0), 1.0, delta=1e-12)
        self.assertAlmostEqual(float(h[h > THRESHOLD_M].sum())
                               / scalar_cone_volume(20, 10, 5.0, above=THRESHOLD_M), 1.0, delta=1e-12)
        np.testing.assert_array_equal(h, h[::-1, ::-1])

    def test_a_pyramid_holds_more_than_a_cone(self) -> None:
        """El mismo pie y la misma cima dan más volumen en pirámide (el cuadrado contiene al círculo)."""
        pyramid = sdata.Mound("p", "pyramid", 60.0, 60.0, 20.0, 10.0, 5.0)
        cone = sdata.Mound("c", "cone", 60.0, 60.0, 20.0, 10.0, 5.0)
        self.assertGreater(float(pyramid.heights(self.x, self.y).sum()),
                           float(cone.heights(self.x, self.y).sum()))

    def test_bad_mounds_are_errors(self) -> None:
        for args in (("x", "dome", 0.0, 0.0, 5.0, 1.0, 1.0), ("x", "cone", 0.0, 0.0, 5.0, 5.0, 1.0),
                     ("x", "cone", 0.0, 0.0, 5.0, 1.0, 0.0), ("x", "cone", 0.0, 0.0, 5.0, -1.0, 1.0)):
            with self.assertRaises(ValueError):
                sdata.Mound(*args)

    def test_moved_keeps_the_shape(self) -> None:
        """``moved`` traslada el centro y deja la forma; la caja del pie va con él."""
        moved = sdata.PYRAMID.moved(10.0, -5.0)
        self.assertEqual((moved.cx, moved.cy, moved.foot_box),
                         (70.0, 55.0, (50.0, 35.0, 90.0, 75.0)))
        self.assertEqual((moved.foot, moved.top, moved.height), (20.0, 12.0, 4.0))


class MoundCaseTest(unittest.TestCase):
    """Los montones sobre los planos de 0°, 3° y 8°, con las celdas atípicas de la corona (CE-016-02;
    RF-016-02, 07)."""

    def test_every_shape_on_every_plane(self) -> None:
        """Con cono y pirámide y los tres planos: el terreno es el plano más el montón más las celdas
        atípicas, exactamente; el montón da el mismo volumen sobre el plano (a mano: 4.184 m³ y el analítico
        del cono) y la misma altura máxima, sea cual sea la inclinación; el plano es el pedido."""
        for shape, peak in (("pyramid", 4.0), ("cone", 5.0)):
            for tilt in sdata.TILTS_DEG:
                with self.subTest(shape=shape, tilt=tilt):
                    case = sdata.mound_case(shape, tilt)
                    self.assertEqual((case.grid, case.plane.tilt_deg), (sdata.window_grid(), tilt))
                    np.testing.assert_array_equal(case.terrain, case.base + case.height + case.offsets)
                    np.testing.assert_array_equal(case.base, case.plane.values(case.grid))
                    self.assertEqual(float(case.height.max()), peak)
                    if shape == "pyramid":
                        self.assertEqual(float(case.height.sum()), 4_184.0)
                    else:
                        analytic = math.pi * 5.0 / 3.0 * 700.0
                        self.assertLess(abs(float(case.height.sum()) / analytic - 1.0), 0.01)
                    self.assertEqual((case.mound.cx, case.mound.cy), (60.0, 60.0))

    def test_outliers_are_beyond_the_maximum_residual(self) -> None:
        """Ocho celdas atípicas (cuatro en la corona de la marca, a 25,5 m del centro por los ejes —25,505 m con
        el medio metro hasta el centro de celda—, y cuatro en la de la huella, a 21,5 m en un eje y 5,5 m en el
        otro: 22,19 m), fuera de la huella del montón (más de 20 m del centro, con la distancia euclídea y con la
        de Chebyshev), con desviaciones de entre 2 y 4 m (más que el residuo máximo de 1 m), tres negativas y
        cinco positivas (un ajuste simple no las compensa: suman +8 m); el resto del terreno es el plano más el
        montón."""
        for shape in ("cone", "pyramid"):
            case = sdata.mound_case(shape, 3.0)
            self.assertEqual(int(case.outliers.sum()), 8)
            offsets = case.offsets[case.outliers]
            self.assertTrue((np.abs(offsets) >= 2.0).all() and (np.abs(offsets) <= 4.0).all())
            self.assertEqual((int((offsets < 0).sum()), float(offsets.sum())), (3, 8.0))
            self.assertTrue((case.offsets[~case.outliers] == 0.0).all())
            self.assertTrue((case.height[case.outliers] == 0.0).all())
            x, y = sdata.local_centers(case.grid)
            dx, dy = x[case.outliers] - 60.0, y[case.outliers] - 60.0
            rho = np.hypot(dx, dy)
            np.testing.assert_allclose(
                np.sort(rho), np.sort([math.hypot(25.5, 0.5)] * 4 + [math.hypot(21.5, 5.5)] * 4),
                rtol=0.0, atol=1e-12)
            self.assertGreater(float(rho.min()), 20.0)  # el pie del cono
            self.assertGreater(float(np.maximum(np.abs(dx), np.abs(dy)).min()), 20.0)  # y el de la pirámide

    def test_without_outliers_the_terrain_is_the_plane_plus_the_mound(self) -> None:
        case = sdata.mound_case("cone", 8.0, outliers=False)
        self.assertEqual(int(case.outliers.sum()), 0)
        np.testing.assert_array_equal(case.terrain, case.base + case.height)

    def test_the_mark(self) -> None:
        """La marca es un cuadrado de 48 m de lado (el semilado del pie más 4 m) centrado en el montón: 2.304
        celdas con las de 1 m, 576 con las de 2 m; su anillo es absoluto, cerrado y antihorario."""
        case = sdata.mound_case("cone", 3.0)
        self.assertEqual(case.mark_box, (36.0, 36.0, 84.0, 84.0))
        self.assertEqual(box_cells(case.mark_box, case.grid), 48 * 48)
        np.testing.assert_array_equal(case.mark, cfx.rectangle(36.0, 36.0, 84.0, 84.0))
        self.assertEqual(case.mark.shape, (5, 2))
        coarse = sdata.mound_case("cone", 3.0, step_m=2.0)
        self.assertEqual((coarse.grid.shape, box_cells(coarse.mark_box, coarse.grid)), ((60, 60), 24 * 24))

    def test_coarse_grid(self) -> None:
        """Con celdas de 2 m, las ocho atípicas son ocho celdas distintas (la más próxima a cada punto) y el
        montón sigue siendo simétrico."""
        case = sdata.mound_case("pyramid", 3.0, step_m=2.0)
        self.assertEqual(int(case.outliers.sum()), 8)
        self.assertEqual(float(case.height.max()), 4.0)
        np.testing.assert_array_equal(case.height, case.height[::-1, ::-1])

    def test_a_new_array_every_time(self) -> None:
        case = sdata.mound_case("cone", 3.0)
        case.terrain[0, 0] = -1.0
        self.assertNotEqual(float(sdata.mound_case("cone", 3.0).terrain[0, 0]), -1.0)

    def test_bad_arguments_are_errors(self) -> None:
        with self.assertRaises(ValueError):
            sdata.mound_case("dome", 3.0)
        with self.assertRaises(ValueError):
            sdata.mound_case("cone", 3.0, step_m=3.0)


class SurveyTest(unittest.TestCase):
    """El levantamiento de CE-016-01: 5 acopios marcados y 20 montículos sin marca, sin Blender (RF-016-02,
    03, 08; E1)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.survey = sdata.survey()
        cls.previous = sdata.previous_survey()
        cls.heights = sdata.mound_heights(qfx.GRID.shape, qfx.STEP_M, sdata.SURVEY_MOUNDS)

    def mounds(self, group: str) -> tuple[sdata.Mound, ...]:
        return tuple(sdata.survey_mound(name) for name in sdata.SURVEY_GROUPS[group])

    def test_the_groups(self) -> None:
        """5 marcados y 20 sin marca: 8 que pasan los filtros, 4 pequeños, 4 bajos y 4 fuera del perímetro;
        los nombres no se repiten; las 5 marcas son las de los marcados."""
        groups = sdata.SURVEY_GROUPS
        self.assertEqual([len(groups[name]) for name in ("marked", "pass", "small", "low", "outside")],
                         [5, 8, 4, 4, 4])
        names = [name for group in groups.values() for name in group]
        self.assertEqual((len(names), len(set(names)), len(sdata.SURVEY_MOUNDS)), (25, 25, 25))
        self.assertEqual(sum(len(groups[name]) for name in ("pass", "small", "low", "outside")), 20)
        self.assertEqual(tuple(mark.mound for mark in sdata.MARKS), groups["marked"])
        self.assertEqual(tuple(mark.name for mark in sdata.MARKS),
                         ("Acopio 1", "Acopio 2", "Acopio 3", "Acopio 4", "Acopio 5"))

    def test_the_feet_are_inside_the_grid_and_apart(self) -> None:
        """Todos los pies caben en la rejilla de 400 m y, salvo los dos acopios que se tocan (Acopio 1 y 2,
        a 20 m con pies de 12 m: se solapan 4 m), están separados al menos 10 m: ni se tocan ni comparten
        corona (la corona llega a 3 m fuera de la huella)."""
        for mound in sdata.SURVEY_MOUNDS:
            left, bottom, right, top = mound.foot_box
            self.assertTrue(0.0 < left and 0.0 < bottom and right < 400.0 and top < 400.0, mound.name)
        for i, first in enumerate(sdata.SURVEY_MOUNDS):
            for second in sdata.SURVEY_MOUNDS[i + 1:]:
                found = gap(first.foot_box, second.foot_box)
                if {first.name, second.name} == {"Acopio 1", "Acopio 2"}:
                    self.assertEqual(found, -4.0)  # 12 + 12 − 20
                else:
                    self.assertGreaterEqual(found, 10.0, (first.name, second.name))

    def test_the_perimeter_splits_21_and_4(self) -> None:
        """Con el perímetro de actuación de la cantera (de (20, 60) a (360, 340)), los 21 de dentro tienen el
        pie entero dentro y los 4 de fuera no lo tocan."""
        left, bottom, right, top = qfx.PERIMETER_LOCAL
        for group in ("marked", "pass", "small", "low"):
            for mound in self.mounds(group):
                foot = mound.foot_box
                self.assertTrue(left <= foot[0] and bottom <= foot[1] and foot[2] <= right
                                and foot[3] <= top, mound.name)
        for mound in self.mounds("outside"):
            foot = mound.foot_box
            outside = foot[2] <= left or foot[0] >= right or foot[3] <= bottom or foot[1] >= top
            self.assertTrue(outside, mound.name)

    def test_the_filters_by_hand(self) -> None:
        """Los filtros de RF-016-08 con las cifras de D-3 (altura mínima 2 m, área de 150 a 20.000 m²): sobre
        el plano, un tronco de pendiente 0,5 supera los 2 m a más de 4 m del borde del pie, en un cuadrado de
        semilado ``R − 4`` y **(2·(R − 4))²** m² (324 m² con R = 13, 400 con 14 y 484 con 15; 100 m² con
        R = 9, 64 con 8 y 36 con 7); los bajos no pasan de 1,5 m. Los que pasan superan los 250 m² (casi el
        doble de los 150) con 5 m de altura o más y un pie de a lo sumo 15 m (el disco de la apertura, de
        31 m, no cabe dentro); los pequeños no llegan a 100 m²; los bajos miden menos de 2 m; los de fuera
        pasarían, pero están fuera del perímetro."""
        def above(mound: sdata.Mound) -> float:
            if mound.height <= MIN_HEIGHT_M:
                return 0.0
            return (2.0 * (mound.foot - MIN_HEIGHT_M / mound.slope)) ** 2

        for mound in (*self.mounds("pass"), *self.mounds("outside")):
            self.assertEqual(mound.shape, "pyramid", mound.name)
            self.assertEqual(mound.slope, 0.5, mound.name)
            self.assertGreaterEqual(above(mound), 250.0, mound.name)
            self.assertGreaterEqual(mound.height, 5.0, mound.name)
            self.assertLessEqual(mound.foot, 15.0, mound.name)
        for mound in self.mounds("small"):
            self.assertLessEqual(above(mound), 100.0, mound.name)
            self.assertLess(above(mound), MIN_AREA_M2)
        for mound in self.mounds("low"):
            self.assertLessEqual(mound.height, 1.5, mound.name)
            self.assertLess(mound.height, MIN_HEIGHT_M)
            self.assertEqual(above(mound), 0.0)
        self.assertEqual([above(sdata.survey_mound(name)) for name in ("P1", "P3", "P5")],
                         [324.0, 400.0, 484.0])
        self.assertEqual([above(sdata.survey_mound(name)) for name in ("S1", "S2", "S4")],
                         [100.0, 64.0, 36.0])

    def test_volumes_by_hand(self) -> None:
        """El volumen de cada montículo (su altura sumada en la caja de su pie) es el de la cuenta por
        anillos, con enteros; el del cono del Acopio 4, el de la cuenta con dos bucles; a ≤ 10⁻¹² relativo.
        Los dos que se tocan, aparte."""
        for mound in sdata.SURVEY_MOUNDS:
            if mound.name in ("Acopio 1", "Acopio 2"):
                continue
            found = float(self.heights[sdata.in_box(mound.foot_box)].sum())
            if mound.shape == "pyramid":
                by_hand = ring_volume(int(mound.foot), int(mound.top), mound.height)
            else:
                by_hand = scalar_cone_volume(int(mound.foot), int(mound.top), mound.height)
            self.assertAlmostEqual(found / by_hand, 1.0, delta=1e-12, msg=mound.name)

    def test_the_hand_volumes_of_a_few(self) -> None:
        """Tres a mano, por anillos. **P1** (pie 13, cima 3, 5 m; pendiente 0,5): anillos 0 a 9 a 0,25 + 0,5·r
        m con 100 − 8·r celdas (Σ (25 + 48·r − 4·r²) = 250 + 2.160 − 1.140 = 1.270 m³) y la cima de 6 × 6 = 36
        celdas a 5 m (180): **1.450 m³**. **S2** (pie 8, cima 1, 3,5 m): anillos 0 a 6 con 60 − 8·r celdas
        (Σ (15 + 28·r − 4·r²) = 105 + 588 − 364 = 329) y la cima de 2 × 2 a 3,5 m (14): **343 m³**. **Acopio
        3** (pie 14, cima 4, 5 m): anillos 0 a 9 con 108 − 8·r celdas (270 + 2.340 − 1.140 = 1.470) y la
        cima de 8 × 8 a 5 m (320): **1.790 m³**."""
        by_hand = {"P1": 1_450.0, "S2": 343.0, "Acopio 3": 1_790.0}
        for name, volume in by_hand.items():
            mound = sdata.survey_mound(name)
            self.assertEqual(ring_volume(int(mound.foot), int(mound.top), mound.height), volume, name)
            self.assertEqual(float(self.heights[sdata.in_box(mound.foot_box)].sum()), volume, name)

    def test_marks(self) -> None:
        """Las cinco marcas: cajas de 20 × 20 m sobre los marcados, los campos de la capa (margen solo en el
        Acopio 3, 6 m; material «mineral» o «estéril»; base solo en el Acopio 5), cada una contiene la cima
        de su montículo y, ampliada por su margen (6 m o los 10 m por defecto), su pie entero (RF-016-05)."""
        marks = {mark.name: mark for mark in sdata.MARKS}
        self.assertEqual({name: mark.margin_m for name, mark in marks.items()},
                         {"Acopio 1": None, "Acopio 2": None, "Acopio 3": 6.0, "Acopio 4": None,
                          "Acopio 5": None})
        self.assertEqual({name: mark.material for name, mark in marks.items()},
                         {"Acopio 1": "mineral", "Acopio 2": "mineral", "Acopio 3": "estéril",
                          "Acopio 4": "estéril", "Acopio 5": "mineral"})
        self.assertEqual({name: mark.base for name, mark in marks.items() if mark.base},
                         {"Acopio 5": sdata.PREVIOUS_LABEL})
        for mark in marks.values():
            left, bottom, right, top = mark.box
            self.assertEqual((right - left, top - bottom), (20.0, 20.0))
            mound = sdata.survey_mound(mark.mound)
            self.assertTrue(left <= mound.cx - mound.top and mound.cx + mound.top <= right, mark.name)
            self.assertTrue(bottom <= mound.cy - mound.top and mound.cy + mound.top <= top, mark.name)
            ext = mark.margin_m if mark.margin_m is not None else 10.0
            foot = mound.foot_box
            self.assertTrue(left - ext <= foot[0] and foot[2] <= right + ext, mark.name)
            self.assertTrue(bottom - ext <= foot[1] and foot[3] <= top + ext, mark.name)
        self.assertEqual(sorted(sdata.MATERIALS), ["estéril", "mineral"])

    def test_the_surface_is_the_plane_plus_the_terrace_plus_the_mounds(self) -> None:
        """El levantamiento anterior es el plano de 3° (con el pivote en el centro de la rejilla) más una
        terraza de 0,5 m (de (240, 200) a (270, 240): 30 × 40 = 1.200 celdas, de las que 15 × 30 = **450**
        están bajo el pie del Acopio 5); el levantamiento, ese más los montículos (donde se tocan, el mayor)."""
        plane = sdata.survey_plane()
        self.assertEqual((plane.tilt_deg, plane.pivot, plane.z_pivot), (3.0, (200.0, 200.0), 110.0))
        base = plane.values(qfx.GRID)
        terrace = sdata.in_box(sdata.TERRACE_BOX)
        np.testing.assert_array_equal(self.previous, base + np.where(terrace, 0.5, 0.0))
        self.assertEqual(int(terrace.sum()), 1_200)
        self.assertEqual(int((terrace & sdata.in_box(sdata.survey_mound("Acopio 5").foot_box)).sum()), 450)
        np.testing.assert_array_equal(self.survey, self.previous + self.heights)
        self.assertEqual(self.survey.shape, (400, 400))
        self.assertTrue((self.heights >= 0.0).all())
        self.assertEqual(float(self.heights.max()), 6.0)

    def test_the_rest_of_the_ground_is_the_plane(self) -> None:
        """Fuera de los pies de los montículos, el levantamiento es el anterior bit a bit."""
        covered = np.zeros(qfx.GRID.shape, dtype=bool)
        for mound in sdata.SURVEY_MOUNDS:
            covered |= sdata.in_box(mound.foot_box)
        self.assertTrue((self.heights[~covered] == 0.0).all())
        np.testing.assert_array_equal(self.survey[~covered], self.previous[~covered])

    def test_coarse_survey(self) -> None:
        """En la rejilla de 2 m el levantamiento sigue siendo el anterior más los montículos y nunca baja
        de él (el ráster del proyecto, T01)."""
        grid = qfx.grid_of(2.0)
        coarse = sdata.survey(grid)
        previous = sdata.previous_survey(grid)
        self.assertEqual(coarse.shape, (200, 200))
        self.assertTrue((coarse >= previous).all())
        self.assertGreater(float((coarse - previous).max()), 5.0)

    def test_a_new_array_every_time(self) -> None:
        found = sdata.survey()
        found[0, 0] = -1.0
        self.assertNotEqual(float(sdata.survey()[0, 0]), -1.0)


class TouchingPairTest(unittest.TestCase):
    """Dos acopios que se tocan (E1; RF-016-06): Acopio 1 y 2, troncos de pirámide de pie 12 m, cima 4 m y 4 m
    de altura, a 20 m uno de otro."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.case = sdata.touching_pair()

    def test_each_alone_by_hand(self) -> None:
        """Cada uno, solo: 8 anillos a 0,25 + 0,5·r m con 92 − 8·r celdas (Σ (23 + 44·r − 4·r²) = 184 +
        1.232 − 560 = 856) y la cima de 8 × 8 = 64 celdas a 4 m (256): **1.112 m³** (el analítico, 4/3·(576 +
        64 + 192) = 1.109,33)."""
        self.assertEqual(ring_volume(12, 4, 4.0), 1_112.0)
        x, y = sdata.local_centers(self.case.grid)
        for mound in self.case.mounds:
            self.assertEqual(float(mound.heights(x, y).sum()), 1_112.0)
        self.assertEqual(len(self.case.mounds), 2)
        self.assertEqual((self.case.mounds[1].cx - self.case.mounds[0].cx, self.case.mounds[0].cy),
                         (20.0, 60.0))

    def test_the_union_by_hand(self) -> None:
        """El montón de la unión es la altura mayor de los dos. Los pies se solapan 4 m en 4 × 24 = **96
        celdas**; en ellas, la menor de las dos alturas suma 46 (las columnas de los extremos a 0,25 m en 24
        filas, 12; las del centro a 0,75 m en 22 filas y 0,25 en dos, 2 × 17 = 34) y la unión da
        2 · 1.112 − 46 = **2.178 m³**. La silla entre los dos está a 1,25 m del plano: más que el umbral de
        0,3, así que es una sola zona conexa."""
        case = self.case
        x, y = sdata.local_centers(case.grid)
        first, second = (mound.heights(x, y) for mound in case.mounds)
        overlap = (first > 0.0) & (second > 0.0)
        self.assertEqual(int(overlap.sum()), 4 * 24)
        self.assertEqual(float(np.minimum(first, second)[overlap].sum()), 46.0)
        self.assertEqual(float(case.height.sum()), 2.0 * 1_112.0 - 46.0)
        self.assertEqual(float(case.height.sum()), 2_178.0)
        np.testing.assert_array_equal(case.height, np.maximum(first, second))
        row = int(np.argmin(np.abs(y[:, 0] - 60.5)))
        between = (x[0] > 52.0) & (x[0] < 68.0)
        self.assertEqual(float(case.height[row, between].min()), 1.25)
        self.assertGreater(1.25, THRESHOLD_M)

    def test_the_marks_touch_along_an_edge(self) -> None:
        """Las dos marcas (20 × 20 m, 400 celdas cada una) comparten el borde x = 60 y ninguna celda: las dos
        se tocan, no se solapan (no se rechazan, T11)."""
        case = self.case
        first, second = case.marks
        self.assertEqual((first.box, second.box), ((40.0, 50.0, 60.0, 70.0), (60.0, 50.0, 80.0, 70.0)))
        a, b = (sdata.in_box(mark.box, case.grid) for mark in case.marks)
        self.assertEqual((int(a.sum()), int(b.sum()), int((a & b).sum())), (400, 400, 0))
        self.assertIsNone(first.margin_m)
        self.assertEqual({first.material, second.material}, {"mineral"})
        self.assertEqual(case.mark_rings[0].shape, (5, 2))

    def test_the_terrain(self) -> None:
        """El terreno es el plano más la unión de los dos (sin celdas atípicas) y el plano es el de 3°."""
        case = self.case
        np.testing.assert_array_equal(case.terrain, case.base + case.height)
        self.assertEqual(case.plane.tilt_deg, 3.0)


class TallStockpileTest(unittest.TestCase):
    """El acopio de 12 m junto a un relleno (CE-016-03; error 47; RF-016-11, 13)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.case = sdata.tall_stockpile_with_fill()

    def test_the_stockpile_by_hand(self) -> None:
        """Un tronco de pirámide de pie 30 m, cima 6 m y **12 m** de altura (pendiente 0,5): 24 anillos a
        0,25 + 0,5·r con 236 − 8·r celdas (Σ (59 + 116·r − 4·r²) = 1.416 + 32.016 − 17.296 = 16.136 m³) y la
        cima de 12 × 12 a 12 m (1.728): **17.864 m³** (el analítico, 4·(3.600 + 144 + 720) = 17.856); la huella
        sobre el umbral de 0,3 m es de 58 × 58 = 3.364 celdas y 17.805 m³ (sin el anillo de 236 celdas a
        0,25 m, 59 m³)."""
        case = self.case
        h = case.stockpile_height
        self.assertEqual(float(h.max()), 12.0)
        self.assertEqual(int((h == 12.0).sum()), 12 * 12)
        self.assertEqual(float(h.sum()), 17_864.0)
        self.assertEqual(ring_volume(30, 6, 12.0), 17_864.0)
        self.assertEqual(int((h > THRESHOLD_M).sum()), 58 * 58)
        self.assertEqual(float(h[h > THRESHOLD_M].sum()), 17_805.0)
        self.assertEqual((case.stockpile.foot, case.stockpile.top, case.stockpile.height), (30.0, 6.0, 12.0))
        self.assertEqual(case.plane.tilt_deg, 0.0)

    def test_the_fill_by_hand(self) -> None:
        """El relleno es un bloque de 36 × 40 = 1.440 celdas (de x = 72 a 108 y de y = 40 a 80) a 3 m sobre el
        plano. Pisa 8 columnas del pie del acopio (de x = 72 a 80, 320 celdas) donde la altura del acopio es
        3,75, 3,25… 0,25 m: el relleno **apoyado** en el acopio (lo que supera su superficie) es
        40 · (0,25 + 0,75 + 1,25 + 1,75 + 2,25 + 2,75) = **360 m³**; fuera del pie, en 28 × 40 = 1.120
        celdas, 3.360 m³ sobre el plano. La superficie de partida pasa sobre el plano de 17.864 + 360 + 3.360
        = **21.584 m³**."""
        case = self.case
        self.assertEqual(int(case.fill.sum()), 36 * 40)
        h = case.stockpile_height
        strip = case.fill & (h > 0.0)
        self.assertEqual(int(strip.sum()), 8 * 40)
        self.assertEqual(float(np.maximum(case.fill_height - h, 0.0)[strip].sum()), 360.0)
        outside = case.fill & (h == 0.0)
        self.assertEqual((int(outside.sum()), float(case.fill_height[outside].sum())), (1_120, 3_360.0))
        start_height = case.start - case.base
        self.assertEqual(float(start_height.sum()), 21_584.0)
        self.assertEqual(float(start_height.max()), 12.0)
        self.assertEqual(case.fill_m, 3.0)

    def test_the_mark(self) -> None:
        """La marca es un cuadrado de 50 m de lado: con los 10 m de margen por defecto, su ampliación (70 m)
        cubre el pie de 60 m."""
        case = self.case
        self.assertEqual(case.mark_box, (25.0, 35.0, 75.0, 85.0))
        left, bottom, right, top = case.mark_box
        foot = case.stockpile.foot_box
        self.assertTrue(left - 10.0 <= foot[0] and foot[2] <= right + 10.0)
        self.assertTrue(bottom - 10.0 <= foot[1] and foot[3] <= top + 10.0)
        self.assertEqual(case.mark.shape, (5, 2))


class ButtressWindowTest(unittest.TestCase):
    """El llano de CE-016-10: un plano con la zona de coronación de 40 × 30 m (RF-016-17)."""

    def test_the_plane_and_the_zone(self) -> None:
        """Un plano a 115 m (0°) y una zona de 40 × 30 m = 1.200 celdas con la coronación a 125 m: el ancla de
        ``EXPL_10_60_6`` (125 m, bancos de 10 m), un banco por encima del plano."""
        case = sdata.flat_window()
        self.assertEqual((float(case.terrain.min()), float(case.terrain.max())), (115.0, 115.0))
        self.assertEqual(sdata.BUTTRESS_ZONE_LOCAL, (40.0, 45.0, 80.0, 75.0))
        self.assertEqual(box_cells(sdata.BUTTRESS_ZONE_LOCAL, case.grid), 1_200)
        self.assertEqual((dfx.EXPL_10_60_6.anchor_m, dfx.EXPL_10_60_6.height_m), (125.0, 10.0))
        self.assertEqual(sdata.BUTTRESS_CROWN_M, 125.0)
        self.assertEqual((sdata.BUTTRESS_CROWN_M - 115.0) / dfx.EXPL_10_60_6.height_m, 1.0)
        np.testing.assert_array_equal(case.zone_ring, cfx.rectangle(40.0, 45.0, 80.0, 75.0))

    def test_tilted_planes(self) -> None:
        """También sobre 3° y 8°: el plano pasa por 115 m en el centro de la zona."""
        for tilt in (3.0, 8.0):
            case = sdata.flat_window(tilt)
            self.assertEqual((case.plane.tilt_deg, case.plane.at(60.0, 60.0)), (tilt, 115.0))
            inside = sdata.in_box(sdata.BUTTRESS_ZONE_LOCAL, case.grid)
            self.assertEqual(int(inside.sum()), 1_200)
            self.assertAlmostEqual(float(case.terrain[inside].mean()), 115.0, delta=1e-9)


class CrownZonesTest(unittest.TestCase):
    """Las zonas de coronación (RF-016-17; CE-016-04, CE-016-06) y la zona de solo restauración."""

    def test_the_zones_by_hand(self) -> None:
        """Tres zonas: la del contrafuerte del Acopio 3 (22 × 22 = 484 celdas, 196 = 14 × 14 sobre el pie
        del acopio), la junto al límite legal (20 × 30 = 600) y la junto a la plataforma de carga
        (40 × 20 = 800). Cada coronación es del ancla de ``EXPL_10_60_6`` más un número entero de bancos
        (RF-016-18)."""
        zones = {zone.name: zone for zone in sdata.CROWN_ZONES}
        self.assertEqual(tuple(zones), ("Contrafuerte del acopio 3", "Coronación junto al límite",
                                        "Coronación junto a la plataforma"))
        self.assertEqual([box_cells(zone.box) for zone in zones.values()], [484, 600, 800])
        stockpile = sdata.survey_mound("Acopio 3")
        chain = zones["Contrafuerte del acopio 3"]
        self.assertEqual(int((sdata.in_box(chain.box) & sdata.in_box(stockpile.foot_box)).sum()), 14 * 14)
        for zone in zones.values():
            banks = (zone.level_m - dfx.EXPL_10_60_6.anchor_m) / dfx.EXPL_10_60_6.height_m
            self.assertEqual(banks, round(banks), zone.name)
        self.assertEqual([zone.level_m for zone in zones.values()], [115.0, 295.0, 285.0])
        self.assertEqual([zone.surface for zone in zones.values()], ["survey", "terrain", "terrain"])

    def test_the_levels_are_above_their_surface(self) -> None:
        """La coronación queda más de 1 m por encima de todas las celdas de su zona en la superficie que le
        toca (el levantamiento o el terreno de la cantera): hay algo que rellenar en todas."""
        survey, terrain = sdata.survey(), qfx.terrain()
        for zone in sdata.CROWN_ZONES:
            surface = survey if zone.surface == "survey" else terrain
            highest = float(surface[sdata.in_box(zone.box)].max())
            self.assertGreater(zone.level_m - highest, 1.0, zone.name)

    def test_the_neighbours(self) -> None:
        """La zona del límite toca por el oeste la de solo restauración (la caja de la restricción) y por el
        este la banda de 5 m hacia dentro del límite legal (que empieza en x = 355); la de la plataforma
        toca por el sur la huella de la plataforma de carga de la 015 (de y = 270 a 290) y no pisa la
        lámina de agua de la cantera."""
        zones = {zone.name: zone for zone in sdata.CROWN_ZONES}
        edge = zones["Coronación junto al límite"].box
        self.assertEqual(sdata.RESTORATION_LOCAL, (305.0, 296.0, 335.0, 334.0))
        self.assertEqual(edge[0], sdata.RESTORATION_LOCAL[2])
        self.assertEqual(edge[2], qfx.LEGAL_LOCAL[2] - qfx.LEGAL_INWARD_M)
        self.assertEqual(box_cells(sdata.RESTORATION_LOCAL), 30 * 38)
        carga = efx.AXES[0]
        self.assertEqual((carga.name, carga.width_m), ("Plataforma de carga", 20.0))
        platform = zones["Coronación junto a la plataforma"].box
        self.assertEqual(platform[1], carga.path[0][1] + carga.width_m / 2.0)
        self.assertGreater(gap(platform, qfx.WATER_LOCAL), 0.0)
        left, bottom, right, top = qfx.PERIMETER_LOCAL
        for zone in zones.values():
            self.assertTrue(left < zone.box[0] and zone.box[2] < right, zone.name)
            self.assertTrue(bottom < zone.box[1] and zone.box[3] < top, zone.name)

    def test_the_restoration_constraint(self) -> None:
        """Una restricción «solo restauración» con la caja (305, 296)–(335, 334), sin resguardo, lista para
        escribir (no está en el proyecto de la cantera: la añade quien la necesita, T26 y T31)."""
        item = sdata.restoration_constraint()
        self.assertEqual((item.code, item.ctype.value, item.kind.value),
                         (sdata.RESTORATION_CODE, "restoration_only", "polygon"))
        self.assertTrue(cp.same_parts(item.parts, ((cfx.rectangle(*sdata.RESTORATION_LOCAL),),)))
        self.assertNotIn(sdata.RESTORATION_CODE, qfx.CONSTRAINT_CODES)


class HillsideTest(unittest.TestCase):
    """La ladera con espesores en tres secciones (CE-016-05; B9; error 26; E5; RF-016-01, 20)."""

    def test_the_hillside_by_hand(self) -> None:
        """``150 + 0,25·y + 0,0625·x + (y − 200)²/256`` en los centros de celda, exacto en binario: una
        vaguada que baja hasta y = 168 (la derivada 0,25 + (y − 200)/128 se anula ahí)."""
        z = sdata.hillside()
        self.assertEqual((z.shape, z.dtype), ((400, 400), np.float64))
        for row, col in ((0, 0), (399, 399), (229, 200), (100, 300)):
            x, y = col + 0.5, 399.5 - row
            by_hand = 150.0 + 0.25 * y + 0.0625 * x + (y - 200.0) ** 2 / 256.0
            self.assertEqual(float(z[row, col]), by_hand)
        self.assertEqual(sdata.hillside_at(200.5, 170.5), 150.0 + 42.625 + 12.53125 + 870.25 / 256.0)
        np.testing.assert_array_equal(z, sdata.hillside(qfx.GRID))

    def test_the_data_by_hand(self) -> None:
        """Tres secciones (y = 140,5; 200,5; 260,5) de cinco estaciones (x = 100,5; 150,5; 200,5; 250,5;
        299,5) en centros de celda (sin ambigüedad con celdas de 1 y de 2 m): 15 datos de 1 a 3 m, nunca
        negativos, que suman 8,5 + 11,0 + 8,5 = **28,0** (medias de 1,7; 2,2 y 1,7 m)."""
        data = sdata.thickness_sections()
        self.assertEqual(data.points.shape, (15, 3))
        np.testing.assert_array_equal(data.points[:, 0] - cfx.BASE[0], np.tile(sdata.STATIONS_X, 3))
        np.testing.assert_array_equal(data.points[:, 1] - cfx.BASE[1], np.repeat(sdata.SECTIONS_Y, 5))
        self.assertEqual(sdata.SECTIONS_Y, (140.5, 200.5, 260.5))
        self.assertEqual(sdata.STATIONS_X, (100.5, 150.5, 200.5, 250.5, 299.5))
        thickness = data.points[:, 2]
        self.assertTrue((thickness >= 1.0).all() and (thickness <= 3.0).all())
        self.assertEqual(tuple(float(v) for v in thickness.reshape(3, 5).sum(axis=1)), (8.5, 11.0, 8.5))
        self.assertEqual(float(thickness.sum()), 28.0)
        self.assertEqual(tuple(round(float(v), 12) for v in thickness.reshape(3, 5).mean(axis=1)),
                         (1.7, 2.2, 1.7))

    def test_the_four_encodings_are_the_same_data(self) -> None:
        """Las líneas con el espesor en su Z (una por sección, cinco vértices) y con él en su M (con la Z del
        terreno en el vértice), y los polígonos (una banda de 200 × 20 m por sección con el espesor medio:
        4.000 m² cada una y 1,7·4.000 + 2,2·4.000 + 1,7·4.000 = **22.400 m³**) dicen lo mismo que los
        puntos."""
        data = sdata.thickness_sections()
        self.assertEqual((len(data.lines_z), len(data.lines_m), len(data.polygons)), (3, 3, 3))
        for index, (line_z, (line_m, m)) in enumerate(zip(data.lines_z, data.lines_m, strict=True)):
            section = data.points[index * 5:(index + 1) * 5]
            self.assertEqual((line_z.shape, line_m.shape), ((5, 3), (5, 3)))
            np.testing.assert_array_equal(line_z, section)
            np.testing.assert_array_equal(line_m[:, :2], section[:, :2])
            np.testing.assert_array_equal(m, section[:, 2])
            for vertex in line_m:
                self.assertEqual(float(vertex[2]),
                                 sdata.hillside_at(vertex[0] - cfx.BASE[0], vertex[1] - cfx.BASE[1]))
        volume = 0.0
        for index, (ring, thickness) in enumerate(data.polygons):
            local = ring - np.asarray(cfx.BASE)
            width = float(local[:, 0].max() - local[:, 0].min())
            depth = float(local[:, 1].max() - local[:, 1].min())
            self.assertEqual((float(local[:, 0].min()), float(local[:, 0].max()), width, depth),
                             (100.0, 300.0, 200.0, 20.0))
            self.assertEqual(round(thickness, 12), (1.7, 2.2, 1.7)[index])
            volume += thickness * width * depth
        self.assertAlmostEqual(volume, 22_400.0, delta=1e-9)

    def test_interpolating_the_base_gives_negative_thicknesses(self) -> None:
        """La demostración de CE-016-05 (no un criterio): sobre esta ladera, la cota de la base interpolada
        entre dos secciones (la cuerda de ``cota − espesor``) deja al terreno por debajo en la vaguada: en
        (200,5; 170,5), entre las secciones de 140,5 y 200,5, la cuerda de la parábola está
        (30·30)/256 = **3,515625 m** por encima del terreno y la del espesor (2,5 y 3,0 m) vale 2,75: el
        «espesor» sale **−0,765625 m**; el espesor interpolado, 2,75 m, no es negativo."""
        sag = (170.5 - 140.5) * (200.5 - 170.5) / 256.0
        self.assertEqual(sag, 3.515625)
        top = sdata.hillside_at
        self.assertEqual(0.5 * (top(200.5, 140.5) + top(200.5, 200.5)) - top(200.5, 170.5), sag)
        found = {(round(float(x) - cfx.BASE[0], 1), round(float(y) - cfx.BASE[1], 1)): float(t)
                 for x, y, t in sdata.thickness_sections().points}
        thickness_a, thickness_b = found[(200.5, 140.5)], found[(200.5, 200.5)]
        self.assertEqual((thickness_a, thickness_b), (2.5, 3.0))
        base_chord = 0.5 * ((top(200.5, 140.5) - thickness_a) + (top(200.5, 200.5) - thickness_b))
        self.assertEqual(top(200.5, 170.5) - base_chord, -0.765625)
        self.assertEqual(0.5 * (thickness_a + thickness_b), 2.75)

    def test_the_footprints(self) -> None:
        """Dos huellas de cuerpos: la de la ladera (de (90, 130) a (310, 270), 220 × 140 m) contiene los 15
        datos y la «sin datos» (de (20, 345) a (60, 380)) ninguno (RF-016-22)."""
        bodies = {body.name: body for body in sdata.BODIES}
        self.assertEqual(tuple(bodies), ("Cuerpo de la ladera", "Cuerpo sin datos"))
        data = sdata.thickness_sections().points - np.array([cfx.BASE[0], cfx.BASE[1], 0.0])

        def inside(box: tuple[float, float, float, float]) -> int:
            return int(((data[:, 0] > box[0]) & (data[:, 0] < box[2])
                        & (data[:, 1] > box[1]) & (data[:, 1] < box[3])).sum())

        self.assertEqual((bodies["Cuerpo de la ladera"].box, inside(bodies["Cuerpo de la ladera"].box)),
                         ((90.0, 130.0, 310.0, 270.0), 15))
        self.assertEqual((bodies["Cuerpo sin datos"].box, inside(bodies["Cuerpo sin datos"].box)),
                         ((20.0, 345.0, 60.0, 380.0), 0))


class LayersTest(unittest.TestCase):
    """Las capas del proyecto, antes de escribirlas (RF-016-02, 17, 20)."""

    def test_the_layers(self) -> None:
        """Cinco capas con los campos de la spec: marcas (``nombre``, ``margen``, ``material``, ``base``),
        coronaciones (``nombre``, ``cota``), huellas de cuerpos (``nombre``), espesores en puntos y en
        polígonos (``espesor``); sus nombres no chocan con los de la cantera ni los de la 015."""
        layers = {layer.name: layer for layer in sdata.layers()}
        self.assertEqual(tuple(layers), sdata.LAYERS)
        self.assertEqual(sdata.LAYERS, (sdata.MARKS_LAYER, sdata.CROWN_LAYER, sdata.BODIES_LAYER,
                                        sdata.THICKNESS_POINTS_LAYER, sdata.THICKNESS_POLYGONS_LAYER))
        self.assertEqual({name: (layer.kind, tuple(layer.fields)) for name, layer in layers.items()}, {
            sdata.MARKS_LAYER: ("polygon", ("margen", "material", "base")),
            sdata.CROWN_LAYER: ("polygon", ("cota",)),
            sdata.BODIES_LAYER: ("polygon", ()),
            sdata.THICKNESS_POINTS_LAYER: ("point", ("espesor",)),
            sdata.THICKNESS_POLYGONS_LAYER: ("polygon", ("espesor",))})
        self.assertFalse({*qfx.LAYERS, *efx.LAYERS} & set(layers))
        marks = layers[sdata.MARKS_LAYER]
        self.assertEqual(marks.names, tuple(mark.name for mark in sdata.MARKS))
        self.assertEqual(marks.fields["margen"], (None, None, 6.0, None, None))
        self.assertEqual(marks.fields["base"], (None, None, None, None, sdata.PREVIOUS_LABEL))
        self.assertEqual(layers[sdata.CROWN_LAYER].fields["cota"], (115.0, 295.0, 285.0))
        points = layers[sdata.THICKNESS_POINTS_LAYER]
        self.assertEqual((len(points.entities), points.entities[0][0][0].shape), (15, (1, 2)))
        self.assertEqual(sum(points.fields["espesor"]), 28.0)
        self.assertEqual(len(layers[sdata.THICKNESS_POLYGONS_LAYER].entities), 3)
        self.assertEqual(layers[sdata.BODIES_LAYER].names, ("Cuerpo de la ladera", "Cuerpo sin datos"))

    def test_a_new_array_every_time(self) -> None:
        sdata.layers()[0].entities[0][0][0][...] = 0.0
        self.assertNotEqual(float(sdata.layers()[0].entities[0][0][0][0, 0]), 0.0)


class ScaleDataTest(unittest.TestCase):
    """Los datos de escala de RNF-016-01 a 07 (plan §7.1): solo lo que no pesa; el levantamiento de 2,81 M
    celdas (``scale_survey``) es **bajo demanda** (lo usa T37) y no se construye en ``check.py``."""

    def test_the_sizes(self) -> None:
        """La rejilla de 1.654 × 1.699 celdas de 1 m (2,81 M), 100 marcas, 2.000 zonas candidatas antes de
        filtrar y 10.000 datos de espesor."""
        grid = sdata.scale_grid()
        self.assertEqual((grid.ncols, grid.nrows, grid.ncols * grid.nrows), (1654, 1699, 2_810_146))
        marks, bumps = sdata.scale_mounds()
        self.assertEqual((len(marks), len(bumps)), (100, 2_000))
        self.assertEqual((sdata.SCALE_MARKS, sdata.SCALE_BUMPS, sdata.SCALE_THICKNESS), (100, 2_000, 10_000))
        self.assertEqual(sdata.scale_thickness().shape, (10_000, 3))

    def test_the_mounds_are_apart_and_inside(self) -> None:
        """Ningún par de pies se toca (separados al menos 5 m) y todos caben en la rejilla; los de las marcas
        son troncos de pirámide de pie 13 m y 5 m de altura; los otros, de pie de 6 a 12 m y de 2,5 a 6 m."""
        marks, bumps = sdata.scale_mounds()
        every = (*marks, *bumps)
        centres = np.array([(m.cx, m.cy) for m in every])
        feet = np.array([m.foot for m in every])
        self.assertTrue((centres[:, 0] - feet > 0).all() and (centres[:, 0] + feet < 1654).all())
        self.assertTrue((centres[:, 1] - feet > 0).all() and (centres[:, 1] + feet < 1699).all())
        d = np.maximum(np.abs(centres[:, None, 0] - centres[None, :, 0]),
                       np.abs(centres[:, None, 1] - centres[None, :, 1]))
        np.fill_diagonal(d, 1e9)
        self.assertGreaterEqual(float((d - feet[:, None] - feet[None, :]).min()), 5.0)
        self.assertEqual({(m.shape, m.foot, m.height) for m in marks}, {("pyramid", 13.0, 5.0)})
        self.assertTrue(all(6.0 <= m.foot <= 12.0 and 2.5 <= m.height <= 6.0 for m in bumps))

    def test_the_thickness_data(self) -> None:
        """Diez mil datos sueltos en 100 ha (un cuadrado de 1.000 m), de 0,5 a 3 m, uno por celda de 1 m como
        mucho; los mismos cada vez (semilla fija)."""
        data = sdata.scale_thickness()
        self.assertTrue((data[:, 2] >= 0.5).all() and (data[:, 2] <= 3.0).all())
        local = data[:, :2] - np.array([sdata.SCALE_WEST, sdata.SCALE_SOUTH])
        self.assertTrue((local[:, 0] >= 300.0).all() and (local[:, 0] <= 1300.0).all())
        self.assertTrue((local[:, 1] >= 350.0).all() and (local[:, 1] <= 1350.0).all())
        self.assertEqual(len({(int(x), int(y)) for x, y in local}), 10_000)
        np.testing.assert_array_equal(data, sdata.scale_thickness())


class StockpileProjectTest(sdata.StockpileProjectCase):
    """El proyecto de la cantera de la 015 con la 016: el levantamiento, el de antes, la ladera y las cinco
    capas, en la rejilla gruesa de 2 m."""

    def test_built_once_within_budget(self) -> None:
        """La plantilla se crea una vez por proceso y paso en ≤ 2 s de CPU (lo que añade a la cantera de la
        015) y cada clase la copia en menos de 1 s."""
        template = sdata.project_template(qfx.COARSE_STEP_M)
        self.assertIs(template, sdata.project_template(qfx.COARSE_STEP_M))
        self.assertLessEqual(template["build_s"], sdata.BUILD_BUDGET_S)
        started = time.process_time()
        with sdata.open_stockpile_project(step_m=qfx.COARSE_STEP_M) as (_project, _clock):
            elapsed = time.process_time() - started
        self.assertLess(elapsed, COPY_BUDGET_S)

    def test_the_015_project_is_still_there(self) -> None:
        """Lo de la cantera y de la 015 sigue igual: V01 y V02, la rejilla gruesa, las cinco capas de la 014
        y las dos de plataformas, y el terreno de partida."""
        self.assertEqual((self.v1.code, self.v2.code), ("V01", "V02"))
        self.assertEqual(self.grid, qfx.grid_of(qfx.COARSE_STEP_M))
        for layer in (*qfx.layers(), *efx.platform_layers()):
            found = self.read_layer(layer.name)
            self.assertTrue(qfx.same_entities(found.parts, layer.entities), layer.name)
        raster = gis_store.load_raster(self.project, qfx.START_DATASET)
        np.testing.assert_array_equal(raster.values, qfx.terrain(self.grid))

    def test_layers_read_back(self) -> None:
        """Las cinco capas están en el proyecto como capas de entidades: su geometría bit a bit, sus ``fid``
        (1, 2…), sus nombres y sus campos (texto y números; el vacío, ``None``)."""
        for layer in sdata.layers():
            self.assertIsNotNone(self.record(layer.name), layer.name)
            found = self.read_layer(layer.name)
            self.assertEqual(found.kind, layer.kind, layer.name)
            self.assertEqual(found.fids, tuple(range(1, len(layer.entities) + 1)))
            self.assertTrue(qfx.same_entities(found.parts, layer.entities), layer.name)
            if layer.names:
                self.assertEqual(tuple(found.values["nombre"]), layer.names)
            for field, values in layer.fields.items():
                self.assertEqual(tuple(found.values[field]), values, (layer.name, field))

    def test_rasters_read_back(self) -> None:
        """El levantamiento, el de antes y la ladera, escritos como rejillas del proyecto, vuelven iguales bit
        a bit a lo que dan las funciones del módulo en la rejilla gruesa."""
        expected = {sdata.SURVEY_DATASET: sdata.survey(self.grid),
                    sdata.PREVIOUS_DATASET: sdata.previous_survey(self.grid),
                    sdata.HILLSIDE_DATASET: sdata.hillside(self.grid)}
        for name, values in expected.items():
            self.assertIsNotNone(self.record(name), name)
            raster = gis_store.load_raster(self.project, name)
            self.assertEqual(raster.grid, self.grid, name)
            self.assertEqual((raster.crs.epsg, raster.vertical.epsg), (25830, 5782))
            np.testing.assert_array_equal(raster.values, values, name)

    def test_the_marks_field_types(self) -> None:
        """``margen`` es numérico y ``material`` y ``base`` de texto en la tabla de las marcas."""
        found = self.read_layer(sdata.MARKS_LAYER)
        self.assertEqual({column.column: column.sql_type for column in found.columns},
                         {"nombre": "TEXT", "margen": "DOUBLE", "material": "TEXT", "base": "TEXT"})


class PlanNamesTest(unittest.TestCase):
    """Los nombres de ``main`` en los que se apoya el plan 016 (§5; T01) existen con la forma que dice, salvo
    lo que se anota: ``entity_surfaces`` está en ``design/entity_store.py``, no en ``entities``."""

    def test_domain_names(self) -> None:
        names = {
            "design.store": ("DesignWriter", "RECOMPUTED", "recompute_run", "masks_steps", "require_version"),
            "design.provenance": ("OPERATION_TYPES_BY_NAME", "CREATED_STEP_PARAMS", "DESIGN_SURFACE_ROLE",
                                  "ENTITY_VERSION_TYPES", "ENTITY_REPRODUCIBLE", "ENTITY_FIGURES",
                                  "DECLARE_CONSTRAINTS", "dataset_spec", "dataset_name", "dataset_locator"),
            "design.entities": ("chain_tails", "registry", "_deduce", "detect_supports", "strongest",
                                "retired_supports", "declared_zone_of_runs", "declared_zone", "Support",
                                "EntityKind"),
            "design.entity_store": ("read_geometry", "prepare_platform_units", "platform_compute_steps",
                                    "entity_surfaces", "declared_sources"),
            "design.params": ("PlatformParam", "entity_key"),
            "design.platform": ("work_window", "PlatformJob"),
            "design.edges": ("seed_envelope_steps", "created_steps"),
            "design.benching": ("bench_fill", "final_trim_steps"),
            "design.grids": ("label_components", "nearest_value_steps", "label_components_steps"),
            "design.steps": ("Calculation", "pace_progress"),
            "gis.tin": ("tin_to_raster",),
            "gis.cdt": ("PureTriangulator",),
            "reserves.compliance": ("Counts", "counts_of", "Checker", "ZoneTotals"),
            "reserves.compliance_store": ("verify_inputs", "verify_settings", "begin_verify", "check_sources",
                                          "freeze_findings"),
            "reserves.materials": ("Unit",),
            "gis.store": ("load_features", "read_features"),
            "gis.masks.access": ("load_masks", "ensure_masks_steps"),
        }
        for module, found in names.items():
            loaded = import_geoblender(module)
            for name in found:
                self.assertTrue(hasattr(loaded, name), f"{module}.{name}")
        import_geoblender("design.compose")

    def test_shapes_the_plan_relies_on(self) -> None:
        """Lo que el plan da por hecho de ``main``: ``Unit`` lleva ``base`` y ``thickness`` (RF-011-14), el
        dominio por defecto es de ``MaskSet``, ``Support`` lleva su ``code`` y la plataforma es un tipo de
        entidad."""
        materials = import_geoblender("reserves.materials")
        entities = import_geoblender("design.entities")
        access = import_geoblender("gis.masks.access")
        self.assertLessEqual({"base", "thickness"}, set(materials.Unit.__dataclass_fields__))
        self.assertTrue(hasattr(access.MaskSet, "default_domain"))
        self.assertIn("code", entities.Support.__dataclass_fields__)
        self.assertIn("platform", [kind.value for kind in entities.EntityKind])

    def test_blender_names(self) -> None:
        """``bl/scene/des_views.LOADERS``, ``bl/props/core.OBJECT_KINDS`` y ``bl/scene/views.BRANCHES`` (que
        ``bl`` no deja importar aquí) se declaran en el código."""
        for module, name in (("scene/des_views.py", "LOADERS"), ("props/core.py", "OBJECT_KINDS"),
                             ("scene/views.py", "BRANCHES")):
            source = (EXTENSION_DIR / "bl" / module).read_text(encoding="utf-8")
            found = False
            for node in ast.parse(source).body:
                target = node.targets[0] if isinstance(node, ast.Assign) else getattr(node, "target", None)
                found = found or (isinstance(target, ast.Name) and target.id == name)
            self.assertTrue(found, f"{module} no declara {name}")


if __name__ == "__main__":
    unittest.main()
