# SPDX-License-Identifier: GPL-3.0-or-later
"""Sin ruta y el destino por cota (spec 017, T08; HU-017-1; RF-017-12, RF-017-02, RF-017-10 y RF-017-04; RNF-017-02; plan 017 §5.4 A3 y A2,
§5.8 H-1; CE-017-04; D-4): ``no_route`` (por qué no hay ruta: la cota a que se llega desde el origen y desde el destino, la pendiente mínima
necesaria y el tramo limitante con su causa y su lugar; el presupuesto agotado, que **no** es «no hay ruta»), ``route_target`` (el destino
por cota: los nodos de la zona de la rampa) y ``arrival_of`` (el destino alcanzado).

Todo en mallas de ≤ 100 × 100 nodos con unos cientos de nodos que se pisan (lo que pasa de 1 s va a ``milestone_*``, RNF-017-09). **Lo que se
comprueba no sale de ``design.road_route``**: las cifras de CE-017-04 son las de a mano de ``tests.support.road_data`` (la franja de un nodo
de 100 m de largo y 30 m de desnivel con pd = 10 %: hacen falta 300 m, se llega 10 m más alto y la pendiente mínima es del 30 %).
"""

from __future__ import annotations

import dataclasses
import math
import unittest
from typing import Any

import numpy as np

from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.unit.design import test_road_route as base

road_route = import_geoblender("design.road_route")
road_model = import_geoblender("design.road_model")
messages = import_geoblender("design.messages")
gis = import_geoblender("gis")

NoRouteCause = road_model.NoRouteCause
LimitCause = road_model.LimitCause
EAST = 4
"""El índice del rumbo al este en los 16 (el 0 es el norte, en sentido horario)."""
STRIP_ROUTE = {"mesh_m": 4.0, "level_step_m": 0.2, "max_cut_fill_m": 24.0, "lambda_per_m": 2.0, "turn_m": 2.0, "margin_m": 60.0,
               "simplify_m": 4.0, "arrival_tol_m": 0.25, "search_budget": 5_000_000}
"""Los parámetros de la franja (HIPÓTESIS de la prueba, T01-a): el paso de cota de 0,2 m **divide** lo que sube un paso (pd·4 m = 0,4 m: dos
niveles), así que la cota mayor alcanzada en los 100 m de la franja es exactamente la del origen + 10 m, y la altura de 24 m (≥ 20 m: el
terreno de la franja sube 30 m) no corta antes."""


def strip_case(*, closed: bool = False, **changes: Any) -> tuple[Any, Any, Any]:
    """El trabajo, la malla y el pasillo de la franja de CE-017-04 (la rejilla de la cantera, de 1 m; la malla de 4 m): el origen y el destino
    son los centros de su primer y de su último nodo (100 m, 30 m de desnivel con el terreno de la franja); con ``closed``, el intocable que
    cierra el único paso."""
    route = rd.route_with(**{**STRIP_ROUTE, **changes})
    grid = rd.GRID
    job = rd.route_job(grid, rd.strip_terrain(grid), tuple(rd.absolute([rd.STRIP_ORIGIN], grid)[0]),
                       tuple(rd.absolute([rd.STRIP_DESTINATION], grid)[0]), route=route,
                       untouchable=~rd.strip_allowed(grid, untouchable=closed))
    mesh, corridor = rd.route_corridor(job)
    return job, mesh, corridor


def absolute(point: tuple[float, float]) -> tuple[float, float]:
    """Un punto local de la cantera en absolutas (float64)."""
    x, y = rd.absolute([point])[0]
    return float(x), float(y)


class StripTest(unittest.TestCase):
    """CE-017-04: «una franja recta de 100 m de largo y 4 m de ancho (un nodo de la malla de la ruta) para un desnivel de 30 m con pd = 10 %
    (hacen falta 300 m), no hay ruta y el mensaje da la cota mayor alcanzada (la del origen + 10 m), la pendiente mínima necesaria (30 %) y
    el tramo limitante, sin registrar nada»."""

    def test_the_strip_that_cannot_climb_says_the_level_reached_the_gradient_and_the_limiting_stretch(self) -> None:
        """RF-017-12, RF-017-10, CE-017-04, HU-017-1: la red 2D alcanza el origen (la franja une los dos extremos) y la búsqueda 3D agota el
        pasillo (``CORRIDOR``): el diagnóstico da **la cota mayor alcanzada desde el origen** (la del origen + 10 m, de los estados vistos),
        la menor desde el destino (130 − 10 m), **la pendiente mínima necesaria** (30 m sobre los 100 m de la ruta más corta de la red 2D:
        30 %) y el tramo limitante, que es el destino (la ruta llega hasta él, pero no a su cota) con la pendiente como causa."""
        job, mesh, corridor = strip_case()
        self.assertTrue(corridor.reachable)
        self.assertEqual(corridor.lower_bound_m, 100.0)
        self.assertAlmostEqual(rd.needed_length_m(30.0, 10.0), rd.STRIP_NEEDED_M)
        route = base.solve(job, corridor)
        self.assertEqual((route.ok, route.cause), (False, NoRouteCause.CORRIDOR))
        found = road_route.no_route(job, corridor.net_origin, corridor.net_dest, route)
        self.assertEqual(found.cause, NoRouteCause.CORRIDOR)
        self.assertAlmostEqual(found.z_origin_m, rd.STRIP_Z_ORIGIN_M, delta=1e-9)
        self.assertAlmostEqual(found.z_destination_m, rd.STRIP_Z_ORIGIN_M + 30.0, delta=1e-9)
        self.assertTrue(found.rising)
        self.assertAlmostEqual(found.reached_from_origin_m, rd.STRIP_Z_ORIGIN_M + rd.STRIP_REACH_M, delta=1e-6)
        self.assertAlmostEqual(found.reached_from_destination_m, rd.STRIP_Z_ORIGIN_M + 30.0 - rd.STRIP_REACH_M, delta=1e-6)
        self.assertEqual((found.length_m, found.length_basis), (100.0, "network"))
        self.assertAlmostEqual(found.min_gradient_pct, 30.0, delta=1e-9)
        self.assertGreater(found.min_gradient_pct, job.profile.max_gradient_pct)
        limit = found.limit
        self.assertEqual(limit.cause, LimitCause.SLOPE)
        destination = mesh.node_of(*job.geometry.destination)
        self.assertEqual(limit.node, destination)
        self.assertEqual((limit.x, limit.y), mesh.center_of(*destination))
        self.assertIsNone(limit.heading)
        self.assertEqual((found.budget, found.margin_m), (None, 60.0))

    def test_the_levels_seen_by_the_search_are_kept_per_node_and_only_when_the_corridor_is_exhausted(self) -> None:
        """RF-017-12 (plan §5.4 A3, T07 aviso 9): la ruta con el pasillo agotado lleva, por nodo, la cota mayor y la menor de los estados vistos
        (``NaN`` donde no hubo ninguno; de solo lectura); con ruta, sin ruta por la red 2D o con el presupuesto agotado no se calculan (el
        presupuesto no las necesita: pagaría 16 pasadas sobre millones de estados)."""
        job, mesh, corridor = strip_case()
        route = base.solve(job, corridor)
        self.assertEqual(route.high_m.shape, mesh.shape)
        self.assertEqual(route.low_m.shape, mesh.shape)
        self.assertFalse(route.high_m.flags.writeable or route.low_m.flags.writeable)
        seen = np.isfinite(route.high_m)
        self.assertTrue(np.array_equal(seen, np.isfinite(route.low_m)))
        self.assertTrue(np.array_equal(seen, corridor.mask))  # el pasillo es la franja y la búsqueda la recorre entera
        self.assertTrue(bool((route.low_m[seen] <= route.high_m[seen]).all()))
        origin = mesh.node_of(*job.geometry.origin)
        self.assertAlmostEqual(float(route.high_m[origin]), rd.STRIP_Z_ORIGIN_M, delta=1e-9)  # el origen arranca en su cota
        self.assertAlmostEqual(float(route.low_m[origin]), rd.STRIP_Z_ORIGIN_M, delta=1e-9)
        self.assertAlmostEqual(float(np.nanmax(route.high_m)), rd.STRIP_Z_ORIGIN_M + rd.STRIP_REACH_M, delta=1e-6)
        job_ok, _mesh, corridor_ok = base.build(base.flat(9, 13), (4, 2), (4, 10))
        found = base.solve(job_ok, corridor_ok)
        self.assertTrue(found.ok)
        self.assertIsNone(found.high_m)
        self.assertIsNone(found.low_m)
        job_c, _mesh_c, corridor_c = strip_case(closed=True)
        self.assertIsNone(base.solve(job_c, corridor_c).high_m)  # NETWORK: no hay búsqueda
        self.assertIsNone(self.exhausted_budget(2_000)[1].high_m)

    def test_with_the_reference_height_the_cut_limit_stops_the_climb_before_the_strip_ends(self) -> None:
        """RF-017-12: con la altura máxima de desmonte y terraplén de la referencia (14 m) la ruta no llega a la cota del origen + 10 m: a 68 m
        (17 nodos) la rasante (100 + 0,4 por nodo) ya no puede seguir al terreno a menos de 14 m (el desmonte pasaría de la altura máxima) y se
        queda en 106,8 m; el tramo limitante es ese nodo y su causa **la altura máxima** (el paso siguiente no cabe por ella), no la pendiente."""
        job, mesh, corridor = strip_case(max_cut_fill_m=14.0)
        route = base.solve(job, corridor)
        self.assertEqual(route.cause, NoRouteCause.CORRIDOR)
        found = road_route.no_route(job, corridor.net_origin, corridor.net_dest, route)
        self.assertAlmostEqual(found.reached_from_origin_m, 106.8, delta=1e-6)
        self.assertAlmostEqual(found.min_gradient_pct, 30.0, delta=1e-9)
        stop = mesh.node_of(*absolute((170.0, 198.0)))  # 68 m del origen
        self.assertEqual(found.limit.cause, LimitCause.HEIGHT)
        self.assertEqual(found.limit.node, stop)
        self.assertEqual((found.limit.x, found.limit.y), mesh.center_of(*stop))
        self.assertEqual(found.limit.heading, EAST)

    def test_without_the_search_the_levels_come_from_the_2d_network_and_there_is_no_stretch_to_name(self) -> None:
        """RF-017-12: sin la ruta (``no_route(job, red del origen, red del destino)``, la firma de plan §5.3.1), la cota alcanzada sale de la
        red 2D (la cota inferior: ``cota + pd · distancia`` sin pasar de la altura máxima del terreno): 110 m desde el origen y 120 m desde
        el destino, lo mismo que con los estados vistos en la franja; la causa es la del pasillo y no se nombra un tramo (no se buscó)."""
        job, _mesh, corridor = strip_case()
        found = road_route.no_route(job, corridor.net_origin, corridor.net_dest)
        self.assertEqual(found.cause, NoRouteCause.CORRIDOR)
        self.assertAlmostEqual(found.reached_from_origin_m, 110.0, delta=1e-9)
        self.assertAlmostEqual(found.reached_from_destination_m, 120.0, delta=1e-9)
        self.assertAlmostEqual(found.min_gradient_pct, 30.0, delta=1e-9)
        self.assertIsNone(found.limit)

    def test_an_untouchable_that_closes_the_only_pass_gives_the_same_figures_with_its_zone(self) -> None:
        """RF-017-12, RF-017-06, CE-017-04: con un intocable que cierra el único paso la red 2D ni siquiera une los extremos (``NETWORK``, no
        hay búsqueda): se dice **la cota mayor alcanzada desde el origen** (cota + pd por los 44 m hasta el intocable: 104,4 m), la menor desde
        el destino (130 − pd por 48 m: 125,2 m), **la pendiente mínima necesaria** con la longitud en línea recta entre los nodos —la red no
        tiene una más corta— (30 m sobre 100 m: 30 %) y el tramo limitante: el último nodo que se alcanza antes del intocable, con la zona que
        las máscaras prohíben como causa, y su lugar."""
        job, mesh, corridor = strip_case(closed=True)
        self.assertFalse(corridor.reachable)
        route = base.solve(job, corridor)
        self.assertEqual((route.ok, route.cause, route.expanded), (False, NoRouteCause.NETWORK, 0))
        for given in (None, route):
            found = road_route.no_route(job, corridor.net_origin, corridor.net_dest, given)
            with self.subTest(route=given is not None):
                self.assertEqual(found.cause, NoRouteCause.NETWORK)
                self.assertAlmostEqual(found.reached_from_origin_m, 104.4, delta=1e-9)
                self.assertAlmostEqual(found.reached_from_destination_m, 125.2, delta=1e-9)
                self.assertEqual(found.length_basis, "straight")
                self.assertAlmostEqual(found.length_m, 100.0, delta=1e-9)
                self.assertAlmostEqual(found.min_gradient_pct, 30.0, delta=1e-9)
                stop = mesh.node_of(*absolute((146.0, 198.0)))  # el último nodo antes del intocable (148 a 152 m)
                self.assertEqual(found.limit.cause, LimitCause.MASK)
                self.assertEqual(found.limit.node, stop)
                self.assertEqual((found.limit.x, found.limit.y), mesh.center_of(*stop))
                self.assertEqual(found.limit.heading, EAST)
        self.assertTrue(strip_zone_closes_one_node(job, mesh))

    def test_the_rejection_names_the_figures_the_limit_and_nothing_else(self) -> None:
        """RF-017-12 (B2), RF-017-04: el rechazo es un ``DesignError`` del catálogo (``des.road_no_route_corridor`` o ``…_network``) con la capa, la
        pista, las dos cotas, la pendiente mínima y, detrás, la nota del tramo limitante con su lugar; en español y en inglés, sin ningún marcador
        sin valor; dice que no se relaja ningún límite ni se crea nada."""
        job, mesh, corridor = strip_case()
        route = base.solve(job, corridor)
        error = road_route.no_route(job, corridor.net_origin, corridor.net_dest, route).error(job)
        self.assertIsInstance(error, messages.DesignError)
        self.assertEqual(error.code, "des.road_no_route_corridor")
        self.assertEqual(error.field, "des.road.rdw_001.margin_m")
        self.assertEqual(error.values["z_origin"], 110.0)
        self.assertEqual(error.values["z_destination"], 120.0)
        self.assertEqual(error.values["gradient"], 30.0)
        self.assertEqual(error.values["layer"], "gis_fea_pistas_puntos")
        self.assertEqual([code for code, _values in error.notes], ["des.road_limit_slope"])
        for text in (error.text, error.text_in("en")):
            self.assertNotIn("?", text)
            self.assertNotIn("{", text)
        for expected in ("«Pista de prueba»", "110", "120", "30 %", "pendiente máxima de diseño", "10 %", "no se relaja ningún límite",
                         "no se crea nada"):
            self.assertIn(expected, error.text)
        job_c, mesh_c, corridor_c = strip_case(closed=True)
        error = road_route.no_route(job_c, corridor_c.net_origin, corridor_c.net_dest).error(job_c)
        self.assertEqual(error.code, "des.road_no_route_network")
        self.assertEqual(error.field, "des.road.rdw_001.max_cut_fill_m")
        self.assertEqual([code for code, _values in error.notes], ["des.road_limit_mask"])
        x, y = mesh_c.center_of(*mesh_c.node_of(*absolute((146.0, 198.0))))
        self.assertEqual((error.notes[0][1]["x"], error.notes[0][1]["y"]), (round(x, 3), round(y, 3)))
        self.assertIn("zona que las máscaras prohíben", error.text)
        self.assertNotIn("?", error.text)

    def exhausted_budget(self, budget: int) -> tuple[Any, Any, Any]:
        """Un caso que agota el presupuesto: bajar 2 m entre dos nodos a 20 m en un plano de 15 × 20 nodos con 60 m de holgura (como el de
        ``test_road_route``: hacen falta unos 20.000 estados expandidos); devuelve ``(trabajo, ruta, pasillo)``."""
        route = rd.route_with(**{**dataclasses.asdict(base.HYPOTHESES), "margin_m": 60.0, "search_budget": budget})
        job, _mesh, corridor = base.build(base.flat(15, 20), (7, 5), (7, 10), route=route, start_level_m=101.0, end_level_m=99.0)
        return job, base.solve(job, corridor), corridor

    def test_the_budget_is_a_third_cause_that_says_the_states_and_what_to_do(self) -> None:
        """RF-017-12 (P-3): la búsqueda que agota su presupuesto de estados da un rechazo distinto, ``des.road_budget``, con los estados
        explorados, el presupuesto y la holgura, y que reducir la holgura o subir el presupuesto puede dar una ruta; **no** es «no hay ruta»
        (sin cotas ni tramo limitante: no se sabe si la hay) y, con la misma geometría y el pasillo agotado de verdad, sale la otra."""
        job, route, corridor = self.exhausted_budget(3_000)
        self.assertEqual(route.cause, NoRouteCause.BUDGET)
        found = road_route.no_route(job, corridor.net_origin, corridor.net_dest, route)
        self.assertEqual(found.cause, NoRouteCause.BUDGET)
        self.assertEqual((found.budget, found.expanded, found.seen, found.margin_m), (3_000, 3_000, route.seen, 60.0))
        self.assertGreaterEqual(found.seen, found.expanded)
        for name in ("z_origin_m", "z_destination_m", "reached_from_origin_m", "reached_from_destination_m", "length_m",
                     "min_gradient_pct", "limit", "rising", "length_basis"):
            self.assertIsNone(getattr(found, name), name)
        error = found.error(job)
        self.assertEqual(error.code, "des.road_budget")
        self.assertEqual(error.field, "des.road.rdw_001.search_budget")
        self.assertEqual(error.notes, ())
        for expected in ("3000", "no significa que no haya ruta", "holgura", "presupuesto", "60", "no se crea nada"):
            self.assertIn(expected, error.text)
        self.assertNotIn("?", error.text)
        tight = rd.route_with(**{**dataclasses.asdict(base.HYPOTHESES), "margin_m": 0.0})
        job_t, _mesh, corridor_t = base.build(base.flat(15, 20), (7, 5), (7, 10), route=tight, start_level_m=101.0, end_level_m=99.0)
        route_t = base.solve(job_t, corridor_t)
        self.assertEqual(road_route.no_route(job_t, corridor_t.net_origin, corridor_t.net_dest, route_t).cause, NoRouteCause.CORRIDOR)


def strip_zone_closes_one_node(job: Any, mesh: Any) -> bool:
    """Que el intocable de la franja quita **un** nodo de la fila de la franja (el de 148 a 152 m), de modo que el único paso queda cerrado."""
    row, column = mesh.node_of(*absolute((150.0, 198.0)))
    strip = mesh.node_of(*job.geometry.origin)[0]
    return row == strip and bool(mesh.forbidden[row, column]) and int((~mesh.forbidden[strip, 25:51]).sum()) == 25


class CausesTest(unittest.TestCase):
    """Las cinco restricciones del tramo limitante (RF-017-12): cada una con un caso que la da y su lugar."""

    def flat_case(self, surface: np.ndarray, origin: tuple[int, int], destination: tuple[int, int], **options: Any) -> tuple[Any, Any, Any]:
        job, mesh, corridor = base.build(surface, origin, destination, **options)
        self.assertFalse(corridor.reachable)
        return job, mesh, corridor

    def test_cells_without_data_between_the_ends_are_the_limit(self) -> None:
        """RF-017-12: una columna de celdas sin dato entre el origen y el destino: la red 2D no los une y el tramo limitante es el último nodo
        con dato antes de ellas, con ``NO_DATA`` como causa y su lugar (el primer paso inadmisible hacia el destino es el del este)."""
        surface = base.flat(9, 13)
        surface[:, 6] = np.nan
        job, mesh, corridor = self.flat_case(surface, (4, 1), (4, 11))
        found = road_route.no_route(job, corridor.net_origin, corridor.net_dest)
        self.assertEqual(found.cause, NoRouteCause.NETWORK)
        self.assertEqual((found.limit.cause, found.limit.node, found.limit.heading), (LimitCause.NO_DATA, (4, 5), EAST))
        self.assertEqual((found.limit.x, found.limit.y), mesh.center_of(4, 5))
        error = found.error(job)
        self.assertEqual([code for code, _values in error.notes], ["des.road_limit_no_data"])
        self.assertIn("celdas sin dato", error.text)

    def test_a_cliff_higher_than_the_cut_and_fill_height_is_the_height_and_with_height_zero_the_slope(self) -> None:
        """RF-017-12: un escalón de 40 m entre dos mesetas (con pd = 10 % y 1 m de altura máxima de desmonte y terraplén no se puede seguir el
        terreno: 40 > 0,4 + 2 m) da ``HEIGHT``; con altura máxima 0 (la pista que sigue el terreno), el mismo escalón da ``SLOPE``; en los dos
        casos la pendiente mínima es el desnivel entre la distancia en línea recta (40 m sobre 36 m)."""
        surface = base.flat(9, 13)
        surface[:, 6:] = 140.0
        for height, expected in ((1.0, LimitCause.HEIGHT), (0.0, LimitCause.SLOPE)):
            route = rd.route_with(**{**dataclasses.asdict(base.HYPOTHESES), "max_cut_fill_m": height})
            job, mesh, corridor = self.flat_case(surface, (4, 1), (4, 10), route=route)
            found = road_route.no_route(job, corridor.net_origin, corridor.net_dest)
            with self.subTest(height=height):
                self.assertEqual((found.limit.cause, found.limit.node, found.limit.heading), (expected, (4, 5), EAST))
                self.assertAlmostEqual(found.length_m, 36.0, delta=1e-9)
                self.assertAlmostEqual(found.min_gradient_pct, 40.0 / 36.0 * 100.0, delta=1e-9)
                self.assertTrue(found.rising)
        job, net_origin, net_dest = self.cliff(1.0)
        error = road_route.no_route(job, net_origin, net_dest).error(job)
        self.assertIn("altura máxima de desmonte y terraplén", error.text)

    def cliff(self, height: float) -> tuple[Any, Any, Any]:
        surface = base.flat(9, 13)
        surface[:, 6:] = 140.0
        route = rd.route_with(**{**dataclasses.asdict(base.HYPOTHESES), "max_cut_fill_m": height})
        job, _mesh, corridor = self.flat_case(surface, (4, 1), (4, 10), route=route)
        return job, corridor.net_origin, corridor.net_dest

    def test_a_falling_route_reports_the_lowest_level_from_the_origin_and_the_highest_from_the_destination(self) -> None:
        """RF-017-12 («la mayor (o la menor) cota»): si el destino está **más bajo** que el origen, desde el origen se dice la cota menor a que
        se llega y desde el destino la mayor; sin desnivel, 0 %."""
        surface = base.flat(9, 13)
        surface[:, 6:] = 60.0
        job, _mesh, corridor = self.flat_case(surface, (4, 1), (4, 10))
        found = road_route.no_route(job, corridor.net_origin, corridor.net_dest)
        self.assertFalse(found.rising)
        self.assertLess(found.reached_from_origin_m, found.z_origin_m)
        self.assertGreater(found.reached_from_destination_m, found.z_destination_m)
        self.assertEqual(found.limit.cause, LimitCause.HEIGHT)
        holed = base.flat(9, 13)
        holed[:, 6] = np.nan
        job_f, _mesh_f, corridor_f = self.flat_case(holed, (4, 1), (4, 11))
        self.assertEqual(road_route.no_route(job_f, corridor_f.net_origin, corridor_f.net_dest).min_gradient_pct, 0.0)

    def grid_of_cells(self, rows: int, cols: int) -> Any:
        return gis.Grid(west=500_000.0, north=4_400_000.0, dx=1.0, dy=1.0, ncols=cols, nrows=rows)

    def test_a_destination_in_a_block_that_leaves_the_grid_is_the_edge_of_the_grid(self) -> None:
        """RF-017-12, P-6: una rejilla de 14 × 12 celdas de 1 m con la malla de 4 m deja el último bloque de la fila (celdas 12 a 15) a medio
        salir de ella: ese nodo no se pisa, así que el destino no tiene red y la causa es **el borde de la rejilla**, en el propio destino; con
        las celdas de su bloque sin dato dentro de la rejilla, ``NO_DATA``; con el destino en un intocable, ``MASK``; el origen, igual."""
        grid = self.grid_of_cells(12, 14)
        surface = np.full(grid.shape, 100.0)
        origin = (grid.west + 2.0, grid.north - 6.0)  # el nodo (1, 0)
        cases = (
            ("borde", (grid.west + 13.0, grid.north - 6.0), None, None, LimitCause.GRID_EDGE),
            ("sin dato", (grid.west + 10.0, grid.north - 6.0), (slice(4, 8), slice(8, 12)), "nan", LimitCause.NO_DATA),
            ("intocable", (grid.west + 10.0, grid.north - 6.0), (slice(4, 8), slice(8, 12)), "mask", LimitCause.MASK),
        )
        for name, destination, where, how, expected in cases:
            terrain, untouchable = surface.copy(), np.zeros(grid.shape, dtype=bool)
            if how == "nan":
                terrain[where] = np.nan
            elif how == "mask":
                untouchable[where] = True
            job = rd.route_job(grid, terrain, origin, destination, route=base.HYPOTHESES, untouchable=untouchable, end_level_m=100.0)
            mesh, corridor = rd.route_corridor(job)
            with self.subTest(case=name):
                self.assertFalse(corridor.reachable)
                found = road_route.no_route(job, corridor.net_origin, corridor.net_dest)
                self.assertEqual(found.cause, NoRouteCause.NETWORK)
                node = mesh.node_of(*destination)
                self.assertEqual((found.limit.cause, found.limit.node, found.limit.heading), (expected, node, None))
                self.assertEqual((found.limit.x, found.limit.y), mesh.center_of(*node))
                self.assertEqual(found.reached_from_destination_m, 100.0)  # nada alcanza el destino: su cota
        job = rd.route_job(grid, surface, (grid.west + 13.0, grid.north - 6.0), (grid.west + 2.0, grid.north - 6.0), route=base.HYPOTHESES)
        mesh, corridor = rd.route_corridor(job)
        found = road_route.no_route(job, corridor.net_origin, corridor.net_dest)
        self.assertEqual((found.limit.cause, found.limit.node), (LimitCause.GRID_EDGE, mesh.node_of(*job.geometry.origin)))
        self.assertIsNone(found.z_origin_m)  # sin dato: ni cota de inicio ni terreno

    def test_the_causes_are_read_from_the_first_blocked_step_in_the_direction_of_the_other_end(self) -> None:
        """RF-017-12 (plan A3: «leída del primer paso inadmisible»): de un nodo, los 16 pasos se recorren del más cercano a la dirección del
        otro extremo al más lejano y la causa es la del primero que no se puede dar: los dos nodos que cruza un paso «de caballo» cuentan; el
        borde de la malla, el bloque que sale de la rejilla, las celdas sin dato y las zonas prohibidas se distinguen en ese orden."""
        grid = self.grid_of_cells(12, 14)
        surface = np.full(grid.shape, 100.0)
        surface[0:4, 8:12] = np.nan
        wall = np.zeros(grid.shape, dtype=bool)
        wall[8:12, 4:8] = True
        job = rd.route_job(grid, surface, (grid.west + 2.0, grid.north - 6.0), (grid.west + 10.0, grid.north - 6.0), route=base.HYPOTHESES,
                           untouchable=wall)
        mesh, _corridor = rd.route_corridor(job)
        reason = road_route.step_reason
        pd, height = 0.10, 1.0
        self.assertEqual(reason(mesh, 1, 0, 0, pd, height), None)  # hacia el norte (0, 1): el nodo (0, 0) se pisa
        self.assertEqual(reason(mesh, 0, 0, 0, pd, height), LimitCause.GRID_EDGE)  # fuera de la malla
        self.assertEqual(reason(mesh, 0, 1, 4, pd, height), LimitCause.NO_DATA)  # el este: celdas sin dato (0, 2)
        self.assertEqual(reason(mesh, 2, 0, 8, pd, height), LimitCause.GRID_EDGE)  # el sur de la última fila: fuera de la malla
        self.assertEqual(reason(mesh, 1, 0, 8, pd, height), None)  # el sur (0, -1): el nodo (2, 0) se pisa
        self.assertEqual(reason(mesh, 1, 1, 8, pd, height), LimitCause.MASK)  # el sur del nodo (1, 1): el intocable
        self.assertEqual(reason(mesh, 1, 2, 4, pd, height), LimitCause.GRID_EDGE)  # el este: el bloque a medio salir de la rejilla
        self.assertEqual(reason(mesh, 1, 0, 5, pd, height), LimitCause.MASK)  # un paso de caballo (2, -1): su nodo intermedio es del intocable
        self.assertEqual(reason(mesh, 0, 0, 5, pd, height), None)  # el mismo paso desde otro nodo
        self.assertEqual(road_route.node_reason(mesh, 2, 3), LimitCause.GRID_EDGE)
        self.assertEqual(road_route.node_reason(mesh, 0, 2), LimitCause.NO_DATA)
        self.assertEqual(road_route.node_reason(mesh, 2, 1), LimitCause.MASK)
        self.assertIsNone(road_route.node_reason(mesh, 0, 0))


class GuardsTest(unittest.TestCase):
    def test_a_route_that_exists_has_nothing_to_explain_and_the_inputs_are_checked(self) -> None:
        """RF-017-12: ``no_route`` con una ruta que sí existe es un error del programa (``ValueError``); las entradas que no son de su tipo o no
        son de la misma malla, ``TypeError`` o ``ValueError`` al llamar, no al avanzar; y las de otro trabajo (otra pendiente) no valen."""
        job, _mesh, corridor = base.build(base.flat(9, 13), (4, 2), (4, 10))
        route = base.solve(job, corridor)
        self.assertTrue(route.ok)
        with self.assertRaises(ValueError):
            road_route.no_route(job, corridor.net_origin, corridor.net_dest, route)
        with self.assertRaises(TypeError):
            road_route.no_route("trabajo", corridor.net_origin, corridor.net_dest)
        with self.assertRaises(TypeError):
            road_route.no_route(job, corridor, corridor.net_dest)
        with self.assertRaises(TypeError):
            road_route.no_route(job, corridor.net_origin, corridor.net_dest, "ruta")
        other, _mesh_o, corridor_o = base.build(base.flat(9, 13), (4, 2), (4, 10), pd_pct=5.0)
        with self.assertRaises(ValueError):
            road_route.no_route(job, corridor_o.net_origin, corridor_o.net_dest)
        with self.assertRaises(ValueError):
            road_route.no_route(other, corridor.net_origin, corridor.net_dest)

    def test_nothing_is_written_or_relaxed_and_the_same_inputs_give_the_same_diagnosis(self) -> None:
        """RF-017-12 (B2), RF-015-02: ``no_route`` no cambia la malla, las redes ni el trabajo (solo los lee), no relaja ningún límite (la
        pendiente y la altura son las del trabajo) y con las mismas entradas da el mismo diagnóstico, igual por igual."""
        job, mesh, corridor = strip_case(closed=True)
        kept = (mesh.z.copy(), mesh.forbidden.copy(), corridor.net_origin.dist.copy(), corridor.net_dest.dist.copy(), job.start.copy(),
                job.untouchable.copy(), job.profile.max_gradient_pct, job.route.max_cut_fill_m)
        first = road_route.no_route(job, corridor.net_origin, corridor.net_dest)
        second = road_route.no_route(job, corridor.net_origin, corridor.net_dest)
        self.assertEqual(first, second)
        after = (mesh.z, mesh.forbidden, corridor.net_origin.dist, corridor.net_dest.dist, job.start, job.untouchable)
        for array, before in zip(after, kept[:6], strict=True):
            self.assertTrue(np.array_equal(array, before, equal_nan=True))
        self.assertEqual((job.profile.max_gradient_pct, job.route.max_cut_fill_m), kept[6:])
        self.assertTrue(dataclasses.is_dataclass(first) and getattr(first, "__dataclass_params__").frozen)


class LevelDestinationTest(unittest.TestCase):
    """El destino por cota (la rampa, D-4; RF-017-02, RF-017-10): la ruta termina en el primer nodo de la zona cuya cota de partida difiere de
    la pedida en menos de la tolerancia, y se da el destino alcanzado (lugar y cota); una cota fuera del terreno de su zona se rechaza."""

    ROWS, COLS = 11, 14
    COLUMNS = (8, 9, 10)
    """Las columnas de la zona de la rampa (nodos de 4 m; las filas 3 a 7) en un talud del 4 % hacia el este: 101,36, 101,52 y 101,68 m."""

    def setUp(self) -> None:
        self.terrain = 100.0 + 0.04 * (np.indices((self.ROWS, self.COLS))[1] + 0.5) * base.CELL_M
        self.grid = gis.Grid(west=500_000.0, north=4_400_000.0, dx=base.CELL_M, dy=base.CELL_M, ncols=self.COLS, nrows=self.ROWS)

    def job(self, level: float, tolerance: float, *, route: Any = None, zone_name: str | None = "gis_fea_pistas_zonas", **options: Any) -> Any:
        side, grid = base.CELL_M, self.grid
        west, east = grid.west + self.COLUMNS[0] * side, grid.west + (self.COLUMNS[-1] + 1) * side
        north, south = grid.north - 3 * side, grid.north - 8 * side
        ring = np.array([[west, south], [east, south], [east, north], [west, north]])
        destination = road_model.LevelDestination(level, tolerance, ((ring,),))
        origin = (grid.west + 1.5 * side, grid.north - 5.5 * side)  # el nodo (5, 1)
        job = rd.route_job(grid, self.terrain, origin, destination, route=base.HYPOTHESES if route is None else route, **options)
        if zone_name is not None:
            job = dataclasses.replace(job, request=dataclasses.replace(job.request, dest_zone=zone_name))
        return job

    def mesh_of(self, job: Any) -> Any:
        road_net = import_geoblender("design.road_net")
        return road_net.route_mesh(job.grid, job.start, job.route.mesh_m, job.untouchable, avoid_weight=job.avoid_weight)

    def test_the_destination_is_the_nodes_of_the_zone_within_the_tolerance_of_the_level(self) -> None:
        """RF-017-10, RF-017-02, D-4: el destino por cota son **los nodos de la zona** (el centro del nodo dentro del polígono) **cuya cota de
        partida** (la media de su bloque) **difiere de la pedida en menos de la tolerancia de llegada**, y que se pisan: con 101,5 m y 0,1 m, solo
        la columna 9 (101,52 m: 0,02 m); con 0,2 m, las columnas 8, 9 y 10 (0,14, 0,02 y 0,18 m); fuera de la zona, ninguno, aunque su cota
        esté dentro de la tolerancia; un nodo que las máscaras prohíben, tampoco."""
        for tolerance, columns in ((0.1, (9,)), (0.2, (8, 9, 10)), (0.01, ())):
            job = self.job(101.5, tolerance)
            mesh = self.mesh_of(job)
            with self.subTest(tolerance=tolerance):
                if not columns:
                    with self.assertRaises(messages.DesignError):
                        road_route.route_target(job, mesh)
                    continue
                target = road_route.route_target(job, mesh)
                self.assertEqual((target.dtype, target.shape), (np.dtype(bool), mesh.shape))
                expected = np.zeros(mesh.shape, dtype=bool)
                expected[3:8, list(columns)] = True
                self.assertTrue(np.array_equal(target, expected))
        wall = np.zeros(self.grid.shape, dtype=bool)
        wall[5, 9] = True
        job = self.job(101.5, 0.1, untouchable=wall)
        target = road_route.route_target(job, self.mesh_of(job))
        self.assertEqual(int(target.sum()), 4)
        self.assertFalse(bool(target[5, 9]))

    def test_a_point_destination_is_its_node(self) -> None:
        """RF-017-10: el destino de un punto es el nodo que lo contiene (``mesh.node_of``), como hasta ahora."""
        job, mesh, _corridor = base.build(base.flat(9, 13), (4, 2), (4, 10))
        self.assertEqual(road_route.route_target(job, mesh), (4, 10))

    def test_the_route_ends_in_the_first_node_of_the_zone_and_the_arrival_says_where_and_at_what_level(self) -> None:
        """RF-017-10, RF-017-02, D-4: con la zona y la tolerancia, la ruta termina en el primer nodo del conjunto que alcanza (el de la fila del
        origen, el más barato) y se da **el destino alcanzado**: el nodo, su lugar (el centro, absoluto) y **la cota** a que llega (el nivel
        más próximo a la pedida: a menos de medio paso de cota) con su diferencia con la pedida y si cabe en la tolerancia de llegada de la
        ruta (``arrival_tol_m``: la de la **cota de llegada**; la tolerancia de la rampa, ``dest_tol_m``, elige los nodos de destino)."""
        level = 101.5
        job = self.job(level, 0.1)
        mesh, corridor = rd.route_corridor(job)  # el destino por defecto es el del conjunto: ``route_target``
        route = base.solve(job, corridor)
        self.assertTrue(route.ok)
        base.verify(self, job, mesh, route)
        arrival = road_route.arrival_of(job, route)
        self.assertEqual(arrival.node, (5, 9))
        self.assertEqual(route.nodes[-1], arrival.node)
        target = road_route.route_target(job, mesh)
        self.assertTrue(all(not target[node] for node in route.nodes[:-1]))  # ningún nodo del conjunto antes del último
        self.assertEqual((arrival.x, arrival.y), mesh.center_of(5, 9))
        self.assertAlmostEqual(arrival.terrain_m, float(self.terrain[5, 9]), delta=1e-9)
        self.assertAlmostEqual(arrival.level_m, float(route.levels_m[-1]), delta=1e-12)
        self.assertEqual(arrival.requested_m, level)
        self.assertAlmostEqual(arrival.difference_m, arrival.level_m - level, delta=1e-9)
        self.assertLessEqual(abs(arrival.difference_m), job.route.level_step_m / 2 + 1e-9)
        self.assertTrue(arrival.within_tolerance)  # 0,02 m ≤ 0,25 m
        strict = rd.route_with(**{**dataclasses.asdict(base.HYPOTHESES), "arrival_tol_m": 0.01})
        job_s = self.job(level, 0.1, route=strict)
        mesh_s, corridor_s = rd.route_corridor(job_s)
        arrival_s = road_route.arrival_of(job_s, base.solve(job_s, corridor_s))
        self.assertEqual(arrival_s.node, arrival.node)
        self.assertFalse(arrival_s.within_tolerance)  # 0,02 m > 0,01 m: se dice, no se corrige
        for level_w, expected in ((101.36, (5, 8)), (101.5, (5, 9))):
            wide = self.job(level_w, 0.2)
            mesh_w, corridor_w = rd.route_corridor(wide)
            arrival_w = road_route.arrival_of(wide, base.solve(wide, corridor_w))
            with self.subTest(level=level_w):
                # 101,36 m: las columnas 8 (0 m) y 9 (0,16 m) son destino y gana la primera que alcanza, la más barata. 101,5 m: la 8 también
                # (0,14 m), pero su nivel de llegada (+0,25 m sobre su terreno) pide subir 0,41 m en un paso que admite 0,4 m: no se alcanza y la
                # ruta acaba en la 9, que sí.
                self.assertEqual(arrival_w.node, expected)
                self.assertTrue(road_route.route_target(wide, mesh_w)[5, 8])

    def test_the_arrival_of_a_point_destination_is_its_node_and_the_end_level(self) -> None:
        """RF-017-10, RF-017-02: la llegada de un destino de punto es su nodo y la cota de fin (la pedida o ninguna: sin ella, el terreno);
        ``arrival_of`` con una ruta que no existe es un error del programa."""
        job, mesh, corridor = base.build(base.flat(9, 13), (4, 2), (4, 10), end_level_m=100.5)
        route = base.solve(job, corridor)
        arrival = road_route.arrival_of(job, route)
        self.assertEqual((arrival.node, arrival.requested_m), ((4, 10), 100.5))
        self.assertAlmostEqual(arrival.level_m, 100.5, delta=1e-12)
        self.assertEqual((arrival.x, arrival.y), mesh.center_of(4, 10))
        job_n, _mesh_n, corridor_n = base.build(base.flat(9, 13), (4, 2), (4, 10))
        arrival_n = road_route.arrival_of(job_n, base.solve(job_n, corridor_n))
        self.assertEqual((arrival_n.requested_m, arrival_n.difference_m, arrival_n.within_tolerance), (None, None, None))
        failed = base.solve(*strip_case()[::2])
        with self.assertRaises(ValueError):
            road_route.arrival_of(job, failed)

    def test_a_level_outside_the_terrain_of_its_zone_is_rejected_with_the_range_of_the_zone(self) -> None:
        """RF-017-04 (RF-017-02): una cota que no está en el terreno de su zona (con la tolerancia de llegada) se rechaza con
        ``des.road_dest_level_out_of_zone``: la capa, la pista, el campo (``dest_level_m``) y el valor, la zona y las cotas del terreno dentro
        de ella (101,36 a 101,68 m); no se elige ninguna cota por la persona; sin zona de la que leer el nombre, sale «?» y no un marcador;
        una zona sin ningún nodo que se pise es un error del programa (la preparación la rechaza antes: el catálogo no tiene un código)."""
        job = self.job(120.0, 0.2)
        with self.assertRaises(messages.DesignError) as caught:
            road_route.route_target(job, self.mesh_of(job))
        error = caught.exception
        self.assertEqual(error.code, "des.road_dest_level_out_of_zone")
        self.assertEqual(error.field, "des.road.rdw_001.dest_level_m")
        self.assertEqual(error.value, 120.0)
        self.assertEqual((error.values["low"], error.values["high"]), (101.36, 101.68))
        self.assertEqual((error.values["layer"], error.values["entity"], error.values["zone"]),
                         ("gis_fea_pistas_puntos", "Pista de prueba", "gis_fea_pistas_zonas"))
        for expected in ("«gis_fea_pistas_zonas»", "120", "101,36", "101,68", "elija una cota", "no se crea nada"):
            self.assertIn(expected, error.text)
        self.assertNotIn("?", error.text)
        unnamed = self.job(120.0, 0.2, zone_name=None)
        with self.assertRaises(messages.DesignError) as other:
            road_route.route_target(unnamed, self.mesh_of(unnamed))
        self.assertIn("?", other.exception.text)
        everything = np.zeros(self.grid.shape, dtype=bool)
        everything[:, 8:11] = True
        closed = self.job(101.5, 0.2, untouchable=everything)
        with self.assertRaises(ValueError):
            road_route.route_target(closed, self.mesh_of(closed))

    def test_without_a_route_the_level_destination_is_explained_with_its_own_level(self) -> None:
        """RF-017-12, RF-017-02: con un destino por cota y sin ruta (la zona detrás de un intocable que cierra el paso), el diagnóstico usa la
        cota pedida como cota del destino y el nodo de la zona más próximo al origen como el otro extremo; la causa es la máscara."""
        wall = np.zeros(self.grid.shape, dtype=bool)
        wall[:, 6] = True
        job = self.job(101.5, 0.1, untouchable=wall)
        mesh, corridor = rd.route_corridor(job)
        self.assertFalse(corridor.reachable)
        found = road_route.no_route(job, corridor.net_origin, corridor.net_dest)
        self.assertEqual(found.cause, NoRouteCause.NETWORK)
        self.assertEqual(found.z_destination_m, 101.5)
        self.assertEqual(found.length_basis, "straight")
        self.assertAlmostEqual(found.length_m, 8.0 * base.CELL_M, delta=1e-9)  # del nodo (5, 1) al (5, 9)
        self.assertEqual((found.limit.cause, found.limit.node, found.limit.heading), (LimitCause.MASK, (5, 5), EAST))
        self.assertEqual((found.limit.x, found.limit.y), mesh.center_of(5, 5))


class StepsTest(unittest.TestCase):
    def test_the_pass_over_the_seen_levels_keeps_each_call_within_the_budget(self) -> None:
        """RNF-017-06 (T07 aviso 9): agotar el pasillo guarda las cotas mayor y menor de los estados vistos **en unidades aparte** (una por
        diccionario de etiquetas): la llamada más larga del paso sigue dentro de 0,2 s con los estados vistos de la franja; y cerrar el
        generador a mitad no deja nada ni cambia el resultado de la siguiente corrida."""
        from tests.support.timing import drive_steps, least_of

        job, _mesh, corridor = strip_case()

        def longest() -> float:
            return drive_steps(road_route.route_steps(job, corridor, budget_s=0.004)).longest_s

        run = drive_steps(road_route.route_steps(job, corridor, budget_s=0.004))
        self.assertEqual(run.result.cause, NoRouteCause.CORRIDOR)
        self.assertIsNotNone(run.result.high_m)
        self.assertLessEqual(least_of(longest, 0.2, attempts=3), 0.2)
        # Una unidad por diccionario de etiquetas en la pasada de las cotas (16) y otra por cada uno al liberarlos (16): con un presupuesto de paso
        # ínfimo, cada unidad es un paso; sin partirla (la pasada de millones de estados de una vez, 100 a 300 ms) quedarían 16 menos.
        steps_of_a_tiny_budget = sum(1 for _ in road_route.route_steps(job, corridor, budget_s=1e-9))
        self.assertGreaterEqual(steps_of_a_tiny_budget, 2 * 16 + 3)
        steps = road_route.route_steps(job, corridor, budget_s=0.004)
        next(steps)
        steps.close()  # type: ignore[attr-defined]
        again = base.solve(job, corridor)
        self.assertEqual(again.seen, run.result.seen)
        self.assertTrue(np.array_equal(again.high_m, run.result.high_m, equal_nan=True))
        self.assertTrue(math.isfinite(float(np.nanmax(again.high_m))))


if __name__ == "__main__":
    unittest.main()
