# SPDX-License-Identifier: GPL-3.0-or-later
"""Preparar la pista y rechazar (spec 017, T19; HU-017-1 y HU-017-2; RF-017-01 a RF-017-06; RF-015-06, RF-015-07, RF-015-08 y RF-015-09; plan 017 §5.1, §5.2.1 a §5.2.3, §5.3.1,
§5.7 P-1 y P-5; D-3, D-13 y D-16): ``design.road_store`` **lee y comprueba antes de calcular**, sin escribir nada: la versión editable, la geometría de origen por modo (los puntos de
una capa del proyecto, o la línea de «sobre un eje»), el perfil de la versión, las cotas de inicio y de fin (las del usuario o las de la superficie de partida, con su origen), la
partida y la cadena, las máscaras de la versión y los parámetros sin valor por defecto. Cada rechazo de RF-017-04 sale **sin escribir nada** (el contador de cambios de la base, las
operaciones, los datos, los parámetros y los ficheros no se mueven) y nombrando la capa, la pista (o el perfil), el campo y el valor.

Sobre el proyecto de las pistas (``tests.support.road_data``: la cantera de la 015 con los terrenos como rejillas, en la gruesa de 2 m, 200 × 200 celdas) con el perfil de referencia de IMGA
(**solo de las pruebas**, D-2) en V01. Lo que cambia el proyecto (una pista hecha antes, un sector sin búsqueda, una versión cerrada, una plataforma de destino) es de
``milestone_road_prepare``.

**Qué queda aquí (T48, RNF-017-09).** Las pruebas puras (:class:`RouteGuardsTest`, :class:`PureTest`, :class:`DefaultStartTest`) y las ayudas que importan los hitos y las pruebas de las pistas
(:class:`PrepareCase`, ``request``, ``drive`` y las constantes). :class:`RoadPrepareTest` (preparar y rechazar sobre el proyecto: 21 pruebas, ≈ 1,2 s) pasó al paso «hito» como
``milestone_road_prepare_checks``.
"""

from __future__ import annotations

import contextlib
import dataclasses
import sqlite3
import unittest
from types import SimpleNamespace
from typing import Any, ClassVar
from unittest import mock

import numpy as np

from tests.support import quarry_fixtures as qfx
from tests.support import res_fixtures
from tests.support import road_data as rd
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.versions_fixtures import change_counter

access = import_geoblender("gis.masks.access")
core_params = import_geoblender("core.params")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
design_params = import_geoblender("design.params")
gis = import_geoblender("gis")
messages = import_geoblender("design.messages")
provenance = import_geoblender("design.provenance")
res_provenance = import_geoblender("reserves.provenance")
road_model = import_geoblender("design.road_model")
road_profiles = import_geoblender("design.road_profiles")
road_section = import_geoblender("design.road_section")
road_store = import_geoblender("design.road_store")
versions_model = import_geoblender("core.versions.model")

DesignError = messages.DesignError
GRID = qfx.grid_of(qfx.COARSE_STEP_M)
"""La rejilla gruesa de la cantera (200 × 200 celdas de 2 m)."""
RAMP = rd.dataset_of("rampa")
HOLLOW = "gis_dtm_hueco"
FINE = "gis_dtm_fina"
PROFILE = "pista_principal"
NARROW = "angosto"
EMPTY = "vacio"
CODE = "RDW-001"
KEY = "des.road.rdw_001."
BY = "Samuel (IMGA)"
ROUTE_FIELDS = ("mesh_m", "level_step_m", "max_cut_fill_m", "lambda_per_m", "turn_m", "margin_m", "simplify_m", "arrival_tol_m", "search_budget")
HOLE_BOX = (90.0, 190.0, 110.0, 210.0)
"""Lo que no tiene dato alrededor del origen de la rampa (local)."""


def absolute(point: tuple[float, float]) -> tuple[float, float]:
    """El punto local ``point`` como absoluto en la rejilla de 2 m."""
    x, y = rd.absolute([point], GRID)[0]
    return float(x), float(y)


def request(name: str = "Pista de la rampa", *, mode: str = "trace", layer: str = rd.POINTS_LAYER, surface: str = RAMP, profile: str = PROFILE,
            route: bool | None = None, **changes: Any) -> Any:
    """Una pista de la capa de puntos de las pistas (o, en los otros modos, de la de ejes) sobre ``surface``, con los parámetros de la ruta y el perfil de la referencia de IMGA (solo de
    las pruebas)."""
    trace = mode == "trace"
    base: dict[str, Any] = {"origin": "Origen rampa", "destination": "Destino rampa"} if trace else {"feature": "Eje de 200 m"}
    if trace if route is None else route:
        base.update({field: getattr(rd.ROUTE, field) for field in ROUTE_FIELDS})
    return road_model.RoadRequest(name, road_model.LayerFields(layer, "nombre"), mode, profile, surface, **{**base, **changes})


def never(request: Any) -> Any:  # solo declara que se repite sola
    raise AssertionError("las pruebas del «verde» no recalculan ni reproducen")


def drive[T](work: Any) -> T:
    """Lo que devuelve ``work`` (unidades de preparación) llevado hasta el final."""
    while True:
        try:
            next(work)
        except StopIteration as stop:
            return stop.value  # type: ignore[no-any-return]


class PrepareCase(rd.RoadProjectCase):
    """Una copia por clase del proyecto de las pistas (rejilla de 2 m) con las máscaras de V01 cargadas, el perfil de referencia en V01, dos perfiles rotos (un radio mínimo que no cabe y
    uno sin valores), un terreno con un hueco sin dato y otro en una rejilla distinta (de 1 m)."""

    STEP_M = qfx.COARSE_STEP_M
    masks_v1: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_definitions((*design_params.DEFINITIONS, *design_params.QUARRY_DEFINITIONS))
        cls.addClassCleanup(core_params.unregister_definitions, "des")
        core_params.register_definitions(res_provenance.VERIFY_DEFINITIONS)
        cls.addClassCleanup(core_params.unregister_definitions, "res")
        core_params.register_families(design_params.ROAD_PROFILE_FAMILIES)
        core_params.register_families(design_params.ROAD_FAMILIES)
        cls.addClassCleanup(core_params.unregister_families, "des")
        cls.enterClassContext(registered(*road_profiles.OPERATIONS, cls.road_definition(), *provenance.ROAD_FIGURES))
        cls.masks_v1 = access.load_masks(cls.project, cls.v1.uid)
        declared = road_profiles.ProfileDeclaration("ITC 07.1.03 de la prueba", BY, "Perfil de la prueba de la T19", version=cls.v1.code)
        values = {param: getattr(rd.PROFILE, "class_name" if param.value == "class" else param.value) for param in design_params.RoadProfileParam}
        cls.clock.advance(minutes=1)
        road_profiles.edit_road_profiles(cls.project, (road_profiles.ProfileEdit(name="PISTA_PRINCIPAL", values=values),), declared)
        cls.broken_profiles(declared, values)
        hole = rd.ramp_terrain(GRID)
        for box in (HOLE_BOX, rd.ZONES[0][1]):
            hole[rd.in_box(box, GRID)] = np.nan
        fine = qfx.grid_of(qfx.STEP_M)
        res_fixtures.write_grids(cls.project, [("hueco", gis.Raster(GRID, hole, rd.CRS, rd.VERTICAL)),
                                               ("fina", gis.Raster(fine, np.full(fine.shape, 100.0), rd.CRS, rd.VERTICAL))],
                                 message="Terrenos de la prueba de preparar la pista")

    @classmethod
    def road_definition(cls) -> Any:
        """El tipo ``des.road`` tal como lo registra la clase: sin recalcular ni reproducir (el «verde» no los usa); las clases que sí (``milestone_road_recompute``, T22) lo cambian por el que
        trae las funciones **reales**, como el gancho ``definitions`` de la 015."""
        return provenance.operation_def(provenance.ROAD, never)

    @classmethod
    def broken_profiles(cls, declared: Any, values: dict[Any, Any]) -> None:
        """Dos perfiles en la tabla que ``edit_road_profiles`` no dejaría crear: ``ANGOSTO`` (un radio mínimo menor que la semianchura) y ``VACIO`` (sin ningún valor)."""
        store = core_params.ParameterStore(cls.project)
        narrow = {**values, design_params.RoadProfileParam.MIN_RADIUS: 3.0}
        with cls.project.write_transaction() as conn:
            for code, name in ((NARROW, "ANGOSTO"), (EMPTY, "VACIO")):
                conn.execute("INSERT INTO des_road_profile (uid, code, name, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
                             (f"uid-{code}", code, name, BY, "2026-11-21T00:00:00Z"))
            road_profiles._write_values(conn, store, NARROW, narrow, declared)

    def state(self) -> dict[str, Any]:
        """Todo lo que podría escribir la preparación: el contador de cambios de la base y, aparte, lo que se vería: operaciones, datos, parámetros y los ficheros de ``rasters/``."""
        return {
            "counter": change_counter(self.root),
            "operations": self.query("SELECT uid, status FROM gb_operation ORDER BY rowid"),
            "datasets": self.query("SELECT uid, status, content_sha256 FROM gb_dataset ORDER BY rowid"),
            "parameters": self.query("SELECT key, scope_uid, value FROM gb_parameter ORDER BY rowid"),
            "files": sorted(path.name for path in (self.root / "rasters").iterdir())}

    def prepare(self, asked: Any, *, version: Any = "default", **options: Any) -> Any:
        """:func:`prepare_road` con V01 por defecto y sus máscaras."""
        which = self.v1.uid if version == "default" else version
        return road_store.prepare_road(self.project, asked, version=which, masks=options.pop("masks", self.masks_v1), **options)

    def refused(self, asked: Any, expected: str, **options: Any) -> Any:
        """``asked`` se rechaza con el código ``expected`` y **no escribe nada**; devuelve el error, cuyo texto no deja ningún marcador sin llenar en ninguno de los dos idiomas."""
        before = self.state()
        with self.assertRaises(DesignError if expected.startswith("des.") else Exception) as caught:
            self.prepare(asked, **options)
        error = caught.exception
        self.assertEqual(error.code, expected)
        self.assertEqual(self.state(), before, "el rechazo ha escrito algo")
        for text in ((error.text, error.text_in("en")) if isinstance(error, DesignError) else (str(error),)):
            self.assertNotIn("{", text)
        return error


class RouteGuardsTest(unittest.TestCase):
    """Los tres comprobadores de la preparación de la ruta de la T41 (B-3 y B-5 de la verificación única), **puros** (sin proyecto: el «verde» no suma ni 5 ms); preparar con ellos sobre el proyecto es de
    ``milestone_road_prepare.RouteGuardsTest``."""

    def test_a_level_step_that_gives_too_many_levels_is_rejected_with_the_minimum_step(self) -> None:
        """RF-017-04, RF-017-10, RNF-017-06 (B-5): con H = 14 m, un paso de cota de 0,0001 m (140.000 niveles a cada lado: 108 s en una sola llamada y 424 MiB) se rechaza **sin calcular**, con el campo
        (``level_step_m``), el valor, los niveles que saldrían, el tope (2.000) y **el paso mínimo para esa altura** (0,007 m); los 50 niveles de la referencia (14 m, 0,28 m) y el límite exacto (0,007 m: 2.000
        niveles) pasan, y un valor que falta o fuera de rango lo dicen sus reglas, no esta."""
        values = {"max_cut_fill_m": 14.0, "level_step_m": 0.0001}
        with self.assertRaises(DesignError) as caught:
            road_store._check_level_count(request(), CODE, values)
        error = caught.exception
        self.assertEqual(error.code, "des.road_level_step_small")
        self.assertEqual((error.values["field"], error.values["value"]), (f"{KEY}level_step_m", 0.0001))
        self.assertEqual((error.values["height"], error.values["levels"], error.values["limit"], error.values["minimum"]), (14.0, 140_000, 2000, 0.007))
        self.assertIn("0,007", error.text)
        self.assertIn("0.007", error.text_in("en"))
        for text in (error.text, error.text_in("en")):
            self.assertNotIn("{", text)
            self.assertNotIn("?", text)
        for fine in ({"max_cut_fill_m": 14.0, "level_step_m": 0.28}, {"max_cut_fill_m": 14.0, "level_step_m": 0.007}, {"max_cut_fill_m": 14.0},
                     {"max_cut_fill_m": 14.0, "level_step_m": 0.0}, {"max_cut_fill_m": 0.0, "level_step_m": 0.0001}):
            self.assertIsNone(road_store._check_level_count(request(), CODE, fine), fine)

    def test_two_points_in_the_same_node_of_the_mesh_are_rejected_before_calculating(self) -> None:
        """RF-017-04, RF-017-12 (B-3): el origen y el destino que caen en el mismo nodo de la malla de la ruta (la rejilla de 2 m con la malla de 400 m: un nodo; o dos puntos a 3 m con la de 4 m) se
        rechazan con ``des.road_same_node`` —la capa, la pista, el campo ``destination``, el valor, la malla y el centro del nodo—, nunca con un ``ValueError``; con la malla de la referencia (4 m) y puntos
        de nodos distintos no."""
        origin, destination = absolute(rd.RAMP_ORIGIN), absolute(rd.RAMP_DESTINATION)
        with self.assertRaises(DesignError) as caught:
            road_store._check_apart(request(), CODE, GRID, 400.0, origin, destination)
        error = caught.exception
        self.assertEqual(error.code, "des.road_same_node")
        self.assertEqual((error.values["field"], error.values["value"], error.values["mesh"]), (f"{KEY}destination", "Destino rampa", 400.0))
        self.assertEqual((error.values["layer"], error.values["x"], error.values["y"]), (rd.POINTS_LAYER, GRID.west + 200.0, GRID.north - 200.0))
        self.assertIn("400 m", error.text)
        for text in (error.text, error.text_in("en")):
            self.assertNotIn("{", text)
            self.assertNotIn("?", text)
        with self.assertRaises(DesignError):
            road_store._check_apart(request(), CODE, GRID, 4.0, origin, (origin[0] + 3.0, origin[1]))
        self.assertIsNone(road_store._check_apart(request(), CODE, GRID, 4.0, origin, destination))

    def test_a_search_budget_over_twice_the_default_carries_the_memory_notice(self) -> None:
        """RF-017-10, RNF-017-07 (B-5): un presupuesto de estados de 20 M (admite hasta 10⁹) da el aviso ``des.road_budget_memory`` con la memoria que puede ocupar (≈ 2,6 GiB con 140 bytes por estado
        visto), que no impide crearla; con el de la referencia o el doble del de por defecto, ninguno."""
        reference = road_model.RouteParams(**{field: getattr(rd.ROUTE, field) for field in ROUTE_FIELDS})
        self.assertIsNone(road_store._budget_notice("Pista de la rampa", reference))
        big = dataclasses.replace(reference, search_budget=20_000_000)
        notice = road_store._budget_notice("Pista de la rampa", big)
        self.assertEqual(notice.code, "des.road_budget_memory")
        self.assertEqual((notice.values["entity"], notice.values["budget"], notice.values["default"], notice.values["bytes"]), ("Pista de la rampa", 20_000_000, 5_000_000, 140))
        self.assertAlmostEqual(notice.values["memory"], 2.6, places=1)
        self.assertEqual(notice.severity, "warning")
        for language in ("es", "en"):
            self.assertNotIn("?", notice.text(language))
        self.assertIsNone(road_store._budget_notice("Pista de la rampa", dataclasses.replace(reference, search_budget=10_000_000)))


class PureTest(unittest.TestCase):
    """Las piezas puras de la preparación (sin proyecto)."""

    def test_the_cells_of_the_zones_to_avoid_are_apart_from_their_weight(self) -> None:
        """RF-017-06, S-2: ``avoid_layers`` da el peso (el **mayor** de las zonas que pisan la celda) y **aparte** las celdas de las zonas (la unión de sus máscaras), de modo que una
        zona de peso exactamente 1 —válida: la 012 pide ≥ 1— es zona aunque pese lo mismo que «ninguna»; sin zonas, ninguna de las dos; ``avoid_weight`` y ``avoid_zone`` dan cada una la suya."""
        zone = np.zeros(GRID.shape, dtype=bool)
        zone[10:20, 30:40] = True
        other = np.zeros(GRID.shape, dtype=bool)
        other[15:25, 35:45] = True

        class FakeRuns:
            def __init__(self, mask: np.ndarray) -> None:
                self.found = mask

            def mask(self, shape: tuple[int, int]) -> np.ndarray:
                return self.found

        def masks_of(zones: dict[str, Any]) -> Any:
            return SimpleNamespace(grid=GRID, avoid_weights=lambda: zones)

        self.assertIsNone(road_store.avoid_layers(masks_of({})))
        light = masks_of({"a": (FakeRuns(zone), 1.0)})
        weight, cells = road_store.avoid_layers(light)
        np.testing.assert_array_equal(weight, np.ones(GRID.shape))
        np.testing.assert_array_equal(cells, zone)
        self.assertEqual((int(cells.sum()), cells.dtype), (100, np.bool_))
        mixed = masks_of({"a": (FakeRuns(zone), 1.0), "b": (FakeRuns(other), 5.0)})
        weight, cells = road_store.avoid_layers(mixed)
        np.testing.assert_array_equal(cells, zone | other)
        self.assertEqual((float(weight[12, 32]), float(weight[17, 37]), float(weight[22, 42]), float(weight[0, 0])), (1.0, 5.0, 5.0, 1.0))
        np.testing.assert_array_equal(road_store.avoid_weight(mixed), weight)
        np.testing.assert_array_equal(road_store.avoid_zone(mixed), cells)
        self.assertIsNone(road_store.avoid_zone(masks_of({})))

    def test_the_references_of_an_origin_and_a_destination(self) -> None:
        """RF-017-02, RF-017-03: ``RDW-001@100,5`` es el eje de otra pista a la abscisa 100,5; ``entity:PLT-001``, una entidad; lo demás, un punto de la capa por su nombre o su ``fid``."""
        parse = road_store.parse_reference
        self.assertEqual(parse("RDW-001@100"), road_store.AxisReference("RDW-001", 100.0))
        self.assertEqual(parse(" RDW-012@0,5 "), road_store.AxisReference("RDW-012", 0.5))
        self.assertEqual(parse("entity:PLT-001"), road_store.EntityReference("PLT-001"))
        for text in ("Origen rampa", "7", "RDW-001", "RDW-001@", "RDW-001@x", "rdw-001@3", "entity:", "entity:abc"):
            with self.subTest(text=text):
                self.assertEqual(parse(text), road_store.PointReference(text.strip()))

    def test_a_station_of_the_axis_of_another_road(self) -> None:
        """RF-017-03: el lugar y la cota de la rasante de una pista a la abscisa ``s`` salen de sus estaciones por interpolación lineal (exacta en una recta); fuera de ellas (antes del
        origen o más allá de su longitud), ``None``."""
        stations = np.array([[0.0, 10.0, 20.0, 5.0, 100.0], [10.0, 20.0, 20.0, 5.0, 101.0], [20.0, 30.0, 20.0, 5.0, 103.0]])  # abscisa, x, y, terreno, rasante
        found = road_store.axis_point_at(stations, 15.0)
        self.assertEqual(found, (25.0, 20.0, 102.0))
        self.assertEqual(road_store.axis_point_at(stations, 0.0), (10.0, 20.0, 100.0))
        self.assertEqual(road_store.axis_point_at(stations, 20.0), (30.0, 20.0, 103.0))
        self.assertIsNone(road_store.axis_point_at(stations, 20.0001))
        self.assertIsNone(road_store.axis_point_at(stations, -0.1))

    def test_the_warning_of_a_restored_start(self) -> None:
        """RF-017-05 (a): sobre la final restaurada de una cantera la pista no llega al fondo: la cota mínima alcanzable desde el origen sobre ella y sobre la de explotación (con la
        pendiente transitable y el ancho de la calzada, T19-a) va en el aviso; si llega igual de hondo, no hay aviso."""
        grid = rd.grid_of(2.0)
        pit, final = rd.pit_exploitation(grid), rd.pit_final(grid)
        x, y = absolute(rd.PIT_ORIGIN)
        notice = road_store.start_is_final_notice("Pista del tajo", "des_fin_cantera", grid, final, pit, (x, y), 16.0, 10.5, np.zeros(grid.shape, dtype=bool))
        self.assertIsNotNone(notice)
        self.assertEqual(notice.code, "des.road_start_is_final")
        self.assertEqual((notice.values["entity"], notice.values["surface"]), ("Pista del tajo", "des_fin_cantera"))
        self.assertAlmostEqual(notice.values["z_pit"], rd.PIT_Z_MIN_EXPLOITATION_M, places=6)
        self.assertGreater(notice.values["z_final"], notice.values["z_pit"])
        self.assertIsNone(road_store.start_is_final_notice("Pista del tajo", "des_fin_cantera", grid, pit, pit, (x, y), 16.0, 10.5, np.zeros(grid.shape, dtype=bool)))

    def test_the_warning_of_another_design(self) -> None:
        """RF-017-05 (b): donde la partida difiere en más del espesor mínimo de otro diseño de la versión que no parte de ella, **dentro de la huella de la pista**, el aviso da el área
        (m²), la diferencia máxima (m) y el lugar de la mayor; sin diferencia sobre el umbral, o fuera de la huella, no hay aviso; el que más difiere de varios, el primero en el orden."""
        grid = rd.grid_of(2.0)
        start = np.full(grid.shape, 100.0)
        other = start.copy()
        other[50:60, 80:90] = 103.0   # 100 celdas de 4 m², 3 m
        other[55, 85] = 107.5          # la mayor: 7,5 m
        other[10:12, 10:12] = 120.0    # fuera de la huella
        footprint = np.zeros(grid.shape, dtype=bool)
        footprint[48:62, 78:92] = True
        notices = road_store.other_design_notices("Pista del tajo", grid, footprint, start, {"Relleno": other}, 0.5)
        self.assertEqual(len(notices), 1)
        notice = notices[0]
        self.assertEqual(notice.code, "des.road_other_design_differs")
        self.assertEqual((notice.values["entity"], notice.values["other"]), ("Pista del tajo", "Relleno"))
        self.assertAlmostEqual(notice.values["area"], 100 * 4.0, places=9)
        self.assertAlmostEqual(notice.values["difference"], 7.5, places=9)
        self.assertEqual((notice.values["x"], notice.values["y"]), (float(grid.west + (85 + 0.5) * grid.dx), float(grid.north - (55 + 0.5) * grid.dy)))
        self.assertEqual(road_store.other_design_notices("Pista", grid, footprint, start, {"Relleno": other}, 8.0), ())
        self.assertEqual(road_store.other_design_notices("Pista", grid, np.zeros(grid.shape, dtype=bool), start, {"Relleno": other}, 0.5), ())
        self.assertEqual(road_store.other_design_notices("Pista", grid, footprint, start, {}, 0.5), ())


class DefaultStartTest(unittest.TestCase):
    """``default_start`` sobre una base de mentira (la tabla de datos y la caché de lo obsoleto de SQLite en memoria; el registro de entidades y la cola de la cadena, dados): lo que lee es el
    **nombre** de los datos de explotación vivos y al día, y lo demás lo decide la función."""

    @staticmethod
    def project_with(live: tuple[str, ...], stale: tuple[str, ...] = ()) -> Any:
        """Un proyecto cuya versión ``v1`` tiene los datos ``live`` al día y los ``stale`` obsoletos (con su causa en la caché)."""
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE gb_dataset (uid TEXT, name TEXT, version_uid TEXT, status TEXT)")
        conn.execute("CREATE TABLE gb_stale (item_kind TEXT, item_uid TEXT, cause_kind TEXT, subject_uid TEXT)")
        for name in (*live, *stale):
            conn.execute("INSERT INTO gb_dataset VALUES (?, ?, 'v1', 'current')", (f"uid-{name}", name))
        for name in stale:
            conn.execute("INSERT INTO gb_stale VALUES ('dataset', ?, 'dataset_changed', ?)", (f"uid-{name}", f"uid-{name}"))
        return SimpleNamespace(read=lambda: contextlib.nullcontext(conn))

    def start(self, project: Any, *, tails: tuple[Any, ...] = ()) -> Any:
        version = SimpleNamespace(uid="v1")
        with mock.patch.object(entities, "registry", return_value=SimpleNamespace(records=())), mock.patch.object(entities, "chain_tails", return_value=tails):
            return road_store.default_start(project, version)

    def test_only_one_live_quarry_is_the_default_start_and_several_are_none(self) -> None:
        """RF-017-05, D-3, A-5 de la verificación única (T45; mutante M10: ``default_start`` con varias canteras vivas propone la primera): con **una** cantera de la 014 viva y al día (otra, obsoleta, no
        cuenta) la partida es su superficie de explotación; con **varias** no se elige una por la persona (ninguna partida, aunque haya una cola de cadena que sí lo sería); sin ninguna cantera, la
        última de la cadena si es una sola."""
        tail = SimpleNamespace(code="PLT-001", name="Carga", state=entities.EntityState.CURRENT)
        found = self.start(self.project_with(("des_exp_cantera",), stale=("des_exp_otra",)), tails=(tail,))
        self.assertEqual((found.ref, found.kind, found.name, found.conflict), ("des_exp_cantera", "exploitation", "des_exp_cantera", None))
        self.assertIsNone(self.start(self.project_with(("des_exp_cantera", "des_exp_otra")), tails=(tail,)), "dos canteras vivas: ninguna")
        self.assertIsNone(self.start(self.project_with(("des_exp_cantera", "des_exp_otra"))), "dos canteras vivas y ninguna cola: ninguna")
        found = self.start(self.project_with(()), tails=(tail,))
        self.assertEqual((found.ref, found.kind, found.name), ("entity:PLT-001", "chain_tail", "Carga"))
        self.assertIsNone(self.start(self.project_with(()), tails=(tail, tail)), "dos colas de cadena: ninguna")


if __name__ == "__main__":
    unittest.main()
