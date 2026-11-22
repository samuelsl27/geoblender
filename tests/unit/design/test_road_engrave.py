# SPDX-License-Identifier: GPL-3.0-or-later
"""Aplicar la sección de la pista y su borde con dos ángulos (spec 017, T13; HU-017-1; RF-017-21, 22, 23 y 06; RNF-017-04, 06 y 07; plan 017 §5.4 A8 y A9, §5.7 P-4
y P-11): ``road_engrave.engrave`` baja a la rasante las celdas de la sección donde el corte se admite y sube las que quedan por debajo donde se admite el
relleno, agrupa las celdas de la calzada que no quedan en ella con su causa (las máscaras o la altura máxima de desmonte y terraplén), une la sección con el
terreno con el ángulo de desmonte hacia arriba y el de terraplén hacia abajo (la copia de ``platform._edge_units`` con dos envolventes) y da el corte y el
relleno de la sección y del borde por separado, las alturas máximas, la pared, la afección de «preferible no afectar» y los avisos del borde.

Los valores esperados salen **a mano** y por **fuerza bruta** (``tests.support.road_data.hand_engrave``: un bucle por celda de la sección y la envolvente de
todas las semillas con ``design_oracles.brute_force_euclidean``) en las mismas celdas, **no** de llamar al código bajo prueba. Todo es sintético, en el dominio y sin
Blender, sobre una rejilla de 120 × 120 celdas de 1 m y con un alcance de 12,5 m (la ventana de trabajo es de unos miles de celdas); el caso de referencia
(CE-017-01, la rampa de 200 m), en ``tests/referencia/des/test_ref_road_engrave`` y la pista de 2 km a escala (RNF-017-04), en ``milestone_road_engrave``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import math
import time
import unittest
from collections.abc import Callable
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import road_data as rd
from tests.support.package import import_geoblender

gis = import_geoblender("gis")
params = import_geoblender("design.params")
platform = import_geoblender("design.platform")
provenance = import_geoblender("design.provenance")
road_axis = import_geoblender("design.road_axis")
road_engrave = import_geoblender("design.road_engrave")
road_section = import_geoblender("design.road_section")

GRID = gis.Grid(cfx.BASE[0], cfx.BASE[1] + 120.0, 1.0, 1.0, 120, 120)
"""La rejilla de las pruebas: 120 × 120 celdas de 1 m (la esquina suroeste en ``BASE``), con las coordenadas locales de ``rd.local_centers``."""
LINE = ((30.0, 60.0), (70.0, 60.0))
"""El eje de las pruebas (local): 40 m de oeste a este a lo largo de un borde de celda (y = 60)."""
SHORT = rd.profile_with(reach_m=12.5)
"""El perfil de referencia con un alcance de 12,5 m (que ninguna distancia entre centros de celda iguala: la métrica exacta no tiene empates en el alcance)."""
PROJECT = {params.TOLERANCE_FACE: 1.0, params.VERIFY_MIN_THICKNESS: 0.05, params.EDGE_MAX_STEP: 1.0, params.EDGE_MIN_SHARE: 99.0}
"""Los parámetros del proyecto que lee el borde (valores de la prueba, no de un proyecto)."""
TOL = 1e-9
"""La tolerancia de las cuentas a mano (RF-017-21: ≤ 10⁻⁹ relativo; las cotas, ≤ 10⁻⁹ m)."""
Z_OF = Callable[[np.ndarray, np.ndarray], np.ndarray]


def plane(cross_pct: float) -> Z_OF:
    """El plano de la rampa del 4 % al este con una pendiente transversal de ``cross_pct`` % al norte (el eje en y = 60: la misma cota en el eje)."""
    return lambda x, y: 100.0 + 0.04 * x + cross_pct / 100.0 * (y - 60.0)


def rolling(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Un terreno ondulado en los dos ejes: desmonte y terraplén a los lados de un eje con curvas."""
    return 100.0 + 0.04 * x + 0.10 * (y - 60.0) + 3.0 * np.sin(x / 9.0) + 2.0 * np.cos(y / 7.0)


def flat(height: float) -> Z_OF:
    """Un terreno llano a ``height`` m."""
    return lambda x, y: np.full(np.shape(x), float(height))


@dataclasses.dataclass(slots=True)
class Case:
    """Un grabado preparado: el terreno, el eje, la sección y su rasante por celda, el trabajo y las máscaras de su ventana (con lo intocable ya quitado)."""

    grid: Any
    terrain: np.ndarray
    profile: Any
    road_profile: Any
    axis: Any
    section: Any
    levels: np.ndarray
    job: Any
    cut_ok: np.ndarray
    fill_ok: np.ndarray

    @property
    def window(self) -> tuple[slice, slice]:
        return self.section.window  # type: ignore[no-any-return]

    def engrave(self, project: Any = None, **options: Any) -> Any:
        """El grabado entero (``engrave``)."""
        return road_engrave.engrave(self.job, self.section, self.levels, PROJECT if project is None else project, **options)

    def by_hand(self, *, max_height_m: float | None = None) -> Any:
        """El grabado a mano en las mismas celdas."""
        return rd.hand_engrave(
            self.grid, self.window, self.terrain, self.levels, self.section.cells, self.section.kind, self.cut_ok, self.fill_ok,
            cut_deg=self.profile.cut_angle_deg, fill_deg=self.profile.fill_angle_deg, reach_m=self.profile.reach_m, mesh_factor=self.profile.mesh_factor,
            max_height_m=max_height_m)


def build(z_of: Z_OF, *, line: Any = LINE, profile: Any = SHORT, level_of: Callable[[np.ndarray], np.ndarray] | None = None, cut_allowed: np.ndarray | None = None,
          fill_allowed: np.ndarray | None = None, untouchable: np.ndarray | None = None, avoid_weight: np.ndarray | None = None,
          route: Any = None, grid: Any = GRID, avoid_zone: np.ndarray | None = None) -> Case:
    """El grabado de la pista de eje ``line`` (local) sobre el terreno ``z_of``: con la rasante ``level_of`` (de las estaciones del eje a cotas) o, sin ella, la del
    terreno en el eje; con ``route`` (los parámetros de la ruta) el trabajo es «trazar» y lleva la altura máxima de desmonte y terraplén; sin ella, «sobre un eje»."""
    terrain = np.asarray(z_of(*rd.local_centers(grid)), dtype=np.float64)
    road_profile = rd.road_profile(profile)
    axis = road_axis.axis_of(rd.absolute(line, grid), profile.curve_radius_m, profile.min_radius_m, profile.station_step_m)
    window = road_engrave.engrave_window(axis, road_profile, grid)
    section = road_section.section_cells(axis, profile.carriageway_m, profile.shoulder_m, profile.berm_m, terrain, grid, window)
    on_axis = road_section.sample_terrain(terrain, grid, axis.points[:, 0], axis.points[:, 1]) if level_of is None else level_of(axis.stations)
    levels = section.levels(axis.stations, on_axis)
    if route is None:
        job = rd.axis_job(grid, terrain, rd.absolute(line, grid), profile=profile, cut_allowed=cut_allowed, fill_allowed=fill_allowed,
                          untouchable=untouchable, avoid_weight=avoid_weight, avoid_zone=avoid_zone)
    else:
        first, last = rd.absolute(line, grid)[0], rd.absolute(line, grid)[-1]
        job = rd.route_job(grid, terrain, (float(first[0]), float(first[1])), (float(last[0]), float(last[1])), route=route, profile=profile,
                           untouchable=untouchable, avoid_weight=avoid_weight, avoid_zone=avoid_zone)
        job = dataclasses.replace(job, cut_allowed=np.ones(grid.shape, bool) if cut_allowed is None else cut_allowed,
                                  fill_allowed=np.ones(grid.shape, bool) if fill_allowed is None else fill_allowed)
    free = ~job.untouchable
    return Case(grid, terrain, profile, road_profile, axis, section, levels, job, (job.cut_allowed & free)[window], (job.fill_allowed & free)[window])


def box_mask(box: tuple[float, float, float, float], grid: Any = GRID) -> np.ndarray:
    """Las celdas de ``grid`` con el centro dentro de la caja local ``(izquierda, abajo, derecha, arriba)``."""
    return rd.in_box(box, grid)


class ApplyTest(unittest.TestCase):
    def test_the_carriageway_cut_and_fill_are_those_of_the_cells_by_hand_on_a_20_percent_cross_slope(self) -> None:
        """RF-017-21, CE-017-01: sobre el plano del 4 % con una pendiente transversal del 20 %, con la rasante en el terreno del eje, el corte y el relleno de la
        calzada (10,5 m) de un eje de 40 m son los del cálculo a mano en las mismas celdas (cinco filas por lado: 100 m³ cada uno) a ≤ 10⁻⁹ relativo; el de la
        sección entera suma además el caballón de 1 m del lado bajo (una fila de 5,5 m: 40 · 0,2 · 5,5 = 44 m³ más de relleno)."""
        case = build(plane(20.0))
        found = case.engrave()
        by_hand = rd.ramp_calzada_by_hand(length_m=40.0)
        drop = (case.terrain[case.window] - found.applied)
        calzada = case.section.kind == int(road_section.SectionClass.CARRIAGEWAY)
        self.assertEqual(by_hand.rows_per_side, 5)
        self.assertEqual(int(calzada.sum()), 2 * by_hand.rows_per_side * by_hand.columns)
        np.testing.assert_allclose(float(np.maximum(drop[calzada], 0.0).sum()), by_hand.cut_m3, rtol=TOL)
        np.testing.assert_allclose(float(np.maximum(-drop[calzada], 0.0).sum()), by_hand.fill_m3, rtol=TOL)
        np.testing.assert_allclose(found.section_cut_m3, by_hand.cut_m3, rtol=TOL)
        np.testing.assert_allclose(found.section_fill_m3, by_hand.fill_m3 + 40 * 0.2 * 5.5, rtol=TOL)

    def test_every_cell_of_the_section_is_on_its_gradient_where_the_masks_admit_it(self) -> None:
        """RF-017-21, RF-017-22: con el corte y el relleno admitidos en todas partes, cada celda de la sección queda **exactamente** en la cota de su rasante, ninguna
        celda de la calzada queda fuera de ella (sin grupos ni confirmación) y la superficie fuera de la sección y de su borde es la de partida bit a bit."""
        case = build(plane(20.0))
        found = case.engrave()
        fp = found.footprint
        np.testing.assert_array_equal(found.applied[fp], case.levels[fp])
        self.assertEqual(found.off_level, ())
        self.assertFalse(found.needs_confirmation)
        np.testing.assert_array_equal(found.at_level, fp)
        start = case.terrain[case.window]
        quiet = ~fp & ~found.changed
        np.testing.assert_array_equal(found.surface[quiet], start[quiet])

    def test_a_cell_the_masks_do_not_let_cut_stays_as_in_the_start_and_is_grouped_with_its_cause(self) -> None:
        """RF-017-21, RF-017-22, RF-017-06: una zona de la calzada donde el corte no se admite (la mitad norte, sobre la rasante) queda como en la partida y se
        agrupa (4-conexa) con su área, su diferencia máxima, su lugar y la causa «máscaras» (``cut_allowed``); hay que confirmarla para crear la pista."""
        cut_allowed = ~box_mask((50.0, 60.0, 60.0, 62.0))
        case = build(plane(20.0), cut_allowed=cut_allowed)
        found = case.engrave()
        by_hand = case.by_hand()
        self.assertTrue(found.needs_confirmation)
        causes = {group.cause for group in found.off_level}
        self.assertEqual(causes, {road_engrave.EngraveCause.CUT_DENIED})
        self.assertEqual(len(found.off_level), 1)
        group = found.off_level[0]
        rows, cols = np.nonzero(by_hand.off["cut_allowed"])
        self.assertEqual(group.cells, rows.size)
        self.assertEqual(group.cells, 2 * 10, "dos filas de la calzada (0,5 y 1,5 m al norte) por diez columnas")
        self.assertEqual(group.area_m2, 20.0)
        gap = (case.terrain[case.window] - case.levels)[by_hand.off["cut_allowed"]]
        self.assertAlmostEqual(group.max_m, float(gap.max()), delta=TOL)
        self.assertAlmostEqual(group.max_m, 0.2 * 1.5, delta=TOL)
        window = case.window
        self.assertAlmostEqual(group.x, float(case.grid.west + (cols.mean() + window[1].start + 0.5) * case.grid.dx), delta=TOL)
        self.assertAlmostEqual(group.y, float(case.grid.north - (rows.mean() + window[0].start + 0.5) * case.grid.dy), delta=TOL)
        np.testing.assert_array_equal(np.sort(group.index), np.sort(rows * case.section.cells.shape[1] + cols))
        np.testing.assert_array_equal(found.applied[by_hand.off["cut_allowed"]], case.terrain[window][by_hand.off["cut_allowed"]])
        self.assertTrue(found.cut_denied[by_hand.off["cut_allowed"]].all())

    def test_a_cell_the_masks_do_not_let_fill_is_grouped_with_the_fill_cause(self) -> None:
        """RF-017-21, RF-017-22: una zona de la calzada donde el relleno no se admite (al sur, bajo la rasante) da un grupo de causa ``fill_allowed``."""
        fill_allowed = ~box_mask((40.0, 58.0, 45.0, 60.0))
        case = build(plane(20.0), fill_allowed=fill_allowed)
        found = case.engrave()
        by_hand = case.by_hand()
        self.assertEqual([group.cause for group in found.off_level], [road_engrave.EngraveCause.FILL_DENIED])
        group = found.off_level[0]
        self.assertEqual(group.cells, int(by_hand.off["fill_allowed"].sum()))
        self.assertEqual(group.cells, 2 * 5)
        self.assertAlmostEqual(group.max_m, 0.2 * 1.5, delta=TOL)
        self.assertTrue(found.fill_denied[by_hand.off["fill_allowed"]].all())
        self.assertFalse(found.cut_denied.any())

    def test_untouchable_cells_do_not_move(self) -> None:
        """RF-017-06, RF-017-21: lo intocable (y las exclusiones) no admite ningún movimiento: sus celdas de la sección quedan como en la partida (un grupo de la
        calzada por el corte o el relleno que se le impide) y el borde tampoco las toca."""
        untouchable = box_mask((48.0, 58.0, 52.0, 62.0))
        case = build(plane(20.0), untouchable=untouchable)
        found = case.engrave()
        window = case.window
        inside = untouchable[window]
        np.testing.assert_array_equal(found.surface[inside], case.terrain[window][inside])
        causes = {group.cause for group in found.off_level}
        self.assertEqual(causes, {road_engrave.EngraveCause.CUT_DENIED, road_engrave.EngraveCause.FILL_DENIED})
        by_hand = case.by_hand()
        np.testing.assert_allclose(found.surface, by_hand.surface, rtol=0, atol=TOL)

    def test_a_millimetre_is_the_tolerance_of_the_gradient(self) -> None:
        """RF-017-22: una celda de la calzada que no se mueve y queda a ≤ 1 mm de su rasante (aquí a 0,5 mm) está en ella: no es un grupo y es una semilla del borde;
        a 1,5 mm de ella, sí es un grupo (de la causa de las máscaras) y no es semilla."""
        cut_allowed = ~box_mask((50.0, 60.0, 60.0, 62.0))
        case = build(plane(0.1), cut_allowed=cut_allowed)
        found = case.engrave()
        blocked = ~case.cut_ok & case.section.cells
        near = blocked & (np.abs(case.section.lateral + 0.5) < 0.1)
        far = blocked & (np.abs(case.section.lateral + 1.5) < 0.1)
        self.assertEqual((int(near.sum()), int(far.sum())), (10, 10))
        self.assertTrue(found.at_level[near].all(), "a 0,5 mm de su rasante, en ella")
        self.assertFalse(found.at_level[far].any(), "a 1,5 mm, fuera de ella")
        self.assertEqual([(group.cause.value, group.cells) for group in found.off_level], [("cut_allowed", 10)])
        self.assertAlmostEqual(found.off_level[0].max_m, 0.0015, delta=TOL)
        np.testing.assert_array_equal(found.applied[near], case.terrain[case.window][near])

    def test_the_height_limit_of_the_route_leaves_the_far_cells_as_they_were_and_is_a_cause(self) -> None:
        """RF-017-22, RF-017-12: en el modo «trazar», una celda de la sección cuyo movimiento pasa de la altura máxima de desmonte y terraplén de la ruta (aquí 0,8 m
        frente a los 0,9 m de la fila a 4,5 m del eje) no se mueve y es un grupo de causa ``max_height`` por lado; en «sobre un eje», sin esa altura, sí se mueve."""
        route = rd.route_with(max_cut_fill_m=0.8)
        case = build(plane(20.0), route=route)
        found = case.engrave()
        assert_like_by_hand(self, case, found, max_height_m=0.8)
        self.assertEqual([group.cause for group in found.off_level], [road_engrave.EngraveCause.MAX_HEIGHT] * 2)
        self.assertEqual([group.cells for group in found.off_level], [40, 40])
        self.assertTrue(all(abs(group.max_m - 0.2 * 4.5) <= TOL for group in found.off_level))
        free = build(plane(20.0)).engrave()
        self.assertEqual(free.off_level, ())
        self.assertIsNone(free.max_height_m)
        self.assertEqual(found.max_height_m, 0.8)

    def test_the_separated_groups_are_numbered_and_not_mixed_across_causes(self) -> None:
        """RF-017-22: dos zonas separadas (4-conexas) de una misma causa son dos grupos; la numeración sigue sin repetirse entre causas (de 1 en adelante, primero el
        corte que no se admite y luego el relleno)."""
        cut_allowed = ~(box_mask((35.0, 60.0, 38.0, 62.0)) | box_mask((55.0, 60.0, 58.0, 62.0)))
        fill_allowed = ~box_mask((45.0, 58.0, 48.0, 60.0))
        case = build(plane(20.0), cut_allowed=cut_allowed, fill_allowed=fill_allowed)
        found = case.engrave()
        self.assertEqual([group.group for group in found.off_level], [1, 2, 3])
        self.assertEqual([group.cause.value for group in found.off_level], ["cut_allowed", "cut_allowed", "fill_allowed"])
        self.assertEqual([group.cells for group in found.off_level], [6, 6, 6])
        self.assertLess(found.off_level[0].x, found.off_level[1].x)


def assert_like_by_hand(test: unittest.TestCase, case: Case, found: Any, *, max_height_m: float | None = None) -> Any:
    """La superficie, las máscaras, los grupos y las cifras del borde y de la sección de ``found`` son las del cálculo a mano (fuerza bruta) en las mismas celdas."""
    by_hand = case.by_hand(max_height_m=max_height_m)
    np.testing.assert_allclose(found.applied, by_hand.applied, rtol=0, atol=TOL)
    np.testing.assert_allclose(found.surface, by_hand.surface, rtol=0, atol=TOL)
    np.testing.assert_array_equal(found.at_level, by_hand.at_level)
    np.testing.assert_array_equal(found.changed, by_hand.changed)
    np.testing.assert_array_equal(found.held, by_hand.held)
    np.testing.assert_array_equal(found.in_reach & ~found.footprint, by_hand.reachable)
    for name in ("section_cut_m3", "section_fill_m3", "edge_cut_m3", "edge_fill_m3", "cut_height_max_m", "fill_height_max_m"):
        np.testing.assert_allclose(getattr(found, name), getattr(by_hand, name), rtol=TOL, atol=0.0, err_msg=name)
    np.testing.assert_allclose(found.wall_max_m, by_hand.wall_max_m, rtol=TOL, atol=0.0)
    for cause in road_engrave.EngraveCause:
        mine = np.sort(np.concatenate([group.index for group in found.off_level if group.cause is cause] or [np.empty(0, dtype=np.int64)]))
        np.testing.assert_array_equal(mine, np.flatnonzero(by_hand.off[cause.value]), err_msg=cause.value)
    test.assertIsNotNone(by_hand)
    return by_hand


class EdgeTest(unittest.TestCase):
    def test_the_edge_of_a_straight_road_with_two_angles_is_the_brute_force_envelope(self) -> None:
        """RF-017-21 (A9): el borde de la pista recta sobre el plano con pendiente transversal es, celda a celda, la envolvente ascendente (60°) del lado alto y la
        descendente (35°) del bajo de **todas** las semillas por fuerza bruta, con el alcance como la distancia a la semilla más próxima; la superficie, las celdas
        movidas, las que sus máscaras no dejan mover, el corte y el relleno del borde, su pared y las alturas máximas salen del cálculo a mano a ≤ 10⁻⁹."""
        case = build(plane(20.0))
        found = case.engrave()
        by_hand = assert_like_by_hand(self, case, found)
        self.assertGreater(by_hand.edge_fill_m3, 0.0, "el lado bajo se rellena con el ángulo de terraplén")
        self.assertGreater(found.edge_cut_m3 + found.edge_fill_m3, 0.0)
        self.assertEqual(found.cut_angle_deg, 60.0)
        self.assertEqual(found.fill_angle_deg, 35.0)

    def test_the_two_angles_are_the_ones_of_the_profile_and_each_side_uses_its_own(self) -> None:
        """RF-017-21: con un terreno llano 2 m sobre la rasante (todo desmonte) el borde sube con la tangente del ángulo de **desmonte**, y con uno 2 m bajo ella (todo
        terraplén), baja con la del ángulo de **terraplén**: en la primera celda fuera de la sección, ``rasante ± tan(ángulo)`` (con el factor de malla 1)."""
        level = lambda s: np.full(np.shape(s), 100.0)  # noqa: E731
        case = build(flat(102.0), level_of=level)
        up = case.engrave()
        down = build(flat(98.0), level_of=level).engrave()
        centre_cols = np.flatnonzero(case.section.cells.any(axis=0))
        mid = int(centre_cols[len(centre_cols) // 2])
        column = up.surface[:, mid]
        in_section = np.flatnonzero(case.section.cells[:, mid])
        north, south = in_section.min(), in_section.max()
        t_cut, t_fill = math.tan(math.radians(60.0)), math.tan(math.radians(35.0))
        self.assertAlmostEqual(float(column[north - 1]), 100.0 + t_cut, delta=TOL)
        self.assertAlmostEqual(float(column[south + 1]), 100.0 + t_cut, delta=TOL)
        self.assertAlmostEqual(float(down.surface[north - 1, mid]), 100.0 - t_fill, delta=TOL)
        self.assertAlmostEqual(float(down.surface[south + 1, mid]), 100.0 - t_fill, delta=TOL)

    def test_a_rolling_terrain_with_corners_and_random_masks_is_the_brute_force_one(self) -> None:
        """RF-017-21, RF-017-06, RF-017-22: un eje con una esquina (radio 12 m), un terreno ondulado y máscaras de corte y de relleno al azar (con celdas de la sección
        que no se mueven y un borde que las respeta): la superficie, las máscaras, los grupos con su causa y todas las cifras son las de la fuerza bruta."""
        rng = np.random.default_rng(7)
        cut_allowed = rng.random(GRID.shape) > 0.12
        fill_allowed = rng.random(GRID.shape) > 0.12
        z0 = float(rolling(np.array(30.0), np.array(60.0)))
        case = build(rolling, line=((30.0, 60.0), (60.0, 60.0), (60.0, 90.0)), level_of=lambda s: z0 + 0.05 * s, cut_allowed=cut_allowed, fill_allowed=fill_allowed)
        found = case.engrave()
        assert_like_by_hand(self, case, found)
        self.assertGreater(len(found.off_level), 0)
        self.assertGreater(int(found.held.sum()), 0, "lo que las máscaras no dejan mover del borde queda como estaba")
        start = case.terrain[case.window]
        np.testing.assert_array_equal(found.surface[found.held], start[found.held])

    def test_no_cell_is_cut_or_filled_where_the_masks_do_not_admit_it_and_the_rest_is_untouched(self) -> None:
        """RF-017-21, RF-017-06: ninguna celda baja donde el corte no se admite ni sube donde el relleno no se admite (sección y borde), y fuera de lo que mueve la
        superficie es la de partida bit a bit."""
        rng = np.random.default_rng(11)
        cut_allowed = rng.random(GRID.shape) > 0.3
        fill_allowed = rng.random(GRID.shape) > 0.3
        case = build(rolling, line=((30.0, 70.0), (80.0, 70.0)), level_of=lambda s: 110.0 + 0.02 * s, cut_allowed=cut_allowed, fill_allowed=fill_allowed)
        found = case.engrave()
        start = case.terrain[case.window]
        self.assertTrue((found.surface[~case.cut_ok] >= start[~case.cut_ok]).all())
        self.assertTrue((found.surface[~case.fill_ok] <= start[~case.fill_ok]).all())
        moved = found.surface != start
        self.assertTrue(moved.any())
        np.testing.assert_array_equal(moved, found.footprint & (found.applied != start) | found.changed)
        outside_reach = ~found.in_reach
        np.testing.assert_array_equal(found.surface[outside_reach], start[outside_reach])

    def test_the_metric_of_the_profile_is_the_one_used(self) -> None:
        """RF-017-21: con la métrica exacta, la primera celda fuera de la sección sube o baja ``tan(ángulo)``; con el *chamfer* 5×5, que a lo largo de un eje mide
        0,98644 de la distancia exacta, ``0,98644 · tan(ángulo)``; y sin nada que mover (el terreno ya es la rasante) las dos métricas dejan la partida igual."""
        level = lambda s: np.full(np.shape(s), 100.0)  # noqa: E731
        exact = build(flat(102.0), level_of=level, profile=SHORT)
        chamfer = build(flat(102.0), level_of=level, profile=rd.profile_with(reach_m=12.5, metric="chamfer5"))
        a, b = exact.engrave(), chamfer.engrave()
        self.assertEqual(a.metric.value, "exact")
        self.assertEqual(b.metric.value, "chamfer5")
        scale = 0.98644
        t_cut = math.tan(math.radians(60.0))
        for case, found, factor in ((exact, a, 1.0), (chamfer, b, scale)):
            columns = np.flatnonzero(case.section.cells.any(axis=0))
            mid = int(columns[len(columns) // 2])
            north = int(np.flatnonzero(case.section.cells[:, mid]).min())
            self.assertAlmostEqual(float(found.surface[north - 1, mid]), 100.0 + factor * t_cut, delta=TOL)
        self.assertNotEqual(a.edge_cut_m3, b.edge_cut_m3)
        self.assertTrue((a.in_reach != b.in_reach).any(), "el alcance se mide con la métrica del perfil")
        quiet_exact = build(plane(0.0), level_of=lambda s: 100.0 + 0.04 * (30.0 + s)).engrave()
        quiet_chamfer = build(plane(0.0), profile=rd.profile_with(reach_m=12.5, metric="chamfer5"), level_of=lambda s: 100.0 + 0.04 * (30.0 + s)).engrave()
        for quiet in (quiet_exact, quiet_chamfer):
            self.assertAlmostEqual(quiet.cut_m3 + quiet.fill_m3, 0.0, delta=TOL)
            self.assertEqual(int(quiet.changed.sum()), 0)

    def test_the_mesh_factor_of_the_profile_multiplies_the_tangent_of_both_angles(self) -> None:
        """RF-017-21: el factor de malla del perfil multiplica la tangente de los dos ángulos: con 0,5, la primera celda fuera de la sección sube ``0,5 · tan(60°)``."""
        level = lambda s: np.full(np.shape(s), 100.0)  # noqa: E731
        case = build(flat(102.0), level_of=level, profile=rd.profile_with(reach_m=12.5, mesh_factor=0.5))
        found = case.engrave()
        columns = np.flatnonzero(case.section.cells.any(axis=0))
        mid = int(columns[len(columns) // 2])
        north = int(np.flatnonzero(case.section.cells[:, mid]).min())
        self.assertAlmostEqual(float(found.surface[north - 1, mid]), 100.0 + 0.5 * math.tan(math.radians(60.0)), delta=TOL)

    def test_on_a_steep_hillside_the_edge_cuts_higher_than_the_section(self) -> None:
        """RF-017-21, RF-017-23: sobre una ladera del 200 % (más empinada que el ángulo de desmonte) la altura máxima de desmonte es la del **borde**, mayor que la de
        la sección (9 m en el borde de la calzada frente a más de 9,2 m en la primera celda del borde), y todo es el de la fuerza bruta."""
        case = build(plane(200.0))
        found = case.engrave()
        assert_like_by_hand(self, case, found)
        start = case.terrain[case.window]
        section_cut = float(np.max((start - found.applied)[found.footprint]))
        self.assertAlmostEqual(section_cut, 2.0 * 4.5, delta=TOL)
        self.assertGreater(found.cut_height_max_m, section_cut + 0.2)
        self.assertGreater(found.fill_height_max_m, 0.0)

    def test_each_wall_is_judged_with_the_angle_of_its_own_kind(self) -> None:
        """RF-017-21: la pared del borde en el límite del alcance se juzga con el ángulo de **terraplén** si la celda sube (36° con su tolerancia) y con el de **desmonte** si
        baja (61°): un escalón de 1 m en 1 m (45°) de un terraplén se avisa; el de 1,37 m en 1 m (54°) de un desmonte, no."""
        level = lambda s: np.full(np.shape(s), 100.0)  # noqa: E731
        reach = rd.profile_with(reach_m=3.5)
        fill = build(flat(96.9), level_of=level, profile=reach).engrave()
        cut = build(flat(103.1), level_of=level, profile=reach).engrave()
        self.assertGreater(fill.steep_cells, 0)
        self.assertEqual({wall.cause.value for wall in fill.walls}, {"reach"})
        self.assertGreater(fill.walls[0].max_deg, 45.0 - 1e-6, "al menos el escalón de 1 m en 1 m (45°); en las esquinas del alcance, algo más")
        self.assertEqual(cut.steep_cells, 0)
        self.assertEqual(cut.walls, ())
        self.assertFalse([item for item in cut.notices if item.code == "des.road_edge_steep"])

    def test_a_wall_next_to_what_the_masks_do_not_let_move_has_the_masks_as_its_cause(self) -> None:
        """RF-017-21, RF-017-06 (RF-015-13): la pared que queda junto a lo que las máscaras no dejan mover es de causa «máscaras» (``masks``): tanto junto a una celda del
        **borde** que no se corta (aquí un bloque a 2 m de la sección) como junto a una celda de la **sección** que no se corta."""
        level = lambda s: np.full(np.shape(s), 100.0)  # noqa: E731
        reach = rd.profile_with(reach_m=3.5)
        edge_masks = build(flat(108.0), level_of=level, profile=reach, cut_allowed=~box_mask((44.0, 66.0, 56.0, 70.0))).engrave()
        self.assertGreater(edge_masks.held_cells, 0)
        self.assertIn("masks", {wall.cause.value for wall in edge_masks.walls})
        section_masks = build(flat(108.0), level_of=level, profile=reach, cut_allowed=~box_mask((45.0, 62.0, 55.0, 65.0))).engrave()
        masks = [wall for wall in section_masks.walls if wall.cause.value == "masks"]
        self.assertTrue(masks)
        notice = next(item for item in section_masks.notices if item.code == "des.road_edge_steep")
        self.assertEqual(notice.values["at_masks"], masks[0].cells)

    def test_the_walls_steeper_than_the_angle_are_only_at_the_reach_limit_or_next_to_the_masks(self) -> None:
        """RF-017-21, RF-017-13 (RF-015-13): con una meseta 8 m sobre la rasante y un alcance de 3,5 m, el borde se corta en el límite del alcance y queda una pared
        más empinada que el ángulo de desmonte (60°) más la tolerancia de cara (1°): sus celdas están en ``walls`` con la causa «alcance» y el aviso
        ``des.road_edge_steep`` las cuenta con el ángulo, el alcance y el lugar; donde el terreno ya era así de empinado no se avisa."""
        level = lambda s: np.full(np.shape(s), 100.0)  # noqa: E731
        case = build(flat(108.0), level_of=level, profile=rd.profile_with(reach_m=3.5))
        found = case.engrave()
        self.assertGreater(found.steep_cells, 0)
        causes = {wall.cause.value for wall in found.walls}
        self.assertEqual(causes, {"reach"})
        wall = found.walls[0]
        self.assertGreater(wall.max_deg, 61.0)
        notice = next(item for item in found.notices if item.code == "des.road_edge_steep")
        self.assertEqual(notice.values["entity"], "Pista de prueba")
        self.assertEqual(notice.values["cells"], found.steep_cells)
        self.assertEqual(notice.values["cut_angle"], 60.0)
        self.assertEqual(notice.values["fill_angle"], 35.0)
        self.assertEqual(notice.values["reach"], 3.5)
        self.assertEqual(notice.values["at_reach"], found.steep_cells)
        text = notice.text("es")
        self.assertIn("Pista «Pista de prueba»", text)
        self.assertIn("60", text)
        self.assertIn("en el límite del alcance", text)
        self.assertGreater(found.wall_max_m, 5.0)
        again = build(plane(20.0)).engrave()
        self.assertFalse([item for item in again.notices if item.code == "des.road_edge_steep"], "un terreno que cabe en el ángulo no avisa")


class NoticesTest(unittest.TestCase):
    def test_the_created_step_of_the_edge_is_the_one_of_the_013(self) -> None:
        """RF-017-21 (RF-014-21, error 48): el salto creado del borde (la pared cortada en el alcance de una meseta) lo mide ``created_steps`` de la superficie entera
        y avisa con ``des.edge_surface_step`` (con el nombre de la pista) y una nota por tramo."""
        level = lambda s: np.full(np.shape(s), 100.0)  # noqa: E731
        found = build(flat(108.0), level_of=level, profile=rd.profile_with(reach_m=3.5)).engrave()
        self.assertTrue(found.created.warned)
        codes = [item.code for item in found.notices]
        self.assertIn("des.edge_surface_step", codes)
        self.assertIn("des.edge_stretch", codes)
        first = next(item for item in found.notices if item.code == "des.edge_surface_step")
        self.assertEqual(first.values["surface"], "Pista de prueba")

    def test_what_reaches_the_border_of_the_grid_is_noticed_with_its_place(self) -> None:
        """RF-017-21 (RF-015-13): si el borde llega a una celda del borde de la rejilla, ``des.entity_edge_outside`` da las celdas, el área y el lugar de la primera;
        una pista lejos del borde no lo avisa."""
        case = build(plane(20.0), line=((30.0, 8.0), (70.0, 8.0)))
        found = case.engrave()
        notice = next(item for item in found.notices if item.code == "des.entity_edge_outside")
        self.assertEqual(notice.values["entity"], "Pista de prueba")
        self.assertEqual(notice.values["cells"], found.outside_cells)
        self.assertGreater(found.outside_cells, 0)
        self.assertEqual(notice.values["area"], found.outside_cells * GRID.cell_area)
        rows, cols = np.nonzero(found.outside)
        self.assertEqual(notice.values["x"], float(GRID.west + (cols[0] + case.window[1].start + 0.5) * GRID.dx))
        self.assertEqual(notice.values["y"], float(GRID.north - (rows[0] + case.window[0].start + 0.5) * GRID.dy))
        far = build(plane(20.0)).engrave()
        self.assertEqual(far.outside_cells, 0)
        self.assertNotIn("des.entity_edge_outside", [item.code for item in far.notices])

    def test_what_the_edge_moves_next_to_cells_without_data_is_noticed(self) -> None:
        """RF-017-21 (RF-015-13): una celda sin dato **fuera** de la sección (que no es un error: se queda sin dato) y el borde que se mueve junto a ella (a una celda, en los
        ocho vecinos) dan ``des.entity_edge_outside``: la superficie puede quedar cortada allí."""
        level = lambda s: np.full(np.shape(s), 100.0)  # noqa: E731
        hole = lambda x, y: np.where((np.abs(x - 50.5) < 0.1) & (np.abs(y - 66.5) < 0.1), np.nan, 108.0)  # noqa: E731
        case = build(hole, level_of=level, profile=rd.profile_with(reach_m=3.5))
        found = case.engrave()
        row, col = np.nonzero(~np.isfinite(case.terrain[case.window]))
        self.assertEqual(row.size, 1)
        near = np.zeros(found.changed.shape, dtype=bool)
        near[row[0] - 1:row[0] + 2, col[0] - 1:col[0] + 2] = True
        np.testing.assert_array_equal(found.outside, found.changed & near)
        self.assertGreater(found.outside_cells, 0)
        self.assertTrue(np.isnan(found.surface[row[0], col[0]]), "la celda sin dato sigue sin dato")
        self.assertIn("des.entity_edge_outside", [item.code for item in found.notices])

    def test_the_order_with_the_other_surface_of_a_quarry_is_noticed(self) -> None:
        """RF-017-21 (RF-015-14): con la partida la superficie de explotación de una cantera, la pista baja el resultado bajo la otra (la final: aquí la partida):
        ``order_check`` da las celdas, el área y lo que más pasa, y el aviso ``des.entity_quarry_order`` los dice; sin ``quarry`` no hay aviso."""
        level = lambda s: np.full(np.shape(s), 100.0)  # noqa: E731
        case = build(flat(102.0), level_of=level, profile=rd.profile_with(reach_m=3.5))
        order = platform.QuarryOrder("Cantera 1", "exploitation", "gis_dtm_explotacion", "gis_dtm_final", case.terrain.copy())
        found = case.engrave(quarry=order)
        self.assertIsNotNone(found.order)
        start = case.terrain[case.window]
        lowered = (start - found.surface) > 0.001
        self.assertEqual(found.order.cells, int(lowered.sum()))
        self.assertAlmostEqual(found.order.max_m, float((start - found.surface).max()), delta=TOL)
        notice = next(item for item in found.notices if item.code == "des.entity_quarry_order")
        self.assertEqual(notice.values["entity"], "Pista de prueba")
        self.assertEqual(notice.values["quarry"], "Cantera 1")
        self.assertEqual(notice.values["cells"], found.order.cells)
        self.assertIsNone(case.engrave().order)
        self.assertNotIn("des.entity_quarry_order", [item.code for item in case.engrave().notices])

    def test_the_effect_on_the_zones_to_preferably_avoid_is_area_volume_and_weighted_volume(self) -> None:
        """RF-017-06, RF-017-23: la afección de «preferible no afectar» (las celdas de peso mayor que 1 que la sección o el borde mueven) es su área (m²), el volumen
        movido (m³) y el volumen por su peso (m³ × peso), y se avisa con ``des.road_avoid_affected``; sin zonas, ceros y sin aviso."""
        weight = np.ones(GRID.shape)
        weight[box_mask((44.0, 50.0, 56.0, 66.0))] = 3.0
        weight[box_mask((56.0, 50.0, 60.0, 66.0))] = 5.0
        case = build(plane(20.0), avoid_weight=weight, cut_allowed=~box_mask((50.0, 60.0, 60.0, 66.0)))
        found = case.engrave()
        window = case.window
        start = case.terrain[window]
        gap = np.abs(found.surface - start)
        w = weight[window]
        moved = (gap > 0.0) & (w > 1.0)
        self.assertEqual(found.avoid_cells, int(moved.sum()))
        self.assertGreater(found.avoid_cells, 0)
        self.assertTrue((~case.cut_ok & found.footprint & (w > 1.0)).any(), "hay celdas de la zona que no se mueven y no cuentan")
        self.assertTrue((found.changed & (w > 1.0)).any(), "el borde también mueve celdas de la zona")
        np.testing.assert_allclose(found.avoid_m2, moved.sum() * GRID.cell_area, rtol=TOL)
        np.testing.assert_allclose(found.avoid_m3, gap[moved].sum() * GRID.cell_area, rtol=TOL)
        np.testing.assert_allclose(found.avoid_weighted_m3, (gap[moved] * w[moved]).sum() * GRID.cell_area, rtol=TOL)
        notice = next(item for item in found.notices if item.code == "des.road_avoid_affected")
        self.assertEqual(notice.values["entity"], "Pista de prueba")
        np.testing.assert_allclose(notice.values["area"], found.avoid_m2, rtol=TOL)
        none = build(plane(20.0)).engrave()
        self.assertEqual((none.avoid_cells, none.avoid_m2, none.avoid_m3, none.avoid_weighted_m3), (0, 0.0, 0.0, 0.0))
        self.assertNotIn("des.road_avoid_affected", [item.code for item in none.notices])

    def test_a_road_that_follows_the_terrain_does_not_affect_a_zone_by_the_noise_of_the_arithmetic(self) -> None:
        """RF-017-06, RF-017-23, CE-017-01, A-6: una pista cuya rasante es el terreno (una rampa del 7 %) con una zona «preferible no afectar» encima **no la afecta**: 0 celdas,
        0 m², 0 m³ y sin ``des.road_avoid_affected``, aunque la aritmética deje en 198 celdas de la sección un «movimiento» de 1,4·10⁻¹⁴ m (que ``!= 0`` contaba: 198 m² y un aviso
        donde no se movía nada); lo que pasa de la tolerancia numérica (10⁻⁹ m) sí cuenta."""
        weight = np.ones(GRID.shape)
        zone = box_mask((20.0, 40.0, 80.0, 80.0))
        weight[zone] = 3.0
        case = build(lambda x, y: 100.0 + 0.07 * x, avoid_weight=weight)
        found = case.engrave()
        gap = np.abs(case.terrain[case.window] - found.applied)
        noise = found.footprint & zone[case.window] & (gap > 0.0) & (gap < 1e-9)
        self.assertGreater(int(noise.sum()), 100, "la aritmética deja ruido bajo la zona: la prueba es del caso")
        self.assertEqual((found.avoid_cells, found.avoid_m2, found.avoid_m3, found.avoid_weighted_m3), (0, 0.0, 0.0, 0.0))
        self.assertNotIn("des.road_avoid_affected", [item.code for item in found.notices])

    def test_a_zone_of_weight_1_counts_in_the_effect(self) -> None:
        """RF-017-06, RF-017-23, S-2: una zona «preferible no afectar» de **peso exactamente 1** (válido: la 012 pide ≥ 1) cuenta en la afección como las demás —área, volumen y
        volumen por el peso (= el volumen) a mano, y el aviso—: la máscara de la zona va aparte del peso (con ``peso > 1`` salían 0 de sus celdas); con el peso 3 y 5, ``test_the_effect_on_the_zones…``."""
        zone = box_mask((44.0, 50.0, 56.0, 66.0))
        light = build(plane(20.0), avoid_weight=np.ones(GRID.shape), avoid_zone=zone)
        found = light.engrave()
        gap = np.abs(found.surface - light.terrain[light.window])
        moved = (gap > 1e-9) & zone[light.window]
        self.assertGreater(int(moved.sum()), 100)
        self.assertEqual(found.avoid_cells, int(moved.sum()))
        np.testing.assert_allclose(found.avoid_m2, moved.sum() * GRID.cell_area, rtol=TOL)
        np.testing.assert_allclose(found.avoid_m3, gap[moved].sum() * GRID.cell_area, rtol=TOL)
        np.testing.assert_allclose(found.avoid_weighted_m3, found.avoid_m3, rtol=TOL)
        notice = next(item for item in found.notices if item.code == "des.road_avoid_affected")
        np.testing.assert_allclose(notice.values["area"], found.avoid_m2, rtol=TOL)

    def test_the_effect_of_a_zone_counts_what_moves_by_more_than_the_numerical_tolerance(self) -> None:
        """RF-017-06, A-6, S-2: ``_avoid_effect`` cuenta las celdas **de la zona** (no el peso: el 1 es de la zona) que se mueven más de 10⁻⁹ m (sin signo: corte y relleno), con su
        volumen y su volumen por el peso; el ruido (1,4·10⁻¹⁴ m), lo que justo no pasa de la tolerancia y lo que se mueve fuera de la zona no cuentan."""
        zone = np.array([True, True, True, False, True, True])
        weight = np.array([1.0, 3.0, 1.5, 9.0, 1.0, 2.0])
        moved = np.array([0.5, -1.4e-14, -2.0, 4.0, 1e-9, 2e-9])
        cells, volume, weighted = road_engrave._avoid_effect(zone, weight, moved)
        self.assertEqual(cells, 3)
        self.assertAlmostEqual(volume, 0.5 + 2.0 + 2e-9, places=12)
        self.assertAlmostEqual(weighted, 0.5 * 1.0 + 2.0 * 1.5 + 2e-9 * 2.0, places=12)
        self.assertEqual(road_engrave._avoid_effect(np.zeros(3, dtype=bool), np.ones(3), np.ones(3)), (0, 0.0, 0.0))
        self.assertEqual(road_engrave._avoid_effect(np.ones(0, dtype=bool), np.ones(0), np.ones(0)), (0, 0.0, 0.0))

    def test_the_notice_of_a_carriageway_group_names_what_stops_it(self) -> None:
        """RF-017-22: el aviso de una celda de la calzada que no queda en su rasante (``des.road_carriageway_*``) lleva el área, la diferencia máxima y el lugar del
        grupo y, según su causa, lo que lo impide: las máscaras (``blocker``), la restricción de otra entidad (``other_entity``) o la altura máxima (``height_m``);
        sin el dato que su causa pide es un error del programa."""
        cut_allowed = ~box_mask((50.0, 60.0, 60.0, 62.0))
        group = build(plane(20.0), cut_allowed=cut_allowed).engrave().off_level[0]
        masks = road_engrave.carriageway_notice(group, "Pista de prueba", blocker="Límite de la concesión")
        self.assertEqual(masks.code, "des.road_carriageway_masks")
        self.assertEqual(masks.values["entity"], "Pista de prueba")
        self.assertEqual(masks.values["blocker"], "Límite de la concesión")
        self.assertEqual(masks.values["area"], group.area_m2)
        self.assertEqual(masks.values["difference"], round(group.max_m, 3))
        self.assertEqual((masks.values["x"], masks.values["y"]), (round(group.x, 2), round(group.y, 2)))
        self.assertIn("Límite de la concesión", masks.text("es"))
        other = road_engrave.carriageway_notice(group, "Pista de prueba", other_entity="PLT-001")
        self.assertEqual(other.code, "des.road_carriageway_entity")
        self.assertEqual(other.values["blocker"], "PLT-001")
        tall = build(plane(20.0), route=rd.route_with(max_cut_fill_m=0.8)).engrave().off_level[0]
        height = road_engrave.carriageway_notice(tall, "Pista de prueba", height_m=0.8)
        self.assertEqual(height.code, "des.road_carriageway_height")
        self.assertEqual(height.values["height"], 0.8)
        with self.assertRaises(ValueError):
            road_engrave.carriageway_notice(group, "Pista de prueba")
        with self.assertRaises(ValueError):
            road_engrave.carriageway_notice(tall, "Pista de prueba", blocker="x")


class FiguresTest(unittest.TestCase):
    def test_the_figures_of_the_engraving_are_those_of_the_13_and_the_provenance_accepts_them(self) -> None:
        """RF-017-23: ``figure_values`` da las doce cifras del grabado con las claves de ``provenance.ROAD_FIGURES`` (el área grabada, el corte y el relleno de la
        sección y del borde por separado, el neto, la pared, las alturas máximas y la afección de «preferible no afectar»); el neto es corte menos relleno de
        sección y borde juntos; y juntadas con las demás de la pista las acepta ``provenance.road_figures``."""
        found = build(plane(20.0)).engrave()
        values = found.figure_values()
        keys = {figure.key for figure in provenance.ROAD_FIGURES}
        self.assertLessEqual(set(values), keys)
        self.assertEqual(len(values), 12)
        self.assertEqual(values["des.road_area_m2"], found.footprint_cells * GRID.cell_area)
        self.assertEqual(values["des.road_cut_m3"], found.section_cut_m3)
        self.assertEqual(values["des.road_fill_m3"], found.section_fill_m3)
        self.assertEqual(values["des.road_edge_cut_m3"], found.edge_cut_m3)
        self.assertEqual(values["des.road_edge_fill_m3"], found.edge_fill_m3)
        np.testing.assert_allclose(values["des.road_net_m3"], found.section_cut_m3 + found.edge_cut_m3 - found.section_fill_m3 - found.edge_fill_m3, rtol=TOL)
        self.assertEqual(found.cut_m3, found.section_cut_m3 + found.edge_cut_m3)
        self.assertEqual(found.fill_m3, found.section_fill_m3 + found.edge_fill_m3)
        self.assertEqual(found.net_m3, values["des.road_net_m3"])
        self.assertEqual(values["des.road_wall_max_m"], found.wall_max_m)
        self.assertEqual(values["des.road_cut_height_max_m"], found.cut_height_max_m)
        self.assertEqual(values["des.road_fill_height_max_m"], found.fill_height_max_m)
        rest = {key: 1.0 for key in keys - set(values)}
        rest["des.road_curves"] = 0
        rest["des.road_radius_min_m"] = None
        made = provenance.road_figures("Pista de prueba", "RDW-001", {**rest, **values})
        self.assertEqual({figure.key for figure in made}, keys - {"des.road_radius_min_m"})

    def test_the_total_volumes_are_those_of_the_difference_between_the_start_and_the_result(self) -> None:
        """RF-017-23, CE-017-09: el corte y el relleno (sección y borde) son los de restar la superficie de partida y la resultante celda a celda por el área de la
        celda a ≤ 10⁻⁹ relativo (lo que dará la cubicación de la 011), y la altura máxima de desmonte y de terraplén, las diferencias mayores."""
        found = build(plane(20.0)).engrave()
        case_start = build(plane(20.0)).terrain
        start = case_start[found.window]
        drop = start - found.surface
        np.testing.assert_allclose(found.cut_m3, np.maximum(drop, 0.0).sum() * GRID.cell_area, rtol=TOL)
        np.testing.assert_allclose(found.fill_m3, np.maximum(-drop, 0.0).sum() * GRID.cell_area, rtol=TOL)
        self.assertAlmostEqual(found.cut_height_max_m, float(drop.max()), delta=TOL)
        self.assertAlmostEqual(found.fill_height_max_m, float((-drop).max()), delta=TOL)
        inside = found.footprint
        self.assertEqual(found.section_cut_cells, int((drop[inside] > 0.0).sum()))
        self.assertEqual(found.section_fill_cells, int((drop[inside] < 0.0).sum()))
        self.assertEqual(found.edge_cut_cells, int((drop[found.changed] > 0.0).sum()))
        self.assertEqual(found.edge_fill_cells, int((drop[found.changed] < 0.0).sum()))
        quiet = build(plane(0.0), level_of=lambda s: 100.0 + 0.04 * (30.0 + s)).engrave()
        self.assertIsNone(quiet.wall_x)
        self.assertIsNone(quiet.figure_values()["des.road_wall_max_m"], "sin borde no hay pared: la cifra no se registra")


class StepsTest(unittest.TestCase):
    def test_the_steps_end_in_the_same_result_bit_by_bit_and_each_call_is_short(self) -> None:
        """RF-017-30, RNF-017-06: por pasos la superficie, las máscaras y las cifras son las mismas bit a bit que de una vez, la misma entrada da la misma pista
        (``reproduce``), cada llamada del paso tarda ≤ 0,2 s y el último ``Progress`` lleva el resultado."""
        case = build(rolling, line=((30.0, 60.0), (60.0, 60.0), (60.0, 90.0)), level_of=lambda s: 105.0 + 0.04 * s)
        whole = case.engrave()
        steps = road_engrave.engrave_steps(case.job, case.section, case.levels, PROJECT, budget_s=0.0)
        longest, last, count = 0.0, None, 0
        while True:
            before = time.perf_counter()
            try:
                last = next(steps)
            except StopIteration:
                break
            longest, count = max(longest, time.perf_counter() - before), count + 1
        self.assertGreater(count, 1)
        self.assertLessEqual(longest, 0.2)
        self.assertEqual(last.phase, "road_engrave")
        found = last.result
        for name in ("surface", "applied", "at_level", "changed", "held", "steep", "outside", "in_reach"):
            np.testing.assert_array_equal(getattr(found, name), getattr(whole, name), err_msg=name)
        self.assertEqual(found.figure_values(), whole.figure_values())
        again = case.engrave()
        np.testing.assert_array_equal(again.surface, whole.surface)

    def test_closing_the_steps_midway_leaves_the_inputs_as_they_were(self) -> None:
        """RF-017-30, principio 7: cerrar el generador a mitad no modifica ninguna entrada (la superficie de partida, las máscaras, la sección y su rasante) ni deja
        nada hecho."""
        case = build(plane(20.0))
        keep = hashlib.sha256(case.job.start.tobytes() + case.levels.tobytes() + case.section.cells.tobytes() + case.job.cut_allowed.tobytes()).hexdigest()
        steps = road_engrave.engrave_steps(case.job, case.section, case.levels, PROJECT)
        next(steps)
        steps.close()
        after = hashlib.sha256(case.job.start.tobytes() + case.levels.tobytes() + case.section.cells.tobytes() + case.job.cut_allowed.tobytes()).hexdigest()
        self.assertEqual(keep, after)
        self.assertFalse(case.job.start.flags.writeable)

    def test_the_results_are_read_only_and_new(self) -> None:
        """RF-017-21: los arrays del resultado son de solo lectura y nuevos: la superficie de partida del trabajo no cambia."""
        case = build(plane(20.0))
        before = case.job.start.copy()
        found = case.engrave()
        for name in ("surface", "applied", "at_level", "changed", "held", "in_reach", "footprint"):
            self.assertFalse(getattr(found, name).flags.writeable, name)
        np.testing.assert_array_equal(case.job.start, before)
        self.assertFalse(np.shares_memory(found.surface, case.job.start))


class InputsTest(unittest.TestCase):
    def test_the_window_has_to_cover_what_the_reach_can_touch(self) -> None:
        """RF-017-21 (A0): una sección medida solo en la caja del corredor (sin el alcance) no basta para el borde: ``ValueError`` (error del programa) que manda ampliarla
        con ``engrave_window``; ``engrave_window`` es la caja del corredor ampliada por el alcance y dos celdas (``work_window``), recortada a la rejilla."""
        case = build(plane(20.0))
        axis, profile = case.axis, case.road_profile
        narrow = road_section.section_cells(axis, SHORT.carriageway_m, SHORT.shoulder_m, SHORT.berm_m, case.terrain, GRID, None)
        levels = narrow.levels(axis.stations, np.full(axis.stations.shape, 100.0))
        with self.assertRaisesRegex(ValueError, "engrave_window"):
            road_engrave.engrave(case.job, narrow, levels, PROJECT)
        box = road_section.section_window(axis, SHORT.carriageway_m, SHORT.shoulder_m, SHORT.berm_m, GRID)
        expected = platform.work_window(box[0], box[1], profile.reach_m, GRID, profile.metric)
        self.assertEqual(road_engrave.engrave_window(axis, profile, GRID), expected)
        self.assertGreater(expected[0].stop - expected[0].start, box[0].stop - box[0].start)

    def test_a_cell_of_the_section_without_data_is_a_program_error(self) -> None:
        """RF-015-09: la superficie de partida sin dato en la sección la rechaza antes la preparación (T19); aquí es ``ValueError``, no se oculta con un valor."""
        case = build(plane(20.0))
        hole = case.terrain.copy()
        hole[60, 50] = np.nan
        job = dataclasses.replace(case.job, start=hole)
        with self.assertRaisesRegex(ValueError, "sin dato"):
            road_engrave.engrave(job, case.section, case.levels, PROJECT)

    def test_the_inputs_that_do_not_fit_are_program_errors(self) -> None:
        """RF-017-21: una rasante que no es de la forma de la ventana, un parámetro del proyecto que falta o está fuera de rango y una sección sin celdas son
        ``ValueError`` (errores del programa: ningún valor se elige por la persona)."""
        case = build(plane(20.0))
        with self.assertRaises(ValueError):
            road_engrave.engrave(case.job, case.section, case.levels[:-1], PROJECT)
        for key in PROJECT:
            incomplete = {name: value for name, value in PROJECT.items() if name != key}
            with self.subTest(missing=key), self.assertRaises(ValueError):
                road_engrave.engrave(case.job, case.section, case.levels, incomplete)
        with self.assertRaises(ValueError):
            road_engrave.engrave(case.job, case.section, np.where(case.section.cells, np.nan, case.levels), PROJECT)


if __name__ == "__main__":
    unittest.main()
