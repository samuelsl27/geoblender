# SPDX-License-Identifier: GPL-3.0-or-later
"""El borde de la plataforma (spec 015, T08; RF-015-22, RF-015-13, RF-015-08 para el alcance; plan 015
§5.4, A0 y A3; CE-015-07).

Las cuentas están hechas a mano y se comparan a ≤ 10⁻⁹ relativo (D-9):

- **Un plano inclinado** (``entity_fixtures.plane_terrain``: ``180 + 0,25·y + 0,0625·x``) con una
  plataforma que cruza la rejilla de norte a sur, de 20 m de ancho y plana a 180 m: todas sus celdas
  se cortan a la rasante y son semillas, así que la envolvente de una celda de fuera es **exactamente**
  ``rasante + tan(α) · k · paso`` con ``k`` las celdas hasta la huella (la semilla más próxima es la de
  su fila). El borde es entonces ``mín(z, rasante + tan α · k)`` columna a columna hasta el alcance, y
  el volumen, la pared y su lugar salen de esa fórmula celda a celda.
- **Una ladera más empinada que el ángulo de borde** (rejilla propia de 12 × 100 celdas, ``z = 300 +
  0,5·x``): la envolvente no encuentra el terreno, llega al alcance y la pared queda en su límite (con
  el aviso del salto creado); por el otro lado el corte acaba solo, sin pared.
- **El modo «en corte y relleno»**: el borde sube además por el lado en que el terreno queda por debajo
  de la envolvente descendente, y en «en corte» no.
- **Una fuerza bruta** (la envolvente ``mín_q [f_q + t · |p − q|]`` de todas las semillas, y su
  simétrica) sobre una huella con esquinas, máscaras al azar y un terreno inclinado en los dos ejes.
- **La métrica**: la euclídea exacta frente al *chamfer* 5×5 (su distancia es 0,98644 de la exacta a lo
  largo de un eje: la pared y el alcance cambian).
"""

from __future__ import annotations

import dataclasses
import math
import unittest
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import entity_fixtures as efx
from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender

platform = import_geoblender("design.platform")
model = import_geoblender("design.model")
params = import_geoblender("design.params")
messages = import_geoblender("design.messages")
envelopes = import_geoblender("design.envelopes")
design_report = import_geoblender("design.report")
preview = import_geoblender("design.preview")
gis = import_geoblender("gis")

DesignError = messages.DesignError
Metric = model.Metric
TOL = 1e-9
"""La tolerancia de las cuentas a mano (D-9)."""
PROJECT = {params.TOLERANCE_FACE: 1.0, params.VERIFY_MIN_THICKNESS: 0.05,
           params.EDGE_MAX_STEP: 1.0, params.EDGE_MIN_SHARE: 99.0}
"""Los parámetros del proyecto que lee el borde (valores de la prueba, no de un proyecto)."""
SCALE = envelopes.CHAMFER_SCALE


# --- Lo que construyen las pruebas -------------------------------------------------------------


def tilted_grid(nrows: int, ncols: int, step: float = 1.0) -> Any:
    """Una rejilla propia con su esquina suroeste en ``BASE`` (absoluta, float64)."""
    return gis.Grid(cfx.BASE[0], cfx.BASE[1] + nrows * step, step, step, ncols, nrows)


def tilt(grid: Any, z0: float, slope_x: float, slope_y: float = 0.0) -> np.ndarray:
    """El plano ``z0 + slope_x·x + slope_y·y`` en los centros de ``grid`` (locales desde la esquina
    suroeste; exacto en binario con pendientes de 0,5, 0,25 o 0,0625)."""
    columns = (np.arange(grid.ncols) + 0.5) * grid.dx
    rows = (grid.nrows - np.arange(grid.nrows) - 0.5) * grid.dy
    x, y = np.meshgrid(columns, rows)
    return z0 + slope_x * x + slope_y * y


def request(name: str = "P1") -> Any:
    return model.PlatformRequest(
        name=name, feature=name, start="Terreno",
        fields=model.PlatformFields(layer=efx.POLYGONS_LAYER, start_level_field="cota_inicial",
                                    gradient_field="pendiente"))


def box_polygon(left: float, bottom: float, right: float, top: float) -> Any:
    """Un polígono rectangular (local desde ``BASE``) sin eje enlazado."""
    return platform.PlatformGeometry("polygon", ((cfx.rectangle(left, bottom, right, top),),))


def make_job(grid: Any, start: np.ndarray, geometry: Any, *, level: float, angle: float = 30.0,
             reach: float | None = 30.5, mode: str | None = None, mesh: float | None = None,
             metric: str | None = None, cut_allowed: np.ndarray | None = None,
             fill_allowed: np.ndarray | None = None, gradient: float = 0.0,
             name: str = "P1") -> Any:
    """El trabajo de una plataforma plana (``gradient`` 0) con los valores dados (``None``: sin el
    valor, que lleva el de por defecto o falta)."""
    values: dict[str, object] = {"start_level_m": level, "gradient_pct": gradient}
    for key, value in (("reach_m", reach), ("edge_angle_deg", angle), ("mode", mode),
                       ("mesh_factor", mesh), ("metric", metric)):
        if value is not None:
            values[key] = value
    allowed = np.ones(grid.shape, dtype=bool)
    return platform.PlatformJob(
        request(name), "PLT-001", grid, start, geometry, values,
        allowed.copy() if cut_allowed is None else cut_allowed,
        allowed.copy() if fill_allowed is None else fill_allowed)


def run(job: Any, project: Any = None) -> tuple[Any, Any, Any]:
    """La huella, la plataforma aplicada y su borde."""
    footprint = platform.platform_footprint(job)
    applied = platform.apply_platform(job, footprint)
    edge = platform.platform_edge(job, footprint, applied, PROJECT if project is None else project)
    return footprint, applied, edge


def final_steps(steps: Any) -> Any:
    """El resultado del último paso de ``steps``."""
    last = None
    for last in steps:
        pass
    return last.result


def centre(grid: Any, row: int, col: int) -> tuple[float, float]:
    """El centro absoluto de la celda ``(row, col)`` de la rejilla entera."""
    return (grid.west + (col + 0.5) * grid.dx, grid.north - (row + 0.5) * grid.dy)


def tangent_deg(surface: np.ndarray, row: int, col: int, step: float) -> float:
    """La mayor inclinación (°) de la celda a sus 8 vecinas con dato, celda a celda y a mano."""
    best = 0.0
    for d_row in (-1, 0, 1):
        for d_col in (-1, 0, 1):
            other_row, other_col = row + d_row, col + d_col
            if (d_row, d_col) == (0, 0) or not (0 <= other_row < surface.shape[0]
                                                and 0 <= other_col < surface.shape[1]):
                continue
            there = surface[other_row, other_col]
            if math.isfinite(there):
                best = max(best, abs(surface[row, col] - there)
                           / (step * math.hypot(d_row, d_col)))
    return math.degrees(math.atan(best))


def strip_oracle(z: np.ndarray, columns: tuple[int, int], level: float, rise: float,
                 reach_cells: int) -> np.ndarray:
    """La superficie de una plataforma plana de ``columns`` (primera y siguiente a la última) que
    cruza la rejilla de norte a sur, a mano: la huella a ``mín(z, rasante)`` y, a ``k`` celdas de
    ella, ``mín(z, rasante + rise · k)`` hasta ``reach_cells``."""
    final = z.copy()
    first, last = columns
    final[:, first:last] = np.minimum(z[:, first:last], level)
    for k in range(1, reach_cells + 1):
        for col in (last - 1 + k, first - k):
            if 0 <= col < z.shape[1]:
                final[:, col] = np.minimum(z[:, col], level + rise * k)
    return final


def assert_close(test: unittest.TestCase, found: Any, wanted: Any, *, rtol: float = TOL) -> None:
    np.testing.assert_allclose(found, wanted, rtol=rtol, atol=0.0)
    test.assertEqual(np.shape(found), np.shape(wanted))


# --- Lo público --------------------------------------------------------------------------------


class PublicNamesTest(unittest.TestCase):
    """RF-015-22: lo que entrega esta tarea es público y está documentado."""

    def test_the_module_publishes_the_edge_and_its_data(self) -> None:
        """RF-015-22, RF-015-13: ``design.platform`` exporta el borde, sus pasos y sus datos, cada uno
        con su documentación."""
        names = ("Edge", "EdgeWall", "WallCause", "magnitude_notices", "platform_edge",
                 "platform_edge_steps")
        for name in names:
            with self.subTest(name=name):
                self.assertIn(name, platform.__all__)
                self.assertTrue(getattr(platform, name).__doc__.strip())

    def test_the_causes_of_a_wall_are_the_reach_the_masks_and_the_rest(self) -> None:
        """RF-015-22: una pared más empinada que el ángulo solo se admite en el límite del alcance y
        en el borde de lo que admiten las máscaras; lo demás (el terreno o la propia plataforma)
        se cuenta aparte."""
        self.assertEqual({cause.value for cause in platform.WallCause},
                         {"reach", "masks", "other"})

    def test_the_new_message_has_its_two_languages(self) -> None:
        """RF-015-13, principio 10: el aviso de la pared del borde está en español y en inglés."""
        message = messages.MESSAGES["des.platform_edge_steep"]
        self.assertEqual(message.severity, "warning")
        self.assertTrue(message.es.strip() and message.msgid.strip())


# --- Un plano inclinado, a mano ----------------------------------------------------------------


class PlaneByHandTest(unittest.TestCase):
    """RF-015-22, CE-015-07: una plataforma plana a 180 m que cruza de norte a sur el plano
    inclinado de la cantera (20 m de ancho, columnas 150 a 169): la envolvente de la celda ``k`` de
    fuera es ``180 + tan α · k`` y el borde, el corte a ella hasta el alcance."""

    LEVEL = 180.0
    ANGLE = 20.0
    REACH = 30.5  # 30 celdas
    K = 30
    COLUMNS = (150, 170)

    @classmethod
    def setUpClass(cls) -> None:
        cls.z = efx.plane_terrain(efx.GRID)
        cls.t = math.tan(math.radians(cls.ANGLE))
        cls.job = make_job(efx.GRID, cls.z, box_polygon(150.0, 0.0, 170.0, 400.0),
                           level=cls.LEVEL, angle=cls.ANGLE, reach=cls.REACH)
        cls.footprint, cls.applied, cls.edge = run(cls.job)
        cls.window = cls.footprint.window
        cls.wanted = strip_oracle(cls.z, cls.COLUMNS, cls.LEVEL, cls.t, cls.K)
        cls.inside = np.zeros(efx.GRID.shape, dtype=bool)
        cls.inside[:, cls.COLUMNS[0]:cls.COLUMNS[1]] = True

    def outside(self, array: np.ndarray) -> np.ndarray:
        """``array`` (de la rejilla) en la ventana, sin la huella."""
        return array[self.window]

    def test_the_surface_is_the_cut_to_the_envelope_cell_by_cell(self) -> None:
        """RF-015-22: ``z' = mín(z, 180 + tan α · k)`` en cada celda de fuera hasta 30 celdas, a ≤
        10⁻⁹ relativo; la huella queda como la dejó la aplicación (bit a bit)."""
        assert_close(self, self.edge.surface, self.wanted[self.window])
        footprint = self.footprint.cells
        np.testing.assert_array_equal(self.edge.surface[footprint], self.applied.surface[footprint])

    def test_the_first_cell_by_hand(self) -> None:
        """RF-015-22, CE-015-07: la celda de la fila 0 (y = 399,5 m) junto a la huella por el este
        (x = 170,5 m): el
        terreno es ``180 + 99,875 + 10,65625 = 290,53125``, la envolvente ``180 + tan α`` y el borde
        la deja en ella."""
        row, col = 0, 170
        self.assertEqual(self.z[row, col], 290.53125)
        found = self.edge.surface[row - self.window[0].start, col - self.window[1].start]
        self.assertAlmostEqual(found, 180.0 + self.t, delta=TOL * found)

    def test_the_edge_volume_is_the_sum_of_what_it_cuts(self) -> None:
        """RF-022 (D-7, D-17): el volumen del borde es la suma celda a celda de ``z − z'`` fuera de
        la huella (corte) y no sube nada (relleno 0 m³), a ≤ 10⁻⁹ relativo."""
        drop = (self.z - self.wanted)[~self.inside]
        self.assertAlmostEqual(self.edge.cut_m3 / float(drop.sum()), 1.0, delta=TOL)
        self.assertEqual(self.edge.fill_m3, 0.0)
        self.assertEqual(self.edge.cut_cells, int(np.count_nonzero(drop > 0.0)))
        self.assertEqual(self.edge.fill_cells, 0)
        self.assertGreater(self.edge.cut_cells, 0)

    def test_the_wall_height_is_the_largest_cut_by_hand(self) -> None:
        """RF-015-22 (interpretación del plan, [I]): la altura de la pared es ``máx(|z − z'|)`` en el
        borde. Aquí baja con ``k`` (la ladera, 0,0625, es más tendida que el ángulo): el máximo es la
        celda de la fila 0 junto a la huella por el este, ``110,53125 − tan α``, con su lugar
        absoluto."""
        wanted = 99.875 + 10.65625 - self.t
        self.assertAlmostEqual(self.edge.wall_max_m / wanted, 1.0, delta=TOL)
        x, y = centre(efx.GRID, 0, 170)
        self.assertEqual((self.edge.wall_x, self.edge.wall_y), (x, y))
        self.assertGreater(x, 699_000.0)
        self.assertGreater(y, 4_399_000.0)

    def test_nothing_changes_beyond_the_reach(self) -> None:
        """RF-015-22: ninguna celda más allá de 30,5 m de la huella cambia, ni un bit; la máscara del
        alcance son las columnas hasta 30 celdas de ella."""
        reach = np.zeros(efx.GRID.shape, dtype=bool)
        reach[:, self.COLUMNS[0] - self.K:self.COLUMNS[1] + self.K] = True
        np.testing.assert_array_equal(self.edge.in_reach, reach[self.window])
        far = ~self.edge.in_reach
        np.testing.assert_array_equal(self.edge.surface[far], self.z[self.window][far])
        self.assertFalse(self.edge.changed[far].any())

    def test_the_wall_at_the_reach_limit_is_flagged_and_the_slope_inside_is_not(self) -> None:
        """RF-015-22: a 20° (< 21°, el ángulo más la tolerancia de 1°) la ladera ya cortada no tiene
        pared; en el límite de las 30 celdas, donde la ladera sigue por encima de la envolvente,
        quedan las celdas con su pared, todas por el alcance."""
        flagged = np.argwhere(self.edge.steep)
        self.assertTrue(flagged.size)
        columns = {int(col) + self.window[1].start for _row, col in flagged}
        self.assertTrue(columns <= {self.COLUMNS[0] - self.K, self.COLUMNS[1] - 1 + self.K})
        self.assertEqual({wall.cause for wall in self.edge.walls}, {platform.WallCause.REACH})
        self.assertEqual(sum(wall.cells for wall in self.edge.walls), int(self.edge.steep.sum()))

    def test_the_cells_on_the_grid_border_are_reported_with_their_place(self) -> None:
        """RF-015-13: lo que llega a la primera y la última fila de la rejilla se avisa con su
        lugar (la ventana cruza la rejilla entera de norte a sur)."""
        rows = self.window[0]
        self.assertEqual((rows.start, rows.stop), (0, 400))
        found = np.argwhere(self.edge.outside)
        self.assertTrue(found.size)
        self.assertTrue(set(found[:, 0]) <= {0, 399})
        notice = next(item for item in self.edge.notices if item.code == "des.entity_edge_outside")
        self.assertEqual(notice.values["cells"], int(self.edge.outside.sum()))
        self.assertEqual(notice.values["area"], float(self.edge.outside.sum()))
        first_row, first_col = found[0]
        x, y = centre(efx.GRID, int(first_row), int(first_col) + self.window[1].start)
        self.assertEqual((notice.values["x"], notice.values["y"]), (x, y))


# --- Una ladera más empinada que el ángulo de borde --------------------------------------------


class SteepHillsideTest(unittest.TestCase):
    """RF-015-22, RF-015-13: ``z = 300 + 0,5·x`` (26,6°) con una plataforma plana a 310 m en las
    columnas 40 a 49 y un ángulo de borde de 20° (< 26,6°): por el este la envolvente no encuentra
    el terreno y llega al alcance (20 celdas), donde queda la pared; por el oeste el terreno baja y
    el corte acaba solo."""

    ROWS, COLS = 12, 100
    LEVEL = 310.0
    ANGLE = 20.0
    REACH = 20.5
    K = 20

    @classmethod
    def setUpClass(cls) -> None:
        cls.grid = tilted_grid(cls.ROWS, cls.COLS)
        cls.z = tilt(cls.grid, 300.0, 0.5)
        cls.t = math.tan(math.radians(cls.ANGLE))
        cls.job = make_job(cls.grid, cls.z, box_polygon(40.0, 0.0, 50.0, float(cls.ROWS)),
                           level=cls.LEVEL, angle=cls.ANGLE, reach=cls.REACH)
        cls.footprint, cls.applied, cls.edge = run(cls.job)
        cls.window = cls.footprint.window

    def east_depth(self, k: int) -> float:
        """El corte de la celda ``k`` por el este: terreno ``324,75 + 0,5 k`` menos ``310 + t k``."""
        return 14.75 + (0.5 - self.t) * k

    def west_depth(self, k: int) -> float:
        """El de la celda ``k`` por el oeste: ``320,25 − 0,5 k`` menos ``310 + t k``."""
        return 10.25 - (0.5 + self.t) * k

    def test_the_volume_and_the_wall_by_hand(self) -> None:
        """RF-015-22 (D-17): por el este se corta ``14,75 + (0,5 − t) k`` en las 20 celdas; por el
        oeste ``10,25 − (0,5 + t) k`` hasta la 11 (con la 12 el terreno ya queda por debajo): doce
        filas de cada una. La pared es el corte de la celda 20 por el este."""
        east = math.fsum(self.east_depth(k) for k in range(1, self.K + 1))
        west = math.fsum(self.west_depth(k) for k in range(1, 12))
        self.assertLess(self.west_depth(12), 0.0)
        self.assertAlmostEqual(self.edge.cut_m3 / (self.ROWS * (east + west)), 1.0, delta=TOL)
        self.assertEqual(self.edge.cut_cells, self.ROWS * (self.K + 11))
        self.assertEqual(self.edge.fill_m3, 0.0)
        self.assertAlmostEqual(self.edge.wall_max_m / self.east_depth(self.K), 1.0, delta=TOL)
        x, y = centre(self.grid, 0, 49 + self.K)
        self.assertEqual((self.edge.wall_x, self.edge.wall_y), (x, y))

    def test_the_envelope_reaches_the_reach_and_the_wall_stays_at_its_limit(self) -> None:
        """RF-015-22: las 12 celdas del límite del alcance (columna 69), con su pared de 17,5 m, son
        las únicas más empinadas que 20° + 1°, todas por el alcance; la peor, la de la fila 0,
        con su inclinación (la de la celda a su vecina de fuera: el corte más lo que sube el
        terreno)."""
        flagged = np.argwhere(self.edge.steep)
        self.assertEqual(len(flagged), self.ROWS)
        self.assertEqual({int(col) + self.window[1].start for _row, col in flagged},
                         {49 + self.K})
        wall = self.edge.walls[0]
        self.assertEqual(len(self.edge.walls), 1)
        self.assertEqual(wall.cause, platform.WallCause.REACH)
        self.assertEqual((wall.cells, wall.area_m2), (self.ROWS, float(self.ROWS)))
        wanted = math.degrees(math.atan(self.east_depth(self.K) + 0.5))
        self.assertAlmostEqual(wall.max_deg / wanted, 1.0, delta=TOL)
        self.assertEqual((wall.x, wall.y), centre(self.grid, 0, 49 + self.K))
        self.assertEqual(self.edge.limit_deg, 21.0)
        self.assertGreater(wanted, 80.0)
        self.assertAlmostEqual(tangent_deg(self.edge.surface, 0, 69 - self.window[1].start, 1.0)
                               / wall.max_deg, 1.0, delta=TOL)

    def test_the_created_step_is_the_wall_and_it_warns(self) -> None:
        """RF-015-13, RF-014-20, RF-014-21: el salto creado de las 12 parejas del límite (la celda
        movida y su vecina sin mover) es la pared (el corte de la celda 20); las 12 del oeste
        (el corte acaba solo) no pasan; con la mitad de las parejas dentro del salto admitido y el
        99 % pedido, avisa, con un tramo."""
        created = self.edge.created
        self.assertEqual((created.pairs, created.over), (24, 12))
        self.assertAlmostEqual(created.maximum_m / self.east_depth(self.K), 1.0, delta=TOL)
        self.assertTrue(created.warned)
        codes = [notice.code for notice in self.edge.notices]
        self.assertEqual(codes, ["des.platform_edge_steep", "des.entity_edge_outside",
                                 "des.edge_surface_step", "des.edge_stretch"])
        step = self.edge.notices[2]
        self.assertEqual(step.values["surface"], "P1")
        self.assertEqual(step.values["stretches"], 1)

    def test_what_reaches_the_grid_border_is_the_first_and_last_row(self) -> None:
        """RF-015-13: el corte llega a las filas 0 y 11 de la rejilla: en cada una, 20 celdas por el
        este y 11 por el oeste; la primera, la de más al oeste de la fila 0, con su lugar."""
        self.assertEqual(int(self.edge.outside.sum()), 2 * (self.K + 11))
        notice = next(item for item in self.edge.notices if item.code == "des.entity_edge_outside")
        self.assertEqual(notice.values["cells"], 62)
        self.assertEqual((notice.values["x"], notice.values["y"]), centre(self.grid, 0, 39 - 10))

    def test_without_a_reach_limit_the_cut_goes_on_to_the_grid_border(self) -> None:
        """RF-015-22, RF-015-13: con un alcance que pasa de la rejilla no queda pared en ningún
        límite (nada flagrante) y el corte llega a su borde este (columna 99), que se avisa."""
        job = make_job(self.grid, self.z, box_polygon(40.0, 0.0, 50.0, float(self.ROWS)),
                       level=self.LEVEL, angle=self.ANGLE, reach=500.5)
        _footprint, _applied, edge = run(job)
        self.assertEqual(edge.walls, ())
        self.assertFalse(edge.steep.any())
        self.assertTrue(edge.changed[:, 99 - edge.window[1].start].all())
        self.assertEqual(int(edge.outside.sum()), 2 * (50 + 11) + 10)
        self.assertEqual(edge.window, (slice(0, 12), slice(0, 100)))


# --- «En corte» y «en corte y relleno» ---------------------------------------------------------


class ModesTest(unittest.TestCase):
    """RF-015-22, RF-015-21: ``z = 300 + 0,5·x`` con una plataforma plana a 325 m en las columnas
    40 a 59 y 30°: por el este el terreno queda por encima de la envolvente ascendente (``325 +
    t k``) y se corta; por el oeste queda por debajo de la descendente (``325 − t k``) y solo en el
    modo «en corte y relleno» se sube."""

    ROWS, COLS = 10, 100
    LEVEL = 325.0
    ANGLE = 30.0
    REACH = 30.5
    K = 30

    @classmethod
    def setUpClass(cls) -> None:
        cls.grid = tilted_grid(cls.ROWS, cls.COLS)
        cls.z = tilt(cls.grid, 300.0, 0.5)
        cls.t = math.tan(math.radians(cls.ANGLE))
        geometry = box_polygon(40.0, 0.0, 60.0, float(cls.ROWS))
        cls.cut = run(make_job(cls.grid, cls.z, geometry, level=cls.LEVEL, angle=cls.ANGLE,
                               reach=cls.REACH, mode="cut"))
        cls.both = run(make_job(cls.grid, cls.z, geometry, level=cls.LEVEL, angle=cls.ANGLE,
                                reach=cls.REACH, mode="cut_fill"))

    def side_sum(self) -> float:
        """El corte por el este (y el relleno por el oeste, igual): ``4,75 − (t − 0,5) k``."""
        return math.fsum(4.75 - (self.t - 0.5) * k for k in range(1, self.K + 1))

    def test_in_cut_mode_the_edge_only_cuts(self) -> None:
        """RF-015-20, RF-015-22: en «en corte» la plataforma no rellena (las celdas de la huella por
        debajo de la rasante quedan como están, no son semillas) y el borde solo corta por el este:
        0 m³ de relleno y el oeste, sin cambiar un bit."""
        footprint, _applied, edge = self.cut
        self.assertAlmostEqual(edge.cut_m3 / (self.ROWS * self.side_sum()), 1.0, delta=TOL)
        self.assertEqual((edge.fill_m3, edge.fill_cells), (0.0, 0))
        west = slice(0, 40 - footprint.window[1].start)
        np.testing.assert_array_equal(edge.surface[:, west], self.z[footprint.window][:, west])

    def test_in_cut_fill_mode_it_also_fills_the_west(self) -> None:
        """RF-015-21, RF-015-22: en «en corte y relleno» la huella queda toda a 325 m y el borde
        corta por el este y rellena por el oeste lo mismo (la ladera es simétrica):
        ``Σ [4,75 − (t − 0,5) k] · filas`` en cada lado, con el corte y el relleno por separado."""
        _footprint, _applied, edge = self.both
        wanted = self.ROWS * self.side_sum()
        self.assertAlmostEqual(edge.cut_m3 / wanted, 1.0, delta=TOL)
        self.assertAlmostEqual(edge.fill_m3 / wanted, 1.0, delta=TOL)
        self.assertEqual((edge.cut_cells, edge.fill_cells), (self.ROWS * self.K,) * 2)
        self.assertAlmostEqual(edge.wall_max_m / (5.25 - self.t), 1.0, delta=TOL)

    def test_the_filled_side_is_the_descending_envelope(self) -> None:
        """RF-015-22: por el oeste ``z' = máx(z, 325 − t k)``, celda a celda; por el este, ``mín(z,
        325 + t k)``; la huella, a 325 m."""
        footprint, _applied, edge = self.both
        first = footprint.window[1].start
        for k in (1, 2, 17, 30):
            west = edge.surface[3, 39 - (k - 1) - first]
            east = edge.surface[3, 59 + k - first]
            self.assertAlmostEqual(west / (325.0 - self.t * k), 1.0, delta=TOL)
            self.assertAlmostEqual(east / (325.0 + self.t * k), 1.0, delta=TOL)
        self.assertTrue((edge.surface[:, 40 - first:60 - first] == 325.0).all())

    def test_the_fill_side_goes_to_the_reach_and_no_further(self) -> None:
        """RF-015-22: el relleno acaba a 30 celdas (la 31 queda como el terreno)."""
        footprint, _applied, edge = self.both
        first = footprint.window[1].start
        self.assertEqual(edge.surface[3, 39 - 30 - first], self.z[3, 39 - 30])
        self.assertNotEqual(edge.surface[3, 39 - 29 - first], self.z[3, 39 - 29])

    def test_more_seeds_never_cut_less(self) -> None:
        """RF-015-22: con las celdas por debajo de la rasante también como semillas
        («en corte y relleno»), la envolvente ascendente es ≤ y el borde corta ≥."""
        self.assertGreaterEqual(self.both[2].cut_m3, self.cut[2].cut_m3 * (1.0 - TOL))


# --- Una fuerza bruta con esquinas y máscaras --------------------------------------------------


def brute_envelope(seeds: np.ndarray, level: np.ndarray, grid: Any, rise: float, *,
                   up: bool) -> tuple[np.ndarray, np.ndarray]:
    """La envolvente ``mín_q [f_q + t·d]`` (``máx_q [f_q − t·d]`` si no ``up``) de las semillas de
    ``seeds`` con la distancia euclídea entre centros y la distancia a la semilla más próxima, a
    fuerza bruta."""
    rows, cols = np.nonzero(seeds)
    row_idx, col_idx = np.indices(seeds.shape)
    distance = np.hypot((row_idx[..., None] - rows) * grid.dy, (col_idx[..., None] - cols) * grid.dx)
    heights = level[rows, cols]
    if up:
        return np.min(heights + rise * distance, axis=-1), distance.min(axis=-1)
    return np.max(heights - rise * distance, axis=-1), distance.min(axis=-1)


class BruteForceTest(unittest.TestCase):
    """RF-015-22, RF-015-06: sobre un terreno inclinado en los dos ejes, una huella de 8 × 6
    celdas (con esquinas, donde la semilla más próxima es una esquina) y máscaras al azar, el borde
    es la envolvente a fuerza bruta de las semillas, recortada al alcance y a lo que las máscaras
    admiten."""

    N = 36
    ANGLE = 35.0
    REACH = 7.5

    @classmethod
    def setUpClass(cls) -> None:
        cls.grid = tilted_grid(cls.N, cls.N)
        cls.z = tilt(cls.grid, 100.0, 0.3, 0.2)
        cls.t = math.tan(math.radians(cls.ANGLE))
        generator = np.random.default_rng(15)
        cls.cut_ok = generator.random(cls.grid.shape) > 0.12
        cls.fill_ok = generator.random(cls.grid.shape) > 0.12
        cls.geometry = box_polygon(12.0, 12.0, 20.0, 18.0)

    def run_mode(self, mode: str) -> tuple[Any, Any, Any]:
        job = make_job(self.grid, self.z, self.geometry, level=107.8, angle=self.ANGLE,
                       reach=self.REACH, mode=mode, cut_allowed=self.cut_ok,
                       fill_allowed=self.fill_ok)
        return run(job)

    def expected(self, footprint: Any, applied: Any, mode: str) -> dict[str, np.ndarray]:
        window = footprint.window
        z = self.z[window]
        outside = ~footprint.cells
        seeds = applied.at_level
        up, near = brute_envelope(seeds, applied.surface, self.grid, self.t, up=True)
        reach = near <= self.REACH
        want_cut = outside & reach & (z > up)
        final = np.where(want_cut & self.cut_ok[window], up, z)
        held = want_cut & ~self.cut_ok[window]
        if mode == "cut_fill":
            down, _ = brute_envelope(seeds, applied.surface, self.grid, self.t, up=False)
            want_fill = outside & reach & (z < down)
            final = np.where(want_fill & self.fill_ok[window], down, final)
            held = held | (want_fill & ~self.fill_ok[window])
        return {"surface": np.where(outside, final, applied.surface), "held": held, "reach": reach,
                "z": z}

    def check(self, mode: str) -> None:
        footprint, applied, edge = self.run_mode(mode)
        wanted = self.expected(footprint, applied, mode)
        assert_close(self, edge.surface, wanted["surface"])
        np.testing.assert_array_equal(edge.held, wanted["held"])
        np.testing.assert_array_equal(edge.in_reach & ~footprint.cells,
                                      wanted["reach"] & ~footprint.cells)
        drop = (wanted["z"] - wanted["surface"])[~footprint.cells]
        self.assertAlmostEqual(edge.cut_m3 / float(np.maximum(drop, 0.0).sum()), 1.0, delta=TOL)
        if mode == "cut_fill":
            self.assertAlmostEqual(edge.fill_m3 / float(np.maximum(-drop, 0.0).sum()), 1.0,
                                   delta=TOL)
        else:
            self.assertEqual(edge.fill_m3, 0.0)
        self.assertTrue(edge.cut_m3 > 0.0)
        # Lo que las máscaras no dejan mover queda como estaba, ni un bit.
        np.testing.assert_array_equal(edge.surface[edge.held], wanted["z"][edge.held])
        self.assertTrue(edge.held.any())

    def test_cut_mode_against_the_brute_force_envelope(self) -> None:
        """RF-015-22, RF-015-06: ``z' = mín(z, ENV↑)`` donde el corte se admite y el alcance llega,
        con la envolvente de las semillas a fuerza bruta (esquinas incluidas) y las máscaras al
        azar; lo que no se puede cortar queda como estaba."""
        self.check("cut")

    def test_cut_fill_mode_against_the_brute_force_envelopes(self) -> None:
        """RF-015-21, RF-015-22: ``z' = mín(z, ENV↑)`` y ``z' = máx(z, ENV↓)`` donde se admiten,
        con las dos envolventes a fuerza bruta."""
        self.check("cut_fill")

    def test_a_steep_ramp_crosses_the_envelopes_and_the_descending_one_wins(self) -> None:
        """RF-015-21, RF-015-22: con una rasante más empinada que el ángulo de borde (80 % frente a
        35°) las semillas no cumplen la pendiente entre sí, ``ENV↓`` pasa por encima de ``ENV↑`` en
        algunas celdas y ``z' = mín(z, ENV↑)`` y ``z' = máx(z, ENV↓)`` se contradicen: gana la
        descendente (es la última que se aplica), celda a celda con la fuerza bruta."""
        job = make_job(self.grid, self.z, self.geometry, level=104.0, angle=self.ANGLE,
                       reach=self.REACH, mode="cut_fill", cut_allowed=self.cut_ok,
                       fill_allowed=self.fill_ok, gradient=80.0)
        footprint, applied, edge = run(job)
        window = footprint.window
        z = self.z[window]
        up, near = brute_envelope(applied.at_level, applied.surface, self.grid, self.t, up=True)
        down, _ = brute_envelope(applied.at_level, applied.surface, self.grid, self.t, up=False)
        outside = ~footprint.cells & (near <= self.REACH)
        crossing = outside & (z > up) & (z < down)
        self.assertTrue((crossing & self.cut_ok[window] & self.fill_ok[window]).any())
        final = np.where(outside & (z > up) & self.cut_ok[window], up, z)
        final = np.where(outside & (z < down) & self.fill_ok[window], down, final)
        assert_close(self, edge.surface, np.where(footprint.cells, applied.surface, final))
        moved = (z - edge.surface)[~footprint.cells]
        self.assertAlmostEqual(edge.cut_m3 / float(np.maximum(moved, 0.0).sum()), 1.0, delta=TOL)
        self.assertAlmostEqual(edge.fill_m3 / float(np.maximum(-moved, 0.0).sum()), 1.0, delta=TOL)

    def test_the_held_area_is_what_the_masks_do_not_let_move(self) -> None:
        """RF-015-13: el área del borde que no se mueve por las máscaras son las celdas que la
        envolvente movería y no se admiten, con su número y su superficie."""
        _footprint, _applied, edge = self.run_mode("cut")
        self.assertEqual(edge.held_cells, int(edge.held.sum()))
        self.assertEqual(edge.held_area_m2, edge.held_cells * self.grid.cell_area)
        self.assertFalse((edge.changed & edge.held).any())


# --- Las máscaras en el borde ------------------------------------------------------------------


class MasksAtTheEdgeTest(unittest.TestCase):
    """RF-015-22, RF-015-13: ``z = 300 + 0,5·x``, plataforma plana a 305 m en las columnas 20 a 29,
    20°, alcance de 20,5 m; fuera de la huella no se corta un trozo de 3 × 4 celdas y dentro, uno de
    2 × 2: la pared contra ellos se admite («borde de lo que admiten las máscaras») y la del
    alcance, también."""

    ROWS, COLS = 12, 80

    @classmethod
    def setUpClass(cls) -> None:
        cls.grid = tilted_grid(cls.ROWS, cls.COLS)
        cls.z = tilt(cls.grid, 300.0, 0.5)
        cut_ok = np.ones(cls.grid.shape, dtype=bool)
        cut_ok[3:6, 33:37] = False  # fuera de la huella (12 celdas)
        cut_ok[5:7, 28:30] = False  # dentro de la huella (4 celdas)
        cls.cut_ok = cut_ok
        cls.job = make_job(cls.grid, cls.z, box_polygon(20.0, 0.0, 30.0, float(cls.ROWS)),
                           level=305.0, angle=20.0, reach=20.5, cut_allowed=cut_ok)
        cls.footprint, cls.applied, cls.edge = run(cls.job)
        cls.window = cls.footprint.window

    def test_what_the_masks_do_not_allow_stays_as_it_was(self) -> None:
        """RF-015-06, RF-015-13: las 12 celdas de fuera que la envolvente cortaría y la máscara no
        admite quedan como en el terreno, son ``held``, y ninguna cambia."""
        offset = self.window[1].start
        patch = np.zeros(self.edge.held.shape, dtype=bool)
        patch[3:6, 33 - offset:37 - offset] = True
        np.testing.assert_array_equal(self.edge.held, patch)
        self.assertEqual((self.edge.held_cells, self.edge.held_area_m2), (12, 12.0))
        np.testing.assert_array_equal(self.edge.surface[patch], self.z[self.window][patch])
        self.assertFalse(self.edge.changed[patch].any())

    def test_the_steep_cells_are_exactly_those_steeper_than_the_angle_and_the_terrain(self) -> None:
        """RF-015-22: las celdas que el borde mueve y quedan con una inclinación a alguna vecina por
        encima de 20° + 1° **y** de la que el terreno ya tenía en ellas (lo que el terreno ya tenía
        no cuenta), calculada a mano celda a celda, son las marcadas (ni una más)."""
        surface, terrain = self.edge.surface, self.z[self.window]
        wanted = np.zeros(surface.shape, dtype=bool)
        for row, col in np.argwhere(self.edge.changed):
            here = tangent_deg(surface, row, col, 1.0)
            wanted[row, col] = here > 21.0 and here > tangent_deg(terrain, row, col, 1.0)
        np.testing.assert_array_equal(self.edge.steep, wanted)

    def test_the_terrains_own_steepness_does_not_count(self) -> None:
        """RF-015-22, error 48: donde el corte acaba solo (columna 14, por el oeste) la celda queda
        a 23,5° de su vecina sin cortar, más que 21°, pero el terreno ya tiene 26,6° (0,5 m por
        metro): no es una pared que deje el borde y no se marca."""
        offset = self.window[1].start
        col = 14 - offset
        here = tangent_deg(self.edge.surface, 5, col, 1.0)
        self.assertGreater(here, 21.0)
        self.assertLess(here, tangent_deg(self.z[self.window], 5, col, 1.0))
        self.assertTrue(self.edge.changed[5, col])
        self.assertFalse(self.edge.steep[:, col].any())

    def test_each_steep_cell_has_its_cause(self) -> None:
        """RF-015-22, RF-015-13: 12 celdas en el límite del alcance (la columna 49, a 20 celdas de la
        huella) y 22 junto a lo que las máscaras no dejan mover (18 alrededor del trozo de fuera, 4
        de la columna 30 junto al de dentro); ninguna sin causa (el terreno o la plataforma)."""
        by_cause = {wall.cause: wall for wall in self.edge.walls}
        self.assertEqual(set(by_cause), {platform.WallCause.REACH, platform.WallCause.MASKS})
        self.assertEqual(by_cause[platform.WallCause.REACH].cells, 12)
        self.assertEqual(by_cause[platform.WallCause.MASKS].cells, 22)
        self.assertEqual(by_cause[platform.WallCause.MASKS].area_m2, 22.0)
        offset = self.window[1].start
        in_limit = [int(row) for row, col in np.argwhere(self.edge.steep)
                    if int(col) + offset == 49]
        self.assertEqual(sorted(in_limit), list(range(self.ROWS)))

    def test_the_worst_wall_of_each_cause_is_by_hand(self) -> None:
        """RF-015-22: la inclinación y el lugar de la peor celda de cada causa son los de la celda
        con más inclinación de las marcadas con ella, la primera de norte a sur y de oeste a este."""
        offset = self.window[1].start
        for wall in self.edge.walls:
            with self.subTest(cause=wall.cause):
                best = (-1.0, None)
                for row, col in np.argwhere(self.edge.steep):
                    here = tangent_deg(self.edge.surface, row, col, 1.0)
                    near_reach = (int(col) + offset) == 49
                    if (wall.cause is platform.WallCause.REACH) == near_reach and here > best[0]:
                        best = (here, (int(row), int(col) + offset))
                self.assertAlmostEqual(wall.max_deg / best[0], 1.0, delta=TOL)
                self.assertEqual((wall.x, wall.y), centre(self.grid, *best[1]))

    def test_the_footprint_cells_the_mask_holds_stay_as_they_were(self) -> None:
        """RF-015-06: las 4 celdas de la huella que no se cortan quedan como el terreno (de T07) y el
        borde no las toca."""
        offset = self.window[1].start
        patch = np.zeros(self.edge.surface.shape, dtype=bool)
        patch[5:7, 28 - offset:30 - offset] = True
        np.testing.assert_array_equal(self.edge.surface[patch], self.z[self.window][patch])
        self.assertEqual(self.applied.blocked_cells, 4)


class StripWithAnUntouchableTest(unittest.TestCase):
    """RF-015-22, RF-015-13, CE-015-02: la franja de la cantera (40 m de ancho, 6 m por encima de su
    rasante) con y sin el intocable que la cruza y sobresale 10 m por cada lado."""

    ANGLE = 40.0

    @classmethod
    def setUpClass(cls) -> None:
        cls.t = math.tan(math.radians(cls.ANGLE))
        cls.plain = cls.make(efx.strip_case())
        cls.held = cls.make(efx.strip_case(untouchable=True))

    @classmethod
    def make(cls, case: Any) -> tuple[Any, Any, Any, Any]:
        request_ = model.PlatformRequest(
            name="Franja", feature="Franja", start="Terreno",
            fields=model.PlatformFields(layer=efx.AXES_LAYER, start_level_field="cota_inicial",
                                        gradient_field="pendiente", width_field="ancho"))
        job = platform.PlatformJob(
            request_, "PLT-001", case.grid, case.terrain, platform.PlatformGeometry("line", ((case.axis,),)),
            {"width_m": case.width_m, "start_level_m": case.grade_start_m,
             "gradient_pct": case.slope_pct, "reach_m": 12.5, "edge_angle_deg": cls.ANGLE},
            case.cut_allowed, case.fill_allowed)
        return (case, *run(job))

    def test_the_cut_on_the_flat_side_is_the_envelope_by_hand(self) -> None:
        """RF-015-22: al norte de la franja, sobre la parte que no es el tramo bajo, el terreno queda
        6 m por encima de la rasante y la envolvente de la celda ``k`` es ``rasante + tan α · k`` (la
        semilla más próxima es la de su columna): el borde baja ``6 − t k`` hasta ``k = 7``, y la
        celda 8 ya no se corta."""
        case, footprint, _applied, edge = self.plain
        first = footprint.window
        column = 135  # x = 135,5 m: sobre la huella pero fuera del tramo bajo
        top_row = 400 - 220  # la fila de y = 219,5 m es la última de la huella
        grade = 230.0 + (135.5 - 100.0) * 0.01
        for k in range(1, 8):
            found = edge.surface[top_row - k - first[0].start, column - first[1].start]
            self.assertAlmostEqual(found / (grade + self.t * k), 1.0, delta=TOL)
        eighth = edge.surface[top_row - 8 - first[0].start, column - first[1].start]
        self.assertEqual(eighth, case.terrain[top_row - 8, column])

    def test_the_wall_height_is_the_first_step_at_the_uphill_end(self) -> None:
        """RF-015-22: la pared más alta es la de la primera celda de fuera por el extremo este, donde
        el terreno (que sigue subiendo el 1 % de la rasante) queda 6,01 m por encima de la semilla
        de su fila: ``6,01 − tan α``; sin relleno."""
        _case, _footprint, _applied, edge = self.plain
        self.assertAlmostEqual(edge.wall_max_m / (6.01 - self.t), 1.0, delta=1e-9)
        self.assertEqual(edge.fill_m3, 0.0)

    def test_the_untouchable_holds_part_of_the_edge_and_cuts_less(self) -> None:
        """RF-015-13: el intocable que sobresale 10 m por cada lado impide cortar celdas del borde
        (``held``), que quedan como el terreno; el borde corta menos que sin él y avisa de la pared
        contra el intocable."""
        case, footprint, _applied, edge = self.held
        window = footprint.window
        self.assertGreater(edge.held_cells, 0)
        self.assertFalse((edge.held & case.cut_allowed[window]).any())
        self.assertFalse((edge.changed & ~case.cut_allowed[window]).any())
        np.testing.assert_array_equal(edge.surface[edge.held], case.terrain[window][edge.held])
        self.assertLess(edge.cut_m3, self.plain[3].cut_m3)
        causes = {wall.cause for wall in edge.walls}
        self.assertIn(platform.WallCause.MASKS, causes)
        self.assertTrue(any(item.code == "des.platform_edge_steep" for item in edge.notices))


# --- Las celdas sin dato -----------------------------------------------------------------------


class NoDataTest(unittest.TestCase):
    """RF-015-13: lo que llega a celdas sin dato fuera de la huella se avisa con su lugar, y esas
    celdas siguen sin dato."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.grid = tilted_grid(12, 60)
        cls.z = tilt(cls.grid, 300.0, 0.5)
        cls.z[4:8, 36:39] = np.nan
        cls.job = make_job(cls.grid, cls.z, box_polygon(20.0, 0.0, 30.0, 12.0), level=305.0,
                           angle=20.0, reach=15.5)
        cls.footprint, cls.applied, cls.edge = run(cls.job)
        cls.window = cls.footprint.window

    def test_the_cells_without_data_stay_without_data(self) -> None:
        """RF-015-22: las 12 celdas sin dato siguen siendo NaN en la superficie; las demás de la
        ventana tienen dato."""
        patch = np.zeros(self.edge.surface.shape, dtype=bool)
        offset = self.window[1].start
        patch[4:8, 36 - offset:39 - offset] = True
        self.assertTrue(np.isnan(self.edge.surface[patch]).all())
        self.assertTrue(np.isfinite(self.edge.surface[~patch]).all())
        self.assertFalse(self.edge.changed[patch].any())

    def test_the_cells_next_to_them_that_it_cuts_are_reported(self) -> None:
        """RF-015-13: las celdas que el borde corta junto a las sin dato (la corona de 6 × 5 menos las
        12 de dentro: 18) están en ``outside``, además de las de las filas 0 y 11 de la rejilla."""
        offset = self.window[1].start
        ring = np.zeros(self.edge.surface.shape, dtype=bool)
        ring[3:9, 35 - offset:40 - offset] = True
        ring[4:8, 36 - offset:39 - offset] = False
        self.assertTrue(self.edge.outside[ring & self.edge.changed].all())
        self.assertEqual(int((ring & self.edge.changed).sum()), 18)
        border = np.zeros(ring.shape, dtype=bool)
        border[[0, 11], :] = True
        np.testing.assert_array_equal(self.edge.outside,
                                      self.edge.changed & (ring | border))


# --- Sin semillas ------------------------------------------------------------------------------


class NoSeedsTest(unittest.TestCase):
    """RF-015-22, RF-015-06: si ninguna celda de la huella queda en la rasante no hay borde."""

    def test_a_footprint_that_cannot_be_cut_has_no_edge(self) -> None:
        """RF-015-22: con el corte no admitido en toda la rejilla no hay semillas: la superficie es
        la de la huella aplicada, sin volumen, sin pared y sin avisos del borde."""
        grid = tilted_grid(12, 60)
        z = tilt(grid, 300.0, 0.5)
        none = np.zeros(grid.shape, dtype=bool)
        job = make_job(grid, z, box_polygon(20.0, 0.0, 30.0, 12.0), level=305.0, angle=20.0,
                       reach=15.5, cut_allowed=none, fill_allowed=none)
        _footprint, applied, edge = run(job)
        np.testing.assert_array_equal(edge.surface, applied.surface)
        self.assertEqual((edge.cut_m3, edge.fill_m3, edge.wall_max_m), (0.0, 0.0, 0.0))
        self.assertEqual((edge.wall_x, edge.wall_y), (None, None))
        self.assertFalse(edge.changed.any() or edge.in_reach.any() or edge.steep.any())
        self.assertEqual(edge.walls, ())
        self.assertEqual(edge.created.pairs, 0)
        self.assertEqual(edge.notices, ())


# --- La métrica --------------------------------------------------------------------------------


class MetricTest(unittest.TestCase):
    """RF-015-22 (D-22): la euclídea exacta y el *chamfer* 5×5 de la 013. A lo largo de un eje el
    *chamfer* mide 0,98644 de la distancia exacta: la envolvente es ``rasante + t · 0,98644 · k`` y
    el alcance llega una celda más (con 20,9 m: la 20 con la exacta, la 21 con el *chamfer*)."""

    ROWS, COLS = 12, 100
    REACH = 20.9

    @classmethod
    def setUpClass(cls) -> None:
        cls.grid = tilted_grid(cls.ROWS, cls.COLS)
        cls.z = tilt(cls.grid, 300.0, 0.5)
        cls.t = math.tan(math.radians(20.0))
        geometry = box_polygon(40.0, 0.0, 50.0, float(cls.ROWS))
        cls.exact = run(make_job(cls.grid, cls.z, geometry, level=310.0, angle=20.0,
                                 reach=cls.REACH, metric="exact"))
        cls.chamfer = run(make_job(cls.grid, cls.z, geometry, level=310.0, angle=20.0,
                                   reach=cls.REACH, metric="chamfer5"))

    def east_depth(self, k: int, scale: float) -> float:
        return 14.75 + 0.5 * k - self.t * scale * k

    def test_the_exact_metric_by_hand(self) -> None:
        """RF-015-22: con la exacta, el corte por el este de las 20 celdas del alcance es ``14,75 +
        0,5 k − t k``; la pared, la de la 20."""
        _footprint, _applied, edge = self.exact
        east = math.fsum(self.east_depth(k, 1.0) for k in range(1, 21))
        west = math.fsum(10.25 - (0.5 + self.t) * k for k in range(1, 12))
        self.assertAlmostEqual(edge.cut_m3 / (self.ROWS * (east + west)), 1.0, delta=TOL)
        self.assertAlmostEqual(edge.wall_max_m / self.east_depth(20, 1.0), 1.0, delta=TOL)

    def test_the_chamfer_metric_by_hand(self) -> None:
        """RF-015-22: con el *chamfer*, la envolvente baja ``0,98644 · t · k`` (el corte por el este
        es mayor y llega a la celda 21) y por el oeste ``10,25 − (0,5 + 0,98644 t) k`` hasta la 11."""
        _footprint, _applied, edge = self.chamfer
        east = math.fsum(self.east_depth(k, SCALE) for k in range(1, 22))
        west = math.fsum(10.25 - (0.5 + self.t * SCALE) * k for k in range(1, 12))
        self.assertLess(10.25 - (0.5 + self.t * SCALE) * 12, 0.0)
        self.assertAlmostEqual(edge.cut_m3 / (self.ROWS * (east + west)), 1.0, delta=TOL)
        self.assertAlmostEqual(edge.wall_max_m / self.east_depth(21, SCALE), 1.0, delta=TOL)

    def test_the_chamfer_slope_is_gentler_than_the_exact_one(self) -> None:
        """RF-015-22, ADR-0014: en la celda 5 del este, la envolvente del *chamfer* queda a
        ``0,98644`` de la altura sobre la rasante de la exacta."""
        first_e, first_c = self.exact[0].window[1].start, self.chamfer[0].window[1].start
        found_e = self.exact[2].surface[4, 49 + 5 - first_e] - 310.0
        found_c = self.chamfer[2].surface[4, 49 + 5 - first_c] - 310.0
        self.assertAlmostEqual(found_c / found_e, SCALE, delta=TOL)

    def test_the_chamfer_reach_goes_one_cell_further(self) -> None:
        """RF-015-22: con 20,9 m el alcance de la exacta son 20 celdas y el del *chamfer* 21: la
        columna 70 solo cambia con él."""
        first_e, first_c = self.exact[0].window[1].start, self.chamfer[0].window[1].start
        self.assertEqual(self.exact[2].surface[4, 70 - first_e], self.z[4, 70])
        self.assertNotEqual(self.chamfer[2].surface[4, 70 - first_c], self.z[4, 70])
        self.assertEqual(self.chamfer[2].surface[4, 71 - first_c], self.z[4, 71])

    def test_a_long_chamfer_reach_does_not_leave_its_window(self) -> None:
        """A0, RF-015-22: con 300,5 m de alcance el *chamfer* llega a 304 celdas (304 · 0,98644 = 299,9 m; la 305
        ya pasa) y no a las 300 de la exacta; la ventana (305 + 2 celdas por lado) lo cubre, el corte
        llega entero hasta la columna 413 y ninguna celda de la última columna de la ventana
        cambia."""
        grid = tilted_grid(6, 800)
        z = tilt(grid, 300.0, 0.5)
        job = make_job(grid, z, box_polygon(100.0, 0.0, 110.0, 6.0), level=340.0, angle=20.0,
                       reach=300.5, metric="chamfer5")
        footprint, _applied, edge = run(job)
        first = footprint.window[1].start
        self.assertGreaterEqual(footprint.window[1].stop, 109 + 305 + 2)
        self.assertTrue(edge.changed[:, 109 + 304 - first].all())
        self.assertFalse(edge.changed[:, 109 + 305 - first].any())
        self.assertFalse(edge.in_reach[:, -1].any() or edge.changed[:, -1].any())
        exact = run(make_job(grid, z, box_polygon(100.0, 0.0, 110.0, 6.0), level=340.0,
                             angle=20.0, reach=300.5, metric="exact"))[2]
        self.assertFalse(exact.changed[:, 109 + 301 - exact.window[1].start].any())

    def test_the_window_covers_the_reach_of_the_metric(self) -> None:
        """A0, RF-015-22: la ventana del *chamfer* es una celda mayor por cada lado, para que lo que el alcance
        puede tocar (``alcance / 0,98644``) no salga de ella: con un alcance de 100 m y celdas de
        0,5 m, 205 celdas y no las 202 de la exacta."""
        self.assertEqual(self.exact[0].window[1].start, 40 - 23)
        self.assertEqual(self.chamfer[0].window[1].start, 40 - 24)
        grid = qfx.grid_of(0.5)
        box = (slice(300, 320), slice(300, 320))
        exact = platform.work_window(*box, 100.0, grid, Metric.EXACT)
        chamfer = platform.work_window(*box, 100.0, grid, Metric.CHAMFER5)
        self.assertEqual(exact, platform.work_window(*box, 100.0, grid))
        self.assertEqual(300 - exact[0].start, 202)
        self.assertEqual(300 - chamfer[0].start, 205)


class MeshFactorTest(unittest.TestCase):
    """RF-015-22 (D-7): la pendiente de la envolvente es ``tan(ángulo de borde) · factor de malla``
    (la de la entidad, de (0; 1], como la de la 013: T45, D-3): con 0,5 y con 0,8 el corte es más tendido que con
    1,0 (un factor de más de 1 haría la envolvente más empinada que el ángulo de borde: se rechaza)."""

    ROWS, COLS = 12, 100

    @classmethod
    def setUpClass(cls) -> None:
        cls.grid = tilted_grid(cls.ROWS, cls.COLS)
        cls.z = tilt(cls.grid, 300.0, 0.5)

    def edge_for(self, mesh: float) -> Any:
        job = make_job(self.grid, self.z, box_polygon(40.0, 0.0, 50.0, float(self.ROWS)),
                       level=310.0, angle=20.0, reach=20.5, mesh=mesh)
        return run(job)[2]

    def test_the_cut_by_hand_with_each_factor(self) -> None:
        """RF-015-22 (D-7): con ``t = 0,5 · tan 20°`` y con ``0,8 · tan 20°`` el corte de cada lado es
        ``Σ máx(0, depth_k)`` en las 20 celdas del alcance, por el este ``14,75 + 0,5 k − t k`` y por
        el oeste ``10,25 − 0,5 k − t k``, a ≤ 10⁻⁹ relativo; el factor queda en el borde."""
        for mesh in (0.5, 0.8):
            with self.subTest(mesh=mesh):
                t = math.tan(math.radians(20.0)) * mesh
                east = math.fsum(max(0.0, 14.75 + 0.5 * k - t * k) for k in range(1, 21))
                west = math.fsum(max(0.0, 10.25 - 0.5 * k - t * k) for k in range(1, 21))
                edge = self.edge_for(mesh)
                self.assertAlmostEqual(edge.cut_m3 / (self.ROWS * (east + west)), 1.0, delta=TOL)
                self.assertEqual(edge.mesh_factor, mesh)
                self.assertEqual(edge.limit_deg, 21.0)

    def test_the_default_factor_is_one(self) -> None:
        """RF-015-22 (D-7): sin factor de malla, el de por defecto (1,0) da lo mismo que pedirlo."""
        job = make_job(self.grid, self.z, box_polygon(40.0, 0.0, 50.0, float(self.ROWS)),
                       level=310.0, angle=20.0, reach=20.5)
        np.testing.assert_array_equal(run(job)[2].surface, self.edge_for(1.0).surface)


class CoarseGridTest(unittest.TestCase):
    """RF-015-22: con celdas de 2 m (4 m² cada una) el alcance y la envolvente se miden en metros y el
    volumen y la pared llevan el área de la celda: ``z = 300 + 0,25·x`` (0,5 m por celda), plataforma
    plana a 305 m en las columnas 10 a 19, 20° y un alcance de 20,5 m (10 celdas)."""

    ROWS, COLS = 12, 60

    @classmethod
    def setUpClass(cls) -> None:
        cls.grid = tilted_grid(cls.ROWS, cls.COLS, 2.0)
        cls.z = tilt(cls.grid, 300.0, 0.25)
        cls.t = math.tan(math.radians(20.0))
        job = make_job(cls.grid, cls.z, box_polygon(20.0, 0.0, 40.0, 24.0), level=305.0,
                       angle=20.0, reach=20.5)
        cls.footprint, cls.applied, cls.edge = run(job)

    def test_the_volume_and_the_wall_by_hand_in_metres(self) -> None:
        """RF-015-22: por el este ``4,75 + 0,5 k − 2 t k`` (la envolvente sube ``2 t`` por celda) en las
        10 celdas del alcance y nada por el oeste (el terreno queda por debajo); el volumen lleva los 4
        m² de la celda; la pared, el corte de la celda 1."""
        east = math.fsum(4.75 + 0.5 * k - 2.0 * self.t * k for k in range(1, 11))
        self.assertAlmostEqual(self.edge.cut_m3 / (self.ROWS * east * 4.0), 1.0, delta=TOL)
        self.assertEqual(self.edge.cell_area_m2, 4.0)
        self.assertEqual(self.edge.cut_cells, self.ROWS * 10)
        self.assertAlmostEqual(self.edge.wall_max_m / (4.75 + 0.5 - 2.0 * self.t), 1.0, delta=TOL)
        self.assertEqual((self.edge.wall_x, self.edge.wall_y), centre(self.grid, 0, 20))

    def test_the_reach_is_in_metres(self) -> None:
        """RF-015-22: con 20,5 m el alcance son 10 celdas de 2 m (la 11 queda como el terreno) y la
        pared del límite ocupa 12 celdas, 48 m²."""
        first = self.footprint.window[1].start
        self.assertNotEqual(self.edge.surface[4, 29 - first], self.z[4, 29])
        self.assertEqual(self.edge.surface[4, 30 - first], self.z[4, 30])
        wall = self.edge.walls[0]
        self.assertEqual((wall.cause, wall.cells, wall.area_m2),
                         (platform.WallCause.REACH, self.ROWS, 4.0 * self.ROWS))


class CausePrecedenceTest(unittest.TestCase):
    """RF-015-22, RF-015-13: una celda junto al límite del alcance y junto a lo que las máscaras no
    dejan mover cuenta como del alcance (la envolvente no pasa de ahí, aunque no hubiera máscara)."""

    def test_the_reach_wins_when_both_apply(self) -> None:
        """Con la máscara de 3 × 3 celdas pegada al límite (columnas 46 a 48; el límite está en la 49),
        las 12 celdas de la columna 49 son del alcance, también las 5 junto a la máscara, y las 11 de
        alrededor de la máscara que no son del límite, de las máscaras."""
        grid = tilted_grid(12, 80)
        z = tilt(grid, 300.0, 0.5)
        cut_ok = np.ones(grid.shape, dtype=bool)
        cut_ok[3:6, 46:49] = False
        job = make_job(grid, z, box_polygon(20.0, 0.0, 30.0, 12.0), level=305.0, angle=20.0,
                       reach=20.5, cut_allowed=cut_ok)
        _footprint, _applied, edge = run(job)
        by_cause = {wall.cause: wall.cells for wall in edge.walls}
        self.assertEqual(by_cause, {platform.WallCause.REACH: 12, platform.WallCause.MASKS: 11})
        self.assertEqual(edge.held_cells, 9)


# --- Rechazos ----------------------------------------------------------------------------------


class RejectionTest(unittest.TestCase):
    """RF-015-08, RF-015-22 (D-20): lo que falta o sale de rango se rechaza nombrando la
    plataforma, el campo y el valor, antes de calcular."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.grid = tilted_grid(12, 100)
        cls.z = tilt(cls.grid, 300.0, 0.5)
        cls.job = make_job(cls.grid, cls.z, box_polygon(40.0, 0.0, 50.0, 12.0), level=310.0,
                           angle=20.0, reach=20.5)
        cls.footprint = platform.platform_footprint(cls.job)
        cls.applied = platform.apply_platform(cls.job, cls.footprint)

    def edge_with(self, **changes: object) -> Any:
        """El borde del trabajo con los valores cambiados (``None`` quita uno)."""
        values = {**self.job.values, **changes}
        values = {key: value for key, value in values.items() if value is not None}
        job = dataclasses.replace(self.job, values=values)
        return platform.platform_edge(job, self.footprint, self.applied, PROJECT)

    def test_a_platform_without_a_reach_is_rejected(self) -> None:
        """RF-015-08, D-20: sin ``reach_m`` (``None``) es ``des.entity_param_missing`` con el campo
        ``des.platform.plt_001.reach_m``; con 0 o con más de 10.000 m, ``des.entity_param_range``;
        no se elige un alcance por la persona."""
        with self.assertRaises(DesignError) as caught:
            self.edge_with(reach_m=None)
        self.assertEqual(caught.exception.code, "des.entity_param_missing")
        self.assertEqual(caught.exception.field, "des.platform.plt_001.reach_m")
        self.assertIn("«P1»", caught.exception.text)
        for value in (0.0, -3.0, 10_000.5):
            with self.subTest(reach=value), self.assertRaises(DesignError) as caught:
                self.edge_with(reach_m=value)
            self.assertEqual(caught.exception.code, "des.entity_param_range")
            self.assertEqual(caught.exception.value, value)

    def test_the_edge_angle_is_required_and_inside_its_range(self) -> None:
        """RF-015-08, D-7: sin ángulo de borde, ``des.entity_param_missing``; con 0 o 90 (ambos
        excluidos), ``des.entity_param_range``."""
        with self.assertRaises(DesignError) as caught:
            self.edge_with(edge_angle_deg=None)
        self.assertEqual(caught.exception.code, "des.entity_param_missing")
        self.assertEqual(caught.exception.field, "des.platform.plt_001.edge_angle_deg")
        for value in (0.0, 90.0, 120.0):
            with self.subTest(angle=value), self.assertRaises(DesignError) as caught:
                self.edge_with(edge_angle_deg=value)
            self.assertEqual(caught.exception.code, "des.entity_param_range")

    def test_the_mesh_factor_and_the_metric_are_checked(self) -> None:
        """RF-015-08: un factor de malla fuera de (0; 1] es ``des.entity_param_range`` y una
        métrica que no es de la lista, ``des.entity_param_choice``; sin ellos, los de por
        defecto (1,0 y exacta)."""
        for value in (0.0, 1.0000001, 11.0):
            with self.subTest(mesh=value), self.assertRaises(DesignError) as caught:
                self.edge_with(mesh_factor=value)
            self.assertEqual(caught.exception.code, "des.entity_param_range")
        with self.assertRaises(DesignError) as caught:
            self.edge_with(metric="chamfer3")
        self.assertEqual(caught.exception.code, "des.entity_param_choice")
        default = self.edge_with()
        self.assertEqual((default.mesh_factor, default.metric), (1.0, Metric.EXACT))

    def test_the_project_parameters_must_be_given(self) -> None:
        """RF-013-30, RF-014-21: la tolerancia de cara y lo del salto creado los lee quien llama de
        los parámetros del proyecto; sin ellos es un error del programa (``ValueError``)."""
        for key in PROJECT:
            with self.subTest(key=key):
                project = {name: value for name, value in PROJECT.items() if name != key}
                with self.assertRaises(ValueError):
                    platform.platform_edge(self.job, self.footprint, self.applied, project)

    def test_a_footprint_whose_window_does_not_cover_the_reach_is_a_program_error(self) -> None:
        """A0, RF-015-22: una huella calculada con un alcance menor no cubre lo que el alcance del trabajo
        puede tocar: ``ValueError`` (el cálculo no sale de la ventana)."""
        short = dataclasses.replace(self.job, values={**self.job.values, "reach_m": 3.5})
        footprint = platform.platform_footprint(short)
        applied = platform.apply_platform(short, footprint)
        with self.assertRaises(ValueError):
            platform.platform_edge(self.job, footprint, applied, PROJECT)

    def test_the_envelope_needs_square_cells(self) -> None:
        """RF-015-22, ADR-0014: las envolventes se calculan en celdas cuadradas; una rejilla de 2 × 3 m es un
        error del programa (``ValueError``)."""
        grid = gis.Grid(cfx.BASE[0], cfx.BASE[1] + 36.0, 2.0, 3.0, 40, 12)
        z = tilt(grid, 300.0, 0.5)
        job = make_job(grid, z, box_polygon(20.0, 0.0, 40.0, 36.0), level=305.0, angle=20.0,
                       reach=9.5)
        footprint = platform.platform_footprint(job)
        applied = platform.apply_platform(job, footprint)
        with self.assertRaises(ValueError):
            platform.platform_edge(job, footprint, applied, PROJECT)


# --- Por pasos y sin tocar lo leído ------------------------------------------------------------


class StepsTest(unittest.TestCase):
    """RF-015-22 (plan §5.3.2): el borde por pasos da lo mismo que de una vez, sin modificar nada de
    lo que lee, y cerrar a mitad no deja nada."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.grid = tilted_grid(12, 100)
        cls.z = tilt(cls.grid, 300.0, 0.5)
        cls.job = make_job(cls.grid, cls.z, box_polygon(40.0, 0.0, 50.0, 12.0), level=310.0,
                           angle=20.0, reach=20.5, mode="cut_fill")
        cls.footprint = platform.platform_footprint(cls.job)
        cls.applied = platform.apply_platform(cls.job, cls.footprint)
        cls.direct = platform.platform_edge(cls.job, cls.footprint, cls.applied, PROJECT)

    def test_the_steps_give_the_same_edge(self) -> None:
        """RF-015-22: por pasos de 0 s (una unidad por paso) el resultado es el de una vez, bit a bit, y solo
        el último paso lleva el resultado; hay varios pasos."""
        steps = list(platform.platform_edge_steps(self.job, self.footprint, self.applied, PROJECT,
                                                  budget_s=0.0))
        self.assertGreater(len(steps), 3)
        self.assertTrue(all(step.result is None for step in steps[:-1]))
        self.assertEqual({step.phase for step in steps}, {"platform_edge"})
        edge = steps[-1].result
        np.testing.assert_array_equal(edge.surface, self.direct.surface)
        np.testing.assert_array_equal(edge.steep, self.direct.steep)
        self.assertEqual((edge.cut_m3, edge.fill_m3, edge.wall_max_m, edge.walls),
                         (self.direct.cut_m3, self.direct.fill_m3, self.direct.wall_max_m,
                          self.direct.walls))
        self.assertEqual([item.code for item in edge.notices],
                         [item.code for item in self.direct.notices])

    def test_the_default_budget_gives_the_result_too(self) -> None:
        """RF-015-22: con el presupuesto por defecto (0,05 s), el mismo borde."""
        edge = final_steps(platform.platform_edge_steps(self.job, self.footprint, self.applied,
                                                        PROJECT))
        np.testing.assert_array_equal(edge.surface, self.direct.surface)

    def test_closing_halfway_leaves_nothing_and_changes_no_input(self) -> None:
        """RF-015-22, principio 7: cerrar el generador a mitad no deja nada; las entradas quedan bit a bit como estaban y
        el resultado es una superficie nueva."""
        start, cut, fill = self.job.start.copy(), self.job.cut_allowed.copy(), \
            self.job.fill_allowed.copy()
        surface, levels = self.applied.surface.copy(), self.footprint.levels.copy()
        at_level = self.applied.at_level.copy()
        steps = platform.platform_edge_steps(self.job, self.footprint, self.applied, PROJECT,
                                             budget_s=0.0)
        next(steps)
        next(steps)
        steps.close()
        platform.platform_edge(self.job, self.footprint, self.applied, PROJECT)
        np.testing.assert_array_equal(self.job.start, start)
        np.testing.assert_array_equal(self.job.cut_allowed, cut)
        np.testing.assert_array_equal(self.job.fill_allowed, fill)
        np.testing.assert_array_equal(self.applied.surface, surface)
        np.testing.assert_array_equal(self.footprint.levels, levels)
        np.testing.assert_array_equal(self.applied.at_level, at_level)
        self.assertFalse(np.shares_memory(self.direct.surface, self.applied.surface))
        self.assertFalse(np.shares_memory(self.direct.surface, self.job.start))
        self.assertEqual(self.direct.surface.dtype, np.float64)


# --- Los avisos --------------------------------------------------------------------------------


class NoticesTest(unittest.TestCase):
    """RF-015-13, RF-013-30: los avisos del borde en español e inglés, con sus números y su lugar."""

    @classmethod
    def setUpClass(cls) -> None:
        grid = tilted_grid(12, 100)
        cls.edge = run(make_job(grid, tilt(grid, 300.0, 0.5), box_polygon(40.0, 0.0, 50.0, 12.0),
                                level=310.0, angle=20.0, reach=20.5))[2]

    def test_the_steep_wall_notice_names_the_entity_the_angles_and_the_causes(self) -> None:
        """RF-015-22, RF-015-13: «Plataforma «P1»: 12 celdas de su borde…», con el ángulo de borde,
        la tolerancia, la peor y su límite, su lugar absoluto y cuántas son del alcance, de las
        máscaras y de otra causa; el singular con una sola celda."""
        notice = self.edge.notices[0]
        self.assertEqual(notice.code, "des.platform_edge_steep")
        values = notice.values
        self.assertEqual((values["entity"], values["cells"], values["angle"], values["tolerance"],
                          values["limit"]), ("P1", 12, 20.0, 1.0, 21.0))
        self.assertEqual((values["at_reach"], values["at_masks"], values["other"]), (12, 0, 0))
        self.assertEqual((values["x"], values["y"]), (self.edge.walls[0].x, self.edge.walls[0].y))
        text = notice.text()
        self.assertIn("Plataforma «P1»", text)
        self.assertIn("12 celdas", text)
        self.assertNotIn("{", text)
        self.assertIn("Platform «P1»", notice.text("en"))
        one = preview.Notice("des.platform_edge_steep", {**values, "cells": 1})
        self.assertIn("1 celda de su borde queda", one.text())
        self.assertIn("1 cell of its edge", one.text("en"))

    def test_the_grid_border_notice_is_the_one_of_the_common_frame(self) -> None:
        """RF-015-13: lo que llega al borde de la rejilla usa ``des.entity_edge_outside`` con la
        entidad, las celdas, su área y el lugar de la primera."""
        notice = self.edge.notices[1]
        self.assertEqual(notice.code, "des.entity_edge_outside")
        self.assertEqual((notice.values["entity"], notice.values["cells"]), ("P1", 62))
        self.assertIn("62 celdas", notice.text())


class MagnitudeTest(unittest.TestCase):
    """RF-013-30, RF-015-13: el aviso de magnitud del desmonte y del terraplén de la entidad frente a
    la revisión congelada anterior."""

    def previous(self) -> Any:
        return design_report.Previous("Plataforma P1", "R02", 1000.0, 200.0)

    def test_a_cut_above_the_threshold_warns(self) -> None:
        """RF-013-30: con 2.500 m³ de corte frente a 1.000 y un umbral de 2 veces avisa del desmonte (con la
        revisión, las veces y el umbral); el terraplén de 300 frente a 200 (1,5 veces) no."""
        found = platform.magnitude_notices(2500.0, 300.0, self.previous(), 2.0, "P1")
        self.assertEqual([notice.code for notice in found], ["des.magnitude_cut"])
        values = found[0].values
        self.assertEqual((values["current"], values["previous"], values["ratio"],
                          values["threshold"], values["revision"]), (2500, 1000, 2.5, 2.0, "R02"))
        self.assertEqual(values["operation"], "Plataforma P1")
        self.assertIn("2,5 veces", found[0].text())

    def test_the_fill_warns_the_same_way(self) -> None:
        """RF-013-30: el terraplén de 600 m³ frente a 200 (3 veces) avisa con ``des.magnitude_fill``."""
        found = platform.magnitude_notices(900.0, 600.0, self.previous(), 2.0)
        self.assertEqual([notice.code for notice in found], ["des.magnitude_fill"])

    def test_without_an_earlier_revision_a_note_says_so(self) -> None:
        """RF-013-30: sin revisión anterior, la nota de que no se compara (con el nombre de la operación)."""
        found = platform.magnitude_notices(2500.0, 300.0, None, 2.0, "P1")
        self.assertEqual([notice.code for notice in found], ["des.magnitude_no_reference"])
        self.assertEqual(found[0].values["operation"], "P1")

    def test_exactly_the_threshold_does_not_warn(self) -> None:
        """RF-013-30: el 2,0 exacto no avisa («más del umbral»), y un volumen anterior de 0 m³ no se compara."""
        previous = design_report.Previous("P", "R01", 1000.0, 0.0)
        self.assertEqual(platform.magnitude_notices(2000.0, 50.0, previous, 2.0, "P"), ())

    def test_a_threshold_that_is_not_above_one_is_a_program_error(self) -> None:
        """RF-013-30: un umbral que no es un número finito mayor que 1 es ``ValueError`` (como el informe)."""
        for bad in (1.0, 0.5, float("nan"), float("inf")):
            with self.subTest(ratio=bad), self.assertRaises(ValueError):
                platform.magnitude_notices(1.0, 1.0, self.previous(), bad)


if __name__ == "__main__":
    unittest.main()
