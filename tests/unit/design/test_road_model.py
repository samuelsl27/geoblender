# SPDX-License-Identifier: GPL-3.0-or-later
"""Los datos de la pista y de la accesibilidad (spec 017, T05; HU-017-1 a 3; RF-017-01, 02, 04, 10, 24; plan 017 §5.1,
§5.2.1, §5.2.2 y §5.3.1): ``RoadMode``, ``RouteParams``, ``RoadRequest`` (con ``LayerFields``), ``RoadJob``
(``RoadGeometry`` y ``LevelDestination``), ``RoadOutcome``, ``AccessRequest``, ``AccessJob`` (``EntryPoint``, ``BermGrid`` y
``AccessCells``), ``AccessOutcome`` (``BermReach``, ``PlatformReach`` y ``ZoneReach``) y los códigos de «sin ruta»
(``NoRouteCause``) y de su tramo limitante (``LimitCause``).

Todo inmutable (``frozen``), sin ninguna cifra minera por defecto (lo que no se pide es ``None``: el valor por defecto del
parámetro o, sin él, el rechazo de RF-015-08), con los errores del programa como ``TypeError`` o ``ValueError`` (los
rechazos de la persona, con su capa, su pista, su campo y su valor, son de la preparación, T19 y T23) y **sin nada del
proyecto** en los dos trabajos, para calcular sin proyecto y reproducir. El módulo es **perezoso**: ni ``design.model`` ni
habilitar Geoblender lo cargan, y él no carga ``design.road_profiles`` hasta que se usa (RNF-001-03).
"""

from __future__ import annotations

import ast
import dataclasses
import os
import pathlib
import sqlite3
import unittest
from typing import Any

import numpy as np

from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.support.repo import EXTENSION_DIR
from tests.unit.architecture import test_lazy_registration

road_model = import_geoblender("design.road_model")
road_profiles = import_geoblender("design.road_profiles")
params = import_geoblender("design.params")
provenance = import_geoblender("design.provenance")
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")
figures = import_geoblender("core.provenance.figures")
preview = import_geoblender("design.preview")
gis = import_geoblender("gis")

GRID = gis.Grid(west=500_000.0, north=4_400_000.0, dx=2.0, dy=2.0, ncols=8, nrows=6)
"""Una rejilla de 6 × 8 celdas de 2 m (absolutas, en el norte de un UTM): lo justo para comprobar formas y tipos."""
SHAPE = GRID.shape
ORIGIN = (500_002.0, 4_399_996.0)
DESTINATION = (500_012.0, 4_399_990.0)
LINE = ((500_002.0, 4_399_996.0), (500_008.0, 4_399_992.0), (500_012.0, 4_399_990.0))
LINE_3D = ((500_002.0, 4_399_996.0, 101.0), (500_008.0, 4_399_992.0, 103.0), (500_012.0, 4_399_990.0, 105.0))
RING = ((500_008.0, 4_399_990.0), (500_014.0, 4_399_990.0), (500_014.0, 4_399_994.0), (500_008.0, 4_399_994.0))
ZONE = ((RING,),)
"""La zona de una rampa: un polígono de una parte con un anillo (por parte, sus anillos; por anillo, sus puntos)."""
ROUTE_NAMES = ("mesh_m", "level_step_m", "max_cut_fill_m", "lambda_per_m", "turn_m", "margin_m", "simplify_m",
               "arrival_tol_m", "search_budget")
"""Los nueve parámetros de la ruta (``RoadParam``: la malla, el paso de cota, la altura máxima de desmonte y terraplén,
λ, el giro, la holgura del pasillo, la simplificación, la llegada y el presupuesto de estados)."""
NOT_REQUESTED = ("supports", "discarded", "reason")
"""Los valores de una pista que no pide el diálogo de crearla: lo declarado después, lo que decide la persona al
descartarla y su motivo (la pista no declara restricción alguna: D-15)."""


def surface() -> np.ndarray:
    return np.linspace(100.0, 110.0, SHAPE[0] * SHAPE[1]).reshape(SHAPE)


def flags(value: bool = True) -> np.ndarray:
    return np.full(SHAPE, value, dtype=bool)


def profile_of(code: str = "pista_principal") -> Any:
    """El perfil de referencia de IMGA como ``RoadProfile`` (``road_data.PROFILE``: solo de las pruebas)."""
    values = {param.value: getattr(rd.PROFILE, "class_name" if param is params.RoadProfileParam.CLASS else param.value)
              for param in params.RoadProfileParam}
    return road_profiles.RoadProfile.from_values(code, rd.PROFILE.name, values)


def route(**changes: object) -> Any:
    return road_model.RouteParams(**{**dataclasses.asdict(rd.ROUTE), **changes})


def layer_fields(**changes: object) -> Any:
    return road_model.LayerFields(**{"layer": "gis_fea_pistas_puntos", "name_field": "nombre", **changes})


def road(**changes: object) -> Any:
    values: dict[str, Any] = {"name": "Acceso al tajo", "fields": layer_fields(), "mode": "trace",
                              "profile": "pista_principal", "start": "gis_dtm_tajo"}
    values.update(changes)
    return road_model.RoadRequest(**values)


def geometry(**changes: object) -> Any:
    values: dict[str, Any] = {"origin": ORIGIN, "destination": DESTINATION}
    values.update(changes)
    return road_model.RoadGeometry(**values)


def job(**changes: object) -> Any:
    """Un trabajo de pista en el modo «trazar» (el de ``road()``), con lo leído en la rejilla de 6 × 8."""
    values: dict[str, Any] = {
        "request": road(), "code": "RDW-001", "profile": profile_of(), "grid": GRID, "start": surface(),
        "cut_allowed": flags(), "fill_allowed": flags(), "untouchable": flags(False), "geometry": geometry(),
        "route": route(), "start_level_m": 101.0, "end_level_m": 105.0}
    values.update(changes)
    return road_model.RoadJob(**values)


def access(**changes: object) -> Any:
    values: dict[str, Any] = {"name": "Accesos del tajo", "entries": layer_fields(layer="gis_fea_pistas_entradas"),
                              "surface": "gis_dtm_tajo"}
    values.update(changes)
    return road_model.AccessRequest(**values)


def access_job(**changes: object) -> Any:
    values: dict[str, Any] = {
        "request": access(), "code": "ACC-001", "grid": GRID, "surface": surface(),
        "entries": (road_model.EntryPoint("Entrada", 500_002.0, 4_399_996.0),), "untouchable": flags(False),
        "walk_slope_pct": 16.0, "walk_width_m": 4.0, "min_berm_area_m2": 300.0}
    values.update(changes)
    return road_model.AccessJob(**values)


class EnumsTest(unittest.TestCase):
    def test_the_three_modes_are_the_ones_of_the_parameter(self) -> None:
        """RF-017-02: la pista tiene tres modos —«trazar», «sobre un eje» y «eje 3D»—, con el texto estable del parámetro
        ``mode`` (el que se registra: ``provenance.ROAD_MODES``, de ``params``); otro es un error del programa."""
        self.assertEqual([item.value for item in road_model.RoadMode], list(provenance.ROAD_MODES))
        self.assertEqual([item.value for item in road_model.RoadMode], ["trace", "on_axis", "axis_3d"])
        for wrong in ("axis3d", "TRACE", "", "ruta"):
            with self.subTest(mode=wrong), self.assertRaises(ValueError):
                road_model.RoadMode(wrong)

    def test_the_causes_of_no_route_are_codes_of_the_catalog(self) -> None:
        """RF-017-12: las tres causas de «sin ruta» (la red 2D no llega al origen, el pasillo no contiene ninguna ruta 3D y
        la búsqueda agota su presupuesto) y las cinco restricciones del tramo limitante (la pendiente, una zona que las
        máscaras prohíben, la altura máxima de desmonte y terraplén, el borde de la rejilla y las celdas sin dato) son
        códigos de ``design.messages``: ninguno huérfano ni en un texto escrito a mano."""
        self.assertEqual([item.value for item in road_model.NoRouteCause],
                         ["des.road_no_route_network", "des.road_no_route_corridor", "des.road_budget"])
        self.assertEqual([item.value for item in road_model.LimitCause],
                         ["des.road_limit_slope", "des.road_limit_mask", "des.road_limit_height",
                          "des.road_limit_grid_edge", "des.road_limit_no_data"])
        for item in (*road_model.NoRouteCause, *road_model.LimitCause):
            with self.subTest(code=item.value):
                self.assertIn(item.value, messages.MESSAGES)
        for wrong in ("network", "des.road_no_route", ""):
            with self.subTest(cause=wrong), self.assertRaises(ValueError):
                road_model.NoRouteCause(wrong)


class LayerFieldsTest(unittest.TestCase):
    def test_the_layer_and_the_field_with_the_name_of_its_features(self) -> None:
        """RF-017-02 (plan 017 §5.2.1): la capa de la pista (o la de entradas) y el campo con el nombre de sus geometrías,
        que se elige en el diálogo; sin él se usa el ``fid``; solo la capa es obligatoria."""
        found = layer_fields(layer=" gis_fea_pistas_puntos ", name_field=" nombre ")
        self.assertEqual((found.layer, found.name_field), ("gis_fea_pistas_puntos", "nombre"))
        bare = road_model.LayerFields(layer="gis_fea_pistas_ejes")
        self.assertEqual((bare.layer, bare.name_field), ("gis_fea_pistas_ejes", None))
        self.assertEqual(road_model.LayerFields(layer="a", name_field="  "), road_model.LayerFields(layer="a"))
        for blank in ("", "  "):
            with self.subTest(layer=blank), self.assertRaises(ValueError):
                road_model.LayerFields(layer=blank)
        with self.assertRaises(TypeError):
            road_model.LayerFields(layer=7)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            road_model.LayerFields(layer="a", name_field=7)  # type: ignore[arg-type]


class RouteParamsTest(unittest.TestCase):
    def test_the_nine_parameters_of_the_route(self) -> None:
        """RF-017-10 (plan 017 §5.2.2): los parámetros de la ruta son nueve, con sus nombres de ``RoadParam``; son valores
        resueltos (todos presentes), inmutables y comparables por valor; ninguno es una cifra minera por defecto del
        producto: los de la referencia de IMGA son de las pruebas (``road_data.ROUTE``)."""
        self.assertEqual(tuple(item.name for item in dataclasses.fields(road_model.RouteParams)), ROUTE_NAMES)
        self.assertEqual({item.value for item in params.RoadParam} & set(ROUTE_NAMES), set(ROUTE_NAMES))
        found = route()
        self.assertEqual((found.mesh_m, found.level_step_m, found.max_cut_fill_m, found.lambda_per_m, found.search_budget),
                         (4.0, 0.28, 14.0, 2.0, 5_000_000))
        self.assertEqual(found, route())
        self.assertEqual(len({found, route()}), 1)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            found.mesh_m = 8.0  # type: ignore[misc]
        with self.assertRaises(TypeError):  # sin valor por defecto salvo el presupuesto: faltan los ocho
            road_model.RouteParams()  # type: ignore[call-arg]

    def test_the_default_budget_is_the_one_of_the_parameter(self) -> None:
        """RF-017-10, RF-017-12 (P-3): el presupuesto de estados de la ruta, sin pedirlo, es el valor por defecto de la
        familia ``des.road.{e}.search_budget`` (5.000.000, ADOPTADO «sin confirmar»): es la misma cifra, leída de
        ``params`` y no escrita aquí; llega al trabajo (:meth:`RouteParams.from_values` con lo que resuelve la
        preparación, que no lo da si nadie lo cambió) y una petición sin presupuesto lo deja en ``None``."""
        default = params.entity_params("road").template(params.RoadParam.SEARCH_BUDGET.value).default
        self.assertEqual(default, 5_000_000)
        self.assertEqual(road_model.DEFAULT_SEARCH_BUDGET, default)
        values = {name: value for name, value in dataclasses.asdict(rd.ROUTE).items() if name != "search_budget"}
        found = road_model.RouteParams.from_values({**values, "layer": "gis_fea_pistas_puntos", "mode": "trace"})
        self.assertEqual(found.search_budget, default)
        self.assertEqual(found, route(search_budget=default))
        self.assertEqual(road_model.RouteParams(4.0, 0.28, 14.0, 2.0, 4.0, 60.0, 4.0, 0.28).search_budget, default)
        self.assertEqual(job(route=found).route.search_budget, default)
        self.assertEqual(route(search_budget=200_000).search_budget, 200_000)
        self.assertIsNone(road().search_budget)

    def test_from_values_takes_the_resolved_values_and_names_what_is_missing(self) -> None:
        """RF-017-10: ``from_values`` lee los valores resueltos de la pista por su último segmento (los demás —la capa, el
        modo, el perfil…— no son suyos y se ignoran); si falta uno de los ocho sin valor por defecto, es un error del
        programa que lo nombra (la preparación rechazó antes, RF-015-08, sin elegir un valor por la persona)."""
        full = dataclasses.asdict(rd.ROUTE)
        self.assertEqual(road_model.RouteParams.from_values({**full, "mode": "trace", "profile": "x"}), route())
        for name in ROUTE_NAMES[:-1]:
            incomplete = {key: value for key, value in full.items() if key != name}
            with self.subTest(missing=name), self.assertRaises(ValueError) as caught:
                road_model.RouteParams.from_values(incomplete)
            self.assertIn(name, str(caught.exception))
            with self.subTest(none=name), self.assertRaises(ValueError):
                road_model.RouteParams.from_values({**full, name: None})

    def test_values_are_checked_against_their_ranges(self) -> None:
        """RF-017-10, RF-017-04: un valor que no es un número real (un texto o un booleano), que no es finito o que sale del
        rango de su familia (``params.ROAD_RANGES``: la malla y la llegada > 0, la altura, λ, el giro, la holgura y la
        simplificación ≥ 0, el presupuesto de 1 a 1.000 millones, entero) es un error del programa."""
        for name, wrong in (("mesh_m", "4"), ("mesh_m", True), ("lambda_per_m", None), ("search_budget", 1.5),
                            ("search_budget", True), ("search_budget", "5")):
            with self.subTest(name=name, wrong=wrong), self.assertRaises(TypeError):
                route(**{name: wrong})
        for name, wrong in (("mesh_m", 0.0), ("mesh_m", float("nan")), ("level_step_m", -0.1), ("max_cut_fill_m", -1.0),
                            ("lambda_per_m", -2.0), ("turn_m", float("inf")), ("margin_m", -60.0), ("simplify_m", -4.0),
                            ("arrival_tol_m", 0.0), ("search_budget", 0), ("search_budget", 1_000_000_001)):
            with self.subTest(name=name, wrong=wrong), self.assertRaises(ValueError) as caught:
                route(**{name: wrong})
            self.assertIn(name, str(caught.exception))
        self.assertEqual(route(max_cut_fill_m=0, lambda_per_m=0, turn_m=0, margin_m=0, simplify_m=0).margin_m, 0.0)

    def test_the_levels_of_a_node_are_at_most_two_thousand_on_each_side(self) -> None:
        """RF-017-10, RF-017-04, RNF-017-02, RNF-017-06, RNF-017-07 (B-5 de la verificación única, T41): el número de niveles a cada lado ``M = ⌊H/Δz⌋`` tiene un tope de 2.000 (``MAX_LEVELS``: 40 veces el de la
        referencia, 14/0,28 = 50; un límite de **validez** de la búsqueda, no una cifra minera): con H = 14 m, un paso de 0,0001 m (140.000 niveles) tardaba 108 s en una sola llamada y 424 MiB; ``level_count`` da ``M``
        como la búsqueda (14/0,28 es 50 aunque el cociente sea 49,999…), ``min_level_step_m`` el paso menor que lo cumple (redondeado hacia arriba al micrómetro) y ``RouteParams`` rechaza con el campo."""
        self.assertEqual(road_model.MAX_LEVELS, 2000)
        self.assertEqual(road_model.level_count(14.0, 0.28), 50)
        self.assertEqual((road_model.level_count(0.5, 0.28), road_model.level_count(0.5, 0.6), road_model.level_count(0.0, 0.2)), (1, 0, 0))
        self.assertEqual(road_model.level_count(14.0, 0.007), 2000)
        self.assertEqual(road_model.min_level_step_m(14.0), 0.007)
        self.assertEqual(road_model.min_level_step_m(1000.0), 0.5)
        self.assertEqual(road_model.level_count(14.0, road_model.min_level_step_m(14.0)), 2000)
        self.assertEqual(road_model.min_level_step_m(7.7777), 0.003889)  # hacia arriba: 3.888,85 µm son 3.889 (hacia abajo darían 2.000,4 niveles)
        for height in (7.7777, 333.3, 0.3, 123.456):
            self.assertLessEqual(road_model.level_count(height, road_model.min_level_step_m(height)), road_model.MAX_LEVELS, height)
        self.assertEqual(route(max_cut_fill_m=14.0, level_step_m=0.007).level_step_m, 0.007)  # el límite se cumple
        for wrong in (0.0001, 0.001, 0.00699):
            with self.subTest(step=wrong), self.assertRaises(ValueError) as caught:
                route(max_cut_fill_m=14.0, level_step_m=wrong)
            self.assertIn("level_step_m", str(caught.exception))
            self.assertIn("0.007", str(caught.exception))
        self.assertEqual(route().max_cut_fill_m, 14.0)  # la de la referencia: 50 niveles

    def test_a_big_search_budget_is_noticed_for_the_memory_it_can_take(self) -> None:
        """RF-017-10, RNF-017-07 (B-5 de la verificación única, T41): el presupuesto de estados admite hasta 10⁹ (``ROAD_RANGES``) y cada estado visto ocupa ≈ 140 bytes (medidos por la T07 y la T34: 965 MiB con
        5,98 M): un presupuesto de más del doble del que viene por defecto (5 M) da el aviso ``des.road_budget_memory`` con la memoria que puede ocupar (20 M estados, unos 2,6 GiB), y el de la referencia o menos, ninguno."""
        self.assertEqual(road_model.ROUTE_STATE_BYTES, 140)
        self.assertEqual(road_model.BUDGET_NOTICE_STATES, 2 * road_model.DEFAULT_SEARCH_BUDGET)
        for budget in (1, road_model.DEFAULT_SEARCH_BUDGET, road_model.BUDGET_NOTICE_STATES):
            self.assertIsNone(road_model.budget_memory_gib(budget), budget)
        self.assertAlmostEqual(road_model.budget_memory_gib(20_000_000), 20_000_000 * 140 / 1024**3, places=9)
        self.assertEqual(road_model.budget_memory_gib(1_000_000_000), 1_000_000_000 * 140 / 1024**3)
        self.assertGreater(road_model.budget_memory_gib(road_model.BUDGET_NOTICE_STATES + 1), 1.3)


class RoadRequestTest(unittest.TestCase):
    def test_a_request_asks_for_no_mining_figure(self) -> None:
        """Principio 2, RF-017-01, RF-017-02 (D-2, D-10, D-11): una petición no lleva ninguna cifra minera por defecto: del
        origen al presupuesto, todo lo que no es el nombre, la capa, el modo, el perfil y la partida es ``None`` (el
        valor por defecto del parámetro o, sin él, el rechazo de RF-015-08); es inmutable y comparable por valor."""
        request = road()
        for name in ("feature", "support", "origin", "destination", "dest_level_m", "dest_tol_m", "dest_zone",
                     "start_level_m", "end_level_m", *ROUTE_NAMES):
            with self.subTest(field=name):
                self.assertIsNone(getattr(request, name))
        self.assertEqual((request.name, request.mode, request.profile, request.start, request.layer),
                         ("Acceso al tajo", road_model.RoadMode.TRACE, "pista_principal", "gis_dtm_tajo",
                          "gis_fea_pistas_puntos"))
        self.assertEqual(request.fields, layer_fields())
        self.assertEqual(request, road())
        self.assertEqual(len({request, road()}), 1)
        self.assertNotEqual(request, road(profile="acceso_tajo"))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            request.name = "otra"  # type: ignore[misc]
        with self.assertRaises(TypeError):  # el nombre, los campos, el modo, el perfil y la partida se piden siempre
            road_model.RoadRequest(name="a", fields=layer_fields(), mode="trace", profile="p")  # type: ignore[call-arg]

    def test_the_request_has_the_values_of_the_road_that_the_dialog_asks_for(self) -> None:
        """RF-017-01, RF-017-02, RF-017-10 (plan 017 §5.2.2): la petición tiene un campo por cada valor de la pista
        (``RoadParam``: el nombre, el modo, la capa, la geometría, el perfil, la partida, el apoyo, el origen y el destino,
        la cota del destino con su tolerancia y su zona, las cotas de inicio y de fin y los nueve de la ruta) **salvo**
        lo declarado, el descarte y su motivo (``supports``, ``discarded`` y ``reason``: la pista no declara nada, D-15);
        y **no** tiene ``protect`` ni ``guard_m``."""
        wanted = {item.value for item in params.RoadParam} - set(NOT_REQUESTED)
        asked = {item.name for item in dataclasses.fields(road_model.RoadRequest) if item.name != "fields"} | {"layer"}
        self.assertEqual(asked, wanted)
        self.assertTrue({"protect", "guard_m"}.isdisjoint(asked))
        self.assertTrue(set(ROUTE_NAMES) <= asked)
        self.assertEqual({item.name for item in dataclasses.fields(road_model.RouteParams)}, set(ROUTE_NAMES))

    def test_values_are_normalized_and_checked(self) -> None:
        """RF-017-02: los textos sin los espacios de los extremos; el modo, de su texto; un número entero llega como
        ``float`` salvo el presupuesto, que es entero; un nombre en blanco, ``des.entity_name_missing``; un valor de otro
        tipo o un modo que no existe, un error del programa."""
        request = road(name="  Acceso ", profile=" p ", start=" gis_dtm_tajo ", mode="on_axis", feature=" Eje 1 ",
                       support=" gis_dtm_apoyo ", origin=" RDW-001@120 ", dest_zone=" gis_fea_pistas_zonas ",
                       start_level_m=101, end_level_m=105, mesh_m=4, level_step_m=0.28, max_cut_fill_m=14,
                       lambda_per_m=2, turn_m=4, margin_m=60, simplify_m=4, arrival_tol_m=1, search_budget=300)
        self.assertEqual((request.name, request.profile, request.start, request.feature, request.support, request.origin,
                          request.dest_zone), ("Acceso", "p", "gis_dtm_tajo", "Eje 1", "gis_dtm_apoyo", "RDW-001@120",
                                               "gis_fea_pistas_zonas"))
        self.assertIs(request.mode, road_model.RoadMode.ON_AXIS)
        self.assertEqual([(name, type(getattr(request, name))) for name in ("start_level_m", "mesh_m", "lambda_per_m")],
                         [("start_level_m", float), ("mesh_m", float), ("lambda_per_m", float)])
        self.assertEqual((request.search_budget, type(request.search_budget)), (300, int))
        self.assertEqual(road(feature="  ").feature, None)
        for blank in ("", "   "):
            with self.subTest(name=blank), self.assertRaises(messages.DesignError) as caught:
                road(name=blank)
            self.assertEqual((caught.exception.code, caught.exception.field), ("des.entity_name_missing", "name"))
        for changes in ({"name": 7}, {"fields": "puntos"}, {"profile": 7}, {"start": None}, {"feature": 7}, {"origin": 7},
                        {"dest_level_m": "140"}, {"dest_level_m": True}, {"mesh_m": "4"}, {"lambda_per_m": False},
                        {"search_budget": 1.5}, {"search_budget": "5"}, {"search_budget": True}):
            with self.subTest(changes=changes), self.assertRaises(TypeError):
                road(**changes)
        for wrong in ("axis3d", "", "ruta"):
            with self.subTest(mode=wrong), self.assertRaises(ValueError):
                road(mode=wrong)

    def test_the_destination_is_a_point_or_an_entity_or_a_level(self) -> None:
        """RF-017-02: el destino es un punto de la capa, una entidad **o** una cota con su zona y su tolerancia (la rampa,
        D-4): pedir un destino y una cota a la vez es un error del programa (el diálogo ofrece una u otra); la cota, la
        zona y la tolerancia sin destino son la rampa; el origen y el destino, un texto (la referencia que resuelve la
        preparación: un punto por ``fid`` o nombre, ``RDW-001@s`` o una entidad)."""
        ramp = road(dest_level_m=140.0, dest_tol_m=0.28, dest_zone="gis_fea_pistas_zonas")
        self.assertEqual((ramp.destination, ramp.dest_level_m, ramp.dest_tol_m), (None, 140.0, 0.28))
        point = road(origin="Entrada", destination="Plataforma 1")
        self.assertEqual((point.origin, point.destination, point.dest_level_m), ("Entrada", "Plataforma 1", None))
        for level in ({"dest_level_m": 140.0}, {"dest_tol_m": 0.28}, {"dest_zone": "gis_fea_pistas_zonas"}):
            with self.subTest(level=level), self.assertRaises(ValueError) as caught:
                road(destination="Plataforma 1", **level)
            self.assertIn("destino", str(caught.exception))
        for name in ("dest_level_m", "dest_tol_m", "dest_zone"):
            with self.subTest(name=name):
                self.assertIsNone(getattr(road(destination="Plataforma 1"), name))

    def test_a_request_is_not_exposed_by_the_model(self) -> None:
        """RNF-001-03 (RNF-017-10): la pista no está en ``design.model`` (como las seis peticiones de la 016, que sí): lo
        que habilitar carga no la crea; se pide a ``design.road_model``."""
        self.assertFalse(hasattr(model, "RoadRequest"))
        self.assertNotIn("RoadRequest", model.__all__)
        self.assertEqual(sorted(name for name in road_model.__all__ if name.endswith("Request")),
                         ["AccessRequest", "RoadRequest"])


class RoadJobTest(unittest.TestCase):
    def test_a_job_carries_everything_that_was_read_and_nothing_of_the_project(self) -> None:
        """RF-017-01, RF-017-02 (plan 017 §5.3.1): el trabajo de una pista lleva todo lo leído —la petición, el código de
        la entidad, el perfil, la rejilla, la superficie de partida, las máscaras como arrays, la geometría, la ruta y las
        cotas— y **nada del proyecto** (ni una ruta, ni una conexión, ni el proyecto): se calcula sin proyecto y se
        reproduce; es inmutable y sin ``__dict__``."""
        found = job()
        names = [item.name for item in dataclasses.fields(road_model.RoadJob)]
        self.assertEqual(names, ["request", "code", "profile", "grid", "start", "cut_allowed", "fill_allowed",
                                 "untouchable", "geometry", "route", "start_level_m", "end_level_m", "avoid_weight", "avoid_zone"])
        for forbidden in ("project", "path", "conn", "store", "version", "writer"):
            self.assertFalse(any(forbidden in name for name in names), forbidden)
        for item in dataclasses.fields(road_model.RoadJob):
            value = getattr(found, item.name)
            with self.subTest(field=item.name):
                self.assertNotIsInstance(value, (pathlib.PurePath, sqlite3.Connection, os.PathLike))
        self.assertFalse(hasattr(found, "__dict__"))
        self.assertEqual((found.request, found.code, found.mode), (road(), "RDW-001", road_model.RoadMode.TRACE))
        self.assertIs(found.grid, GRID)
        self.assertEqual((found.start_level_m, found.end_level_m, found.avoid_weight, found.avoid_zone), (101.0, 105.0, None, None))
        for name in ("request", "code", "start", "route"):
            with self.subTest(name=name), self.assertRaises(dataclasses.FrozenInstanceError):
                setattr(found, name, None)

    def test_the_arrays_of_a_job_are_read_only_views(self) -> None:
        """RF-015-02 (reproducir): lo leído que lleva el trabajo no se cambia por descuido: la superficie de partida y las
        máscaras son vistas **de solo lectura** (float64 y booleanos) y las del que las entregó siguen siendo suyas;
        con el mismo contenido, el mismo resultado."""
        start, cut = surface(), flags()
        found = job(start=start, cut_allowed=cut)
        for name in ("start", "cut_allowed", "fill_allowed", "untouchable"):
            array = getattr(found, name)
            with self.subTest(name=name):
                self.assertEqual(array.shape, SHAPE)
                self.assertFalse(array.flags.writeable)
                with self.assertRaises(ValueError):
                    array[0, 0] = array[0, 0]
        self.assertEqual((found.start.dtype, found.cut_allowed.dtype), (np.float64, np.bool_))
        self.assertTrue(start.flags.writeable and cut.flags.writeable)
        np.testing.assert_array_equal(found.start, start)
        self.assertEqual(job(start=start.astype(np.float32)).start.dtype, np.float64)

    def test_the_arrays_have_the_shape_of_the_grid(self) -> None:
        """RF-017-04: la superficie de partida y las máscaras son de la forma de la rejilla (filas × columnas): si no, es
        un error del programa."""
        for name in ("start", "cut_allowed", "fill_allowed", "untouchable"):
            with self.subTest(name=name), self.assertRaises(ValueError) as caught:
                job(**{name: np.zeros((SHAPE[0] + 1, SHAPE[1]))})
            self.assertIn("forma", str(caught.exception))
        with self.assertRaises(TypeError):
            job(grid="rejilla")

    def test_the_weight_of_the_zones_to_avoid(self) -> None:
        """RF-017-06: el peso de las celdas de «preferible no afectar» multiplica el coste: es opcional (sin zonas, todo
        pesa 1), de la forma de la rejilla, y ningún peso baja de 1 ni es NaN."""
        weight = np.ones(SHAPE)
        weight[2:4, 2:5] = 3.0
        found = job(avoid_weight=weight)
        np.testing.assert_array_equal(found.avoid_weight, weight)
        self.assertFalse(found.avoid_weight.flags.writeable)
        for wrong in (np.full(SHAPE, 0.5), np.where(flags(), np.nan, 1.0), np.ones((2, 2))):
            with self.subTest(wrong=wrong.shape), self.assertRaises(ValueError):
                job(avoid_weight=wrong)

    def test_the_cells_of_the_zones_to_avoid_are_apart_from_their_weight(self) -> None:
        """RF-017-06, S-2: las celdas de las zonas «preferible no afectar» (``avoid_zone``: un booleano por celda) van **aparte del peso**: una zona de peso exactamente 1
        (válida: la 012 admite ≥ 1) no se distingue por el peso de «ninguna zona», así que la lleva la máscara; sin ella (quien solo tiene el peso), la zona son las celdas de peso
        mayor que 1; es de la forma de la rejilla y de solo lectura; sin peso no hay zona, y una celda de peso mayor que 1 que no es de la zona es un error del programa."""
        weight = np.ones(SHAPE)
        zone = np.zeros(SHAPE, dtype=bool)
        zone[2:4, 2:5] = True
        found = job(avoid_weight=weight, avoid_zone=zone)
        np.testing.assert_array_equal(found.avoid_zone, zone)
        self.assertEqual(int(found.avoid_zone.sum()), 6)
        self.assertEqual((found.avoid_zone.dtype, found.avoid_zone.flags.writeable), (np.bool_, False))
        heavy = np.ones(SHAPE)
        heavy[2:4, 2:5] = 3.0
        np.testing.assert_array_equal(job(avoid_weight=heavy).avoid_zone, heavy > 1.0)
        np.testing.assert_array_equal(job(avoid_weight=heavy, avoid_zone=zone).avoid_zone, zone)
        for wrong in ({"avoid_weight": weight, "avoid_zone": np.ones((2, 2), dtype=bool)}, {"avoid_zone": zone},
                      {"avoid_weight": heavy, "avoid_zone": np.zeros(SHAPE, dtype=bool)}):
            with self.subTest(wrong=sorted(wrong)), self.assertRaises(ValueError):
                job(**wrong)

    def test_the_code_and_the_profile_are_the_ones_of_a_road(self) -> None:
        """RF-017-01, RF-017-07: el código es el de una pista (``RDW-001``: no el de una accesibilidad, una plataforma ni
        un texto cualquiera) y el perfil, un ``RoadProfile`` ya comprobado (no sus datos sin validar)."""
        for wrong in ("ACC-001", "PLT-001", "road", "rdw-001"):
            with self.subTest(code=wrong), self.assertRaises(ValueError):
                job(code=wrong)
        with self.assertRaises(TypeError):
            job(code=1)
        with self.assertRaises(TypeError):
            job(profile=rd.PROFILE)  # los datos de la prueba, no un RoadProfile
        with self.assertRaises(TypeError):
            job(request=access())
        self.assertEqual(job().profile.code, "pista_principal")

    def test_the_trace_mode_has_an_origin_a_destination_and_a_route(self) -> None:
        """RF-017-02, RF-017-10 (P-14): «trazar» lleva el origen y el destino (un punto o una cota con su zona y su
        tolerancia: la rampa, D-4) y los parámetros de la ruta; sin línea. La cota de la rampa y su tolerancia son de su
        destino; un destino que no es ninguna de las dos cosas, un error del programa."""
        found = job()
        self.assertEqual((found.geometry.origin, found.geometry.destination), (ORIGIN, DESTINATION))
        self.assertIsNone(found.geometry.line)
        self.assertEqual(found.route, route())
        ramp_destination = road_model.LevelDestination(level_m=140.0, tolerance_m=0.28, zone=ZONE)
        ramp = job(geometry=geometry(destination=ramp_destination), end_level_m=None)
        self.assertEqual((ramp.geometry.destination.level_m, ramp.geometry.destination.tolerance_m, ramp.end_level_m),
                         (140.0, 0.28, None))
        self.assertEqual(ramp.geometry.destination.zone[0][0].shape, (4, 2))
        self.assertEqual(ramp.geometry.destination.zone[0][0].dtype, np.float64)
        for changes in ({"geometry": geometry(origin=None)}, {"geometry": geometry(destination=None)},
                        {"geometry": geometry(line=LINE)}, {"route": None}):
            with self.subTest(changes=list(changes)), self.assertRaises(ValueError):
                job(**changes)

    def test_the_axis_modes_have_a_line_and_no_route(self) -> None:
        """RF-017-02, RF-017-18 (P-14): «sobre un eje» lleva la línea en planta y «eje 3D» la línea con su Z (la rasante);
        ni origen, ni destino ni parámetros de la ruta (no buscan ninguna). Una línea de «eje 3D» sin Z, o con una Z que
        no es un número, es un error del programa (la preparación la rechazó con ``des.road_line_no_z``)."""
        on_axis = job(request=road(mode="on_axis", feature="Eje 1"), geometry=road_model.RoadGeometry(line=LINE), route=None)
        self.assertEqual((on_axis.mode, on_axis.geometry.line.shape, on_axis.geometry.line.dtype),
                         (road_model.RoadMode.ON_AXIS, (3, 2), np.float64))
        self.assertIsNone(on_axis.route)
        planar = job(request=road(mode="on_axis"), geometry=road_model.RoadGeometry(line=LINE_3D), route=None)
        self.assertEqual(planar.geometry.line.shape, (3, 3))  # la Z, en «sobre un eje», no cuenta
        axis_3d = job(request=road(mode="axis_3d"), geometry=road_model.RoadGeometry(line=LINE_3D), route=None,
                      start_level_m=None, end_level_m=None)
        np.testing.assert_array_equal(axis_3d.geometry.line[:, 2], [101.0, 103.0, 105.0])
        self.assertFalse(axis_3d.geometry.line.flags.writeable)
        nan_z = np.asarray(LINE_3D)
        nan_z[1, 2] = np.nan
        for changes in ({"request": road(mode="on_axis"), "geometry": road_model.RoadGeometry(line=LINE), "route": route()},
                        {"request": road(mode="on_axis"), "geometry": geometry(), "route": None},
                        {"request": road(mode="on_axis"), "geometry": geometry(line=LINE), "route": None},
                        {"request": road(mode="axis_3d"), "geometry": road_model.RoadGeometry(line=LINE), "route": None},
                        {"request": road(mode="axis_3d"), "geometry": road_model.RoadGeometry(line=nan_z), "route": None},
                        {"request": road(mode="axis_3d"), "geometry": road_model.RoadGeometry(), "route": None}):
            with self.subTest(changes={key: type(value).__name__ for key, value in changes.items()}), \
                    self.assertRaises(ValueError):
                job(**changes)

    def test_the_geometry_is_absolute_float64_and_valid(self) -> None:
        """RF-017-01 (principio 6, regla 4 de AGENTS.md): la geometría de origen va en coordenadas absolutas float64 (un
        origen de 4,4 Mm de norte, exacto) y finita; un punto que no son dos números reales o una línea de menos de dos
        vértices es un error del programa."""
        found = geometry(origin=(500_002.123456789, 4_399_996.987654321))
        self.assertEqual(found.origin, (500_002.123456789, 4_399_996.987654321))
        self.assertTrue(all(type(value) is float for value in found.origin))
        self.assertEqual(geometry(origin=np.array([500_002.5, 4_399_996.5])).origin, (500_002.5, 4_399_996.5))
        for wrong in ((1.0,), (1.0, 2.0, 3.0), "xy", 3.5, (float("nan"), 1.0), (1.0, float("inf"))):
            with self.subTest(origin=wrong), self.assertRaises((TypeError, ValueError)):
                geometry(origin=wrong)
        for wrong in (((500_002.0, 4_399_996.0),), (), ((1.0, float("nan")), (2.0, 3.0))):
            with self.subTest(line=wrong), self.assertRaises(ValueError):
                road_model.RoadGeometry(line=wrong)
        with self.assertRaises(ValueError):
            road_model.RoadGeometry(line=np.zeros((3, 4)))
        for wrong in (1.5, "(1, 2)", [object()]):
            with self.subTest(destination=wrong), self.assertRaises((TypeError, ValueError)):
                geometry(destination=wrong)

    def test_the_level_destination_is_checked(self) -> None:
        """RF-017-02, RF-017-10: la cota del destino por cota es finita, su tolerancia de llegada es un número real de
        (0; 1.000] m y su zona, los anillos (≥ 3 vértices) de un polígono; lo demás, un error del programa."""
        found = road_model.LevelDestination(level_m=140, tolerance_m=1, zone=ZONE)
        self.assertEqual((found.level_m, found.tolerance_m), (140.0, 1.0))
        for changes, error in (({"level_m": "140"}, TypeError), ({"level_m": True}, TypeError),
                               ({"tolerance_m": None}, TypeError), ({"level_m": float("nan")}, ValueError),
                               ({"tolerance_m": 0.0}, ValueError), ({"tolerance_m": -0.1}, ValueError),
                               ({"tolerance_m": 1000.1}, ValueError), ({"zone": ()}, ValueError), ({"zone": ((),)}, ValueError),
                               ({"zone": ((((0.0, 0.0), (1.0, 1.0)),),)}, ValueError),
                               ({"zone": ((((0.0, 0.0), (1.0, float("nan")), (2.0, 0.0)),),)}, ValueError)):
            with self.subTest(changes=changes), self.assertRaises(error):
                road_model.LevelDestination(**{"level_m": 140.0, "tolerance_m": 0.28, "zone": ZONE, **changes})

    def test_the_levels_of_the_ends_are_finite_numbers(self) -> None:
        """RF-017-02 (D-13): las cotas de inicio y de fin resueltas (las del usuario o las de la superficie de partida en
        esos puntos) son números reales finitos o ``None`` (las da la geometría o la ruta); pueden ser negativas."""
        self.assertEqual(job(start_level_m=-5, end_level_m=None).start_level_m, -5.0)
        for wrong, error in (("101", TypeError), (True, TypeError), (float("nan"), ValueError), (float("inf"), ValueError)):
            for name in ("start_level_m", "end_level_m"):
                with self.subTest(name=name, wrong=wrong), self.assertRaises(error):
                    job(**{name: wrong})

    def test_a_job_does_not_need_the_project_to_reproduce(self) -> None:
        """RF-015-02: el mismo trabajo, construido otra vez con el mismo contenido, es el mismo (la petición, las cotas, la
        ruta y los arrays); es la base de reproducir sin proyecto."""
        first, second = job(), job()
        self.assertEqual((first.request, first.route, first.geometry.origin, first.geometry.destination),
                         (second.request, second.route, second.geometry.origin, second.geometry.destination))
        for name in ("start", "cut_allowed", "fill_allowed", "untouchable"):
            np.testing.assert_array_equal(getattr(first, name), getattr(second, name))
        self.assertIsNot(first, second)


class OutcomeTest(unittest.TestCase):
    @staticmethod
    def outcome(**changes: object) -> Any:
        values: dict[str, Any] = {
            "name": "Acceso al tajo", "code": "RDW-001", "mode": "trace", "window": (slice(1, 5), slice(2, 7)),
            "surface": np.full((4, 5), 100.0), "footprint": np.zeros((4, 5), dtype=bool),
            "figures": (figures.FigureSpec("des.road_length_m", 12.5, "m"),),
            "notices": (preview.Notice("des.road_radius_reduced", {"entity": "Acceso", "vertex": 2}),)}
        values.update(changes)
        return road_model.RoadOutcome(**values)

    def test_the_outcome_of_a_road(self) -> None:
        """RF-017-01, RF-017-23 (plan 017 §5.3.1): el resultado de la pista da su nombre, su código, su modo, la ventana de
        trabajo de la rejilla (filas y columnas), la superficie resultante y la huella de la sección en esa ventana, las
        cifras CALCULADO y los avisos; inmutable, con los arrays de solo lectura. Los campos que necesiten las tareas
        que calculan el eje, la rasante, la sección y el grabado se añaden en esas tareas, compatibles hacia atrás."""
        found = self.outcome()
        self.assertEqual((found.name, found.code, found.mode), ("Acceso al tajo", "RDW-001", road_model.RoadMode.TRACE))
        self.assertEqual(found.window, (slice(1, 5), slice(2, 7)))
        self.assertEqual((found.surface.shape, found.footprint.dtype, found.surface.flags.writeable), ((4, 5), np.bool_, False))
        self.assertEqual((len(found.figures), len(found.notices)), (1, 1))
        self.assertEqual(self.outcome(figures=(), notices=()).notices, ())
        self.assertEqual(self.outcome(notices=[]).notices, ())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            found.name = "otra"  # type: ignore[misc]

    def test_the_outcome_is_checked(self) -> None:
        """RF-017-01: un resultado con otra forma de ventana, un código que no es de una pista, un modo que no existe o
        cifras y avisos de otro tipo es un error del programa."""
        for changes, error in (({"surface": np.zeros((4, 6))}, ValueError), ({"footprint": np.zeros((3, 5), dtype=bool)}, ValueError),
                               ({"window": (slice(1, 5), slice(2, 8))}, ValueError), ({"window": (slice(5, 1), slice(2, 7))}, ValueError),
                               ({"window": (slice(1, 5, 2), slice(2, 7))}, ValueError), ({"window": (1, 5)}, TypeError),
                               ({"code": "ACC-001"}, ValueError), ({"mode": "ruta"}, ValueError),
                               ({"figures": ("longitud",)}, TypeError), ({"notices": ("aviso",)}, TypeError),
                               ({"name": 7}, TypeError)):
            with self.subTest(changes=list(changes)), self.assertRaises(error):
                self.outcome(**changes)


class AccessRequestTest(unittest.TestCase):
    def test_the_request_of_an_accessibility(self) -> None:
        """RF-017-24 (plan 017 §5.2.2 y §5.3.3; D-17): la accesibilidad pide su nombre, la capa de sus puntos de entrada
        (con su campo) y la superficie; la pendiente y el ancho transitables, el área mínima de berma y los datos de
        bermas son ``None`` si no se piden (HIPÓTESIS sin valor por defecto: el rechazo de RF-015-08); inmutable y
        comparable por valor. **Sin ``start``**: no parte de ninguna superficie."""
        request = access()
        for name in ("berms", "walk_slope_pct", "walk_width_m", "min_berm_area_m2"):
            with self.subTest(field=name):
                self.assertIsNone(getattr(request, name))
        self.assertEqual((request.name, request.surface, request.entries.layer),
                         ("Accesos del tajo", "gis_dtm_tajo", "gis_fea_pistas_entradas"))
        self.assertEqual(request.layer, request.entries.layer)
        self.assertEqual(request, access())
        self.assertEqual(len({request, access()}), 1)
        wanted = {item.value for item in params.AccessParam} - {"discarded", "entries_layer"}
        asked = {item.name for item in dataclasses.fields(road_model.AccessRequest)} - {"entries"}
        self.assertEqual(asked, wanted)
        self.assertNotIn("start", asked)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            request.name = "otra"  # type: ignore[misc]
        with self.assertRaises(TypeError):
            road_model.AccessRequest(name="a", entries=layer_fields())  # type: ignore[call-arg]

    def test_values_are_normalized_and_checked(self) -> None:
        """RF-017-24: los textos sin los espacios de los extremos; los números, ``float``; los datos de bermas, una lista
        de nombres sin repetir y en su orden (sin ellos, todos los al día de la versión: ``None``); un nombre en
        blanco, ``des.entity_name_missing``; lo demás, un error del programa."""
        request = access(name="  Accesos ", surface=" gis_dtm_tajo ", walk_slope_pct=16, walk_width_m=4, min_berm_area_m2=300,
                         berms=(" gis_brm_a ", "gis_brm_b", "gis_brm_a"))
        self.assertEqual((request.name, request.surface), ("Accesos", "gis_dtm_tajo"))
        self.assertEqual((request.walk_slope_pct, type(request.walk_slope_pct), request.min_berm_area_m2), (16.0, float, 300.0))
        self.assertEqual(request.berms, ("gis_brm_a", "gis_brm_b"))
        self.assertEqual(access(berms=["gis_brm_a"]).berms, ("gis_brm_a",))
        self.assertEqual(len({access(berms=("a",)), access(berms=("a",))}), 1)
        for blank in ("", "  "):
            with self.subTest(name=blank), self.assertRaises(messages.DesignError) as caught:
                access(name=blank)
            self.assertEqual((caught.exception.code, caught.exception.field), ("des.entity_name_missing", "name"))
        for changes in ({"name": 7}, {"entries": "entradas"}, {"surface": None}, {"walk_slope_pct": "16"},
                        {"walk_width_m": True}, {"min_berm_area_m2": "300"}, {"berms": "gis_brm_a"}, {"berms": (7,)}):
            with self.subTest(changes=changes), self.assertRaises(TypeError):
                access(**changes)
        for changes in ({"berms": ()}, {"berms": ("a", "  ")}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                access(**changes)


class AccessJobTest(unittest.TestCase):
    @staticmethod
    def zone(code: str = "REQ-001", cells: object = (3, 4, 11)) -> Any:
        return road_model.AccessCells(code=code, name="Zona 1", cells=np.asarray(cells, dtype=np.int64))

    def test_a_job_carries_everything_that_was_read_and_nothing_of_the_project(self) -> None:
        """RF-017-24, RF-017-25 (plan 017 §5.3.1): el trabajo de la accesibilidad lleva todo lo leído —la petición, el
        código (``ACC-001``), la rejilla, la superficie, los puntos de entrada, lo que no se atraviesa, la pendiente y el
        ancho transitables, el área mínima de berma y, si los hay, la superficie final de la cantera, las bermas, las
        plataformas y las zonas «requiere acceso»— y **nada del proyecto**; inmutable, con los arrays de solo lectura."""
        found = access_job()
        names = [item.name for item in dataclasses.fields(road_model.AccessJob)]
        self.assertEqual(names, ["request", "code", "grid", "surface", "entries", "untouchable", "walk_slope_pct",
                                 "walk_width_m", "min_berm_area_m2", "final", "berms", "platforms", "zones"])
        for forbidden in ("project", "path", "conn", "store", "version", "writer"):
            self.assertFalse(any(forbidden in name for name in names), forbidden)
        for item in dataclasses.fields(road_model.AccessJob):
            with self.subTest(field=item.name):
                self.assertNotIsInstance(getattr(found, item.name), (pathlib.PurePath, sqlite3.Connection, os.PathLike))
        self.assertFalse(hasattr(found, "__dict__"))
        self.assertEqual((found.request, found.code, found.final, found.berms, found.platforms, found.zones),
                         (access(), "ACC-001", None, (), (), ()))
        self.assertEqual((found.walk_slope_pct, found.walk_width_m, found.min_berm_area_m2), (16.0, 4.0, 300.0))
        for name in ("surface", "untouchable"):
            with self.subTest(array=name):
                self.assertEqual(getattr(found, name).shape, SHAPE)
                self.assertFalse(getattr(found, name).flags.writeable)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            found.surface = None  # type: ignore[misc]

    def test_entries_berms_platforms_and_zones(self) -> None:
        """RF-017-24, RF-017-25 (plan 017 §5.2.3, A10 y A11): los puntos de entrada son absolutos float64 con su nombre; la
        superficie final de la cantera, las bermas (la cota de berma de cada celda, ``NaN`` fuera) y las plataformas y
        zonas (sus celdas, por índice de la rejilla en filas) se leen una vez y son de la forma de la rejilla; una lista de
        entradas **vacía** es construible (el rechazo «sin punto de entrada» es de quien calcula, con su capa)."""
        berm = np.full(SHAPE, np.nan)
        berm[3, 2:6] = 125.0
        found = access_job(final=surface() + 15.0, berms=(road_model.BermGrid("gis_brm_a", berm),),
                           platforms=(road_model.AccessCells("PLT-001", "Plataforma 1", np.array([5, 6, 7])),),
                           zones=(self.zone(),))
        self.assertEqual((found.entries[0].name, found.entries[0].x, found.entries[0].y),
                         ("Entrada", 500_002.0, 4_399_996.0))
        self.assertFalse(found.final.flags.writeable)
        self.assertEqual((found.berms[0].name, found.berms[0].levels.shape, found.berms[0].levels.dtype), ("gis_brm_a", SHAPE, np.float64))
        self.assertFalse(found.berms[0].levels.flags.writeable)
        self.assertEqual((found.platforms[0].code, found.platforms[0].cells.tolist()), ("PLT-001", [5, 6, 7]))
        self.assertEqual((found.zones[0].code, found.zones[0].name, found.zones[0].cells.tolist()), ("REQ-001", "Zona 1", [3, 4, 11]))
        self.assertFalse(found.zones[0].cells.flags.writeable)
        self.assertEqual(access_job(entries=()).entries, ())
        self.assertEqual(access_job(entries=[road_model.EntryPoint("A", 500_004.0, 4_399_992.0)]).entries[0].name, "A")

    def test_what_is_read_is_checked(self) -> None:
        """RF-017-04, RF-017-24: la superficie, la final y las bermas son de la forma de la rejilla; las celdas de una
        plataforma o de una zona son índices enteros de la rejilla (de 0 al número de celdas); la pendiente, el ancho y el
        área mínima están en su rango (``params.ACCESS_RANGES``: > 0, > 0 y ≥ 0); el código es el de una accesibilidad;
        lo demás, un error del programa."""
        size = SHAPE[0] * SHAPE[1]
        bad_shape = np.zeros((SHAPE[0], SHAPE[1] + 1))
        for changes, error in (({"surface": bad_shape}, ValueError), ({"untouchable": bad_shape}, ValueError),
                               ({"final": bad_shape}, ValueError),
                               ({"berms": (road_model.BermGrid("gis_brm_a", bad_shape),)}, ValueError),
                               ({"platforms": (road_model.AccessCells("PLT-001", "P", np.array([size])),)}, ValueError),
                               ({"walk_slope_pct": 0.0}, ValueError), ({"walk_slope_pct": -1.0}, ValueError),
                               ({"walk_width_m": 0.0}, ValueError), ({"min_berm_area_m2": -1.0}, ValueError),
                               ({"walk_slope_pct": float("nan")}, ValueError), ({"walk_slope_pct": "16"}, TypeError),
                               ({"walk_width_m": True}, TypeError), ({"code": "RDW-001"}, ValueError),
                               ({"code": "PLT-001"}, ValueError), ({"request": road()}, TypeError),
                               ({"entries": ("Entrada",)}, TypeError), ({"berms": ("gis_brm_a",)}, TypeError),
                               ({"grid": None}, TypeError)):
            with self.subTest(changes=list(changes)), self.assertRaises(error):
                access_job(**changes)
        self.assertEqual(access_job(min_berm_area_m2=0).min_berm_area_m2, 0.0)

    def test_the_small_pieces_are_checked(self) -> None:
        """RF-017-04, RF-017-25: un punto de entrada tiene nombre y dos coordenadas finitas; las celdas, un array 1-D de
        enteros; una berma, un nombre y una rejilla 2-D; lo demás, un error del programa."""
        for args, error in ((("", 1.0, 2.0), ValueError), (("A", float("nan"), 2.0), ValueError), (("A", 1.0, True), TypeError),
                            ((7, 1.0, 2.0), TypeError)):
            with self.subTest(entry=args), self.assertRaises(error):
                road_model.EntryPoint(*args)
        for cells, error in ((np.array([1.5]), TypeError), (np.zeros((2, 2), dtype=np.int64), ValueError),
                             (np.array(["a"]), TypeError), (np.array([True]), TypeError)):
            with self.subTest(cells=cells), self.assertRaises(error):
                road_model.AccessCells("REQ-001", "Z", cells)
        for args, error in ((("", np.zeros(SHAPE)), ValueError), (("a", np.zeros(5)), ValueError), ((7, np.zeros(SHAPE)), TypeError)):
            with self.subTest(berm=args[0]), self.assertRaises(error):
                road_model.BermGrid(*args)
        with self.assertRaises(ValueError):
            road_model.AccessCells("REQ-001", "Z", np.array([-1]))
        self.assertEqual(road_model.AccessCells("REQ-001", "Z", []).cells.tolist(), [])
        self.assertEqual(road_model.AccessCells("REQ-001", "Z", np.array([4, 2], dtype=np.uint16)).cells.dtype, np.int64)


class AccessOutcomeTest(unittest.TestCase):
    @staticmethod
    def outcome(**changes: object) -> Any:
        values: dict[str, Any] = {
            "name": "Accesos del tajo", "code": "ACC-001", "reachable": np.ones(SHAPE, dtype=bool), "z_min_m": 115.0,
            "z_max_m": 140.0, "area_m2": 1200.5}
        values.update(changes)
        return road_model.AccessOutcome(**values)

    def test_what_is_reachable_and_the_lists_that_follow(self) -> None:
        """RF-017-24, RF-017-25 (plan 017 §5.2.3, A10 y A11): el resultado da la rejilla de lo alcanzable (booleana, de solo
        lectura), las cotas mínima y máxima alcanzables y el área (``None`` las cotas si no se alcanza ninguna celda) y,
        si se piden, la cota mínima sobre la superficie final y las listas de bermas, plataformas y zonas con su
        comunicación (cota real y área; cota a que se llega; lugar, distancia y diferencia de cota de las que no); todo
        opcional en la parte A10, que da lo alcanzable antes de las listas."""
        bare = self.outcome()
        self.assertEqual((bare.z_min_m, bare.z_max_m, bare.area_m2, bare.z_min_final_m), (115.0, 140.0, 1200.5, None))
        self.assertEqual((bare.berms, bare.platforms, bare.zones, bare.figures, bare.notices), ((), (), (), (), ()))
        self.assertFalse(bare.reachable.flags.writeable)
        full = self.outcome(
            z_min_final_m=140.0,
            berms=(road_model.BermReach(number=1, level_m=135.0, area_m2=8000.0, connected=True, x=500_004.0, y=4_399_992.0),
                   road_model.BermReach(2, 105.0, 8000.0, False, 500_006.0, 4_399_990.0)),
            platforms=(road_model.PlatformReach("PLT-001", True, 125.0), road_model.PlatformReach("PLT-002", False, None)),
            zones=(road_model.ZoneReach("REQ-001", True), road_model.ZoneReach("REQ-002", False, 500_010.0, 4_399_994.0, 31.5, -10.0)),
            figures=(figures.FigureSpec("des.acc_z_min_m", 115.0, "m"),),
            notices=(preview.Notice("des.road_start_is_final", {"entity": "Acceso", "z_final": 140.0}),))
        self.assertEqual([item.connected for item in full.berms], [True, False])
        self.assertEqual((full.berms[0].number, full.berms[0].level_m, full.berms[0].area_m2), (1, 135.0, 8000.0))
        self.assertEqual((full.platforms[0].level_m, full.platforms[1].level_m), (125.0, None))
        self.assertEqual((full.zones[0].distance_m, full.zones[1].distance_m, full.zones[1].level_difference_m), (None, 31.5, -10.0))
        self.assertEqual((full.zones[1].x, full.zones[1].y), (500_010.0, 4_399_994.0))
        nothing = self.outcome(z_min_m=None, z_max_m=None, area_m2=0.0, reachable=np.zeros(SHAPE, dtype=bool))
        self.assertEqual((nothing.z_min_m, nothing.z_max_m, nothing.area_m2), (None, None, 0.0))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            full.z_min_m = 0.0  # type: ignore[misc]

    def test_the_outcome_is_checked(self) -> None:
        """RF-017-24: lo alcanzable que no es una rejilla 2-D, un código que no es de una accesibilidad, una cota que no
        es un número real finito, un área negativa y las listas de otro tipo son errores del programa."""
        for changes, error in (({"reachable": np.ones(5, dtype=bool)}, ValueError), ({"code": "RDW-001"}, ValueError),
                               ({"z_min_m": "115"}, TypeError), ({"z_max_m": float("nan")}, ValueError),
                               ({"z_min_final_m": True}, TypeError), ({"area_m2": -1.0}, ValueError),
                               ({"area_m2": None}, TypeError), ({"name": 7}, TypeError), ({"berms": ("a",)}, TypeError),
                               ({"platforms": ("a",)}, TypeError), ({"zones": ("a",)}, TypeError),
                               ({"figures": ("a",)}, TypeError), ({"notices": ("a",)}, TypeError)):
            with self.subTest(changes=list(changes)), self.assertRaises(error):
                self.outcome(**changes)
        for args, error in (((1, 135.0, -1.0, True, 1.0, 2.0), ValueError), ((1.5, 135.0, 1.0, True, 1.0, 2.0), TypeError),
                            ((1, 135.0, 1.0, 1, 1.0, 2.0), TypeError), ((1, float("nan"), 1.0, True, 1.0, 2.0), ValueError)):
            with self.subTest(berm=args), self.assertRaises(error):
                road_model.BermReach(*args)
        for args, error in ((("", True, 1.0), ValueError), (("PLT-001", 1, 1.0), TypeError), (("PLT-001", True, "1"), TypeError)):
            with self.subTest(platform=args), self.assertRaises(error):
                road_model.PlatformReach(*args)
        for args, error in ((("", True), ValueError), (("REQ-001", 1), TypeError),
                            (("REQ-001", False, 1.0, None, None), ValueError), (("REQ-001", False, "1", 2.0), TypeError),
                            (("REQ-001", False, 1.0, 2.0, -3.0), ValueError)):
            with self.subTest(zone=args), self.assertRaises(error):
                road_model.ZoneReach(*args)


def module_imports(name: str) -> set[str]:
    """Los módulos de ``design`` que importa ``design/<name>.py`` **al importarse**: los imports relativos de nivel de módulo
    (``from .preview import …``, ``from . import x``), sin los de ``if TYPE_CHECKING`` ni los de dentro de una función o de una
    clase, que son los que lo hacen perezoso."""
    tree = ast.parse((EXTENSION_DIR / "design" / f"{name}.py").read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            found.update([node.module] if node.module else [alias.name for alias in node.names])
    return found


class LazyTest(unittest.TestCase):
    """RNF-001-03 (RNF-017-10): habilitar Geoblender no crea los datos de la pista ni carga la tabla de los perfiles. En el
    «verde», por el árbol sintáctico (cuesta milisegundos); la comprobación en un proceso nuevo, que cuesta casi un segundo,
    es de ``milestone_road_model.py``."""

    def test_the_model_does_not_import_the_road_data(self) -> None:
        """RNF-001-03: ``design.model`` (que habilitar importa) no importa ``design.road_model`` al importarse y los
        módulos pesados que vigila ``test_lazy_registration`` (los que ``bl`` no puede alcanzar al registrar) lo incluyen:
        la pista se pide a ``design.road_model``."""
        self.assertNotIn("road_model", module_imports("model"))
        self.assertIn("design.road_model", test_lazy_registration.HEAVY)

    def test_the_road_data_import_the_profiles_only_when_they_use_them(self) -> None:
        """RNF-001-03, T04: ``design.road_model`` **no importa** ``design.road_profiles`` (la tabla de los perfiles, su edición y
        su base de datos) al importarse; lo importa una sola vez, dentro de ``RoadJob``, al construir un trabajo."""
        imported = module_imports("road_model")
        self.assertNotIn("road_profiles", imported)
        self.assertTrue({"model", "params", "preview", "supported_requests"} <= imported)
        source = (EXTENSION_DIR / "design" / "road_model.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        job = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "RoadJob")
        inside = [node for node in ast.walk(job)
                  if isinstance(node, ast.ImportFrom) and node.level == 1 and (node.module == "road_profiles" or
                                                                          [alias.name for alias in node.names] == ["road_profiles"])]
        self.assertEqual(len(inside), 1)


if __name__ == "__main__":
    unittest.main()
