# SPDX-License-Identifier: GPL-3.0-or-later
"""Preparar la plataforma: lo que se lee y se rechaza antes de calcular (spec 015, T11; HU-015-3;
RF-015-06, RF-015-07, RF-015-08, RF-015-09; plan 015 §5.2.1, §5.2.2 y §5.3.1; ADR-0030).

Sobre la cantera sintética de la 014 con las capas de plataformas (``tests.support.entity_fixtures``,
T01), con la rejilla gruesa de 2 m (200 × 200 celdas):

- **El camino bueno** (RF-015-06): ``prepare_platform_units`` lee la capa y la geometría elegida (por
  su nombre o su ``fid``), el código ``PLT-001``, la superficie de partida y su rejilla, las máscaras
  de la versión (registradas como entradas) y deja el ``PlatformJob`` (todo lo leído y nada del
  proyecto) y lo que anotará la operación (``OperationStart``); ``prepare_platform`` da solo esto
  último. **No escribe nada.** Las cuentas están hechas a mano: la «Plataforma de carga» (eje de
  200 m, 20 m de ancho, 250 m al 1 %) son 100 columnas por 10 filas de celdas de 2 m, 1.000 celdas y
  4.000 m², con la rasante de 250,01 m (abscisa 1 m) a 251,99 m (199 m).
- **Los rechazos** (RF-015-07, RF-015-08, RF-015-09), cada uno **sin escribir nada** (el contador de
  cambios de la base y los ficheros no se mueven) y nombrando la capa, la entidad, el campo y el
  valor: sin versión activa o no editable (RF-009-21), geometría no válida, campo de la capa o
  parámetro sin valor o fuera de rango, una cota fuera de las del terreno ± 1.000 m, la pendiente
  máxima (D-6), proteger en «en corte y relleno» (RF-015-12), nombre repetido, una superficie de la
  que ya parte otra entidad, un sector sin búsqueda de intocables vigente (solo si lo toca la huella
  o lo que mueve) y la falta de dato en la huella (en la de partida y en la de apoyo, con el área y
  el lugar de la primera celda).
- **Los parámetros de la entidad** (la trampa de la T04): ``set_entity_params`` los escribe como
  filas de la versión, con su origen («capa X, campo Y, entidad Z»), y la operación los lee con
  ``begin_operation`` sin crear ninguno en el proyecto.
"""

from __future__ import annotations

import unittest
from collections.abc import Generator, Iterator
from typing import Any, ClassVar

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import constraints_project as cp
from tests.support import entity_fixtures as efx
from tests.support import quarry_fixtures as qfx
from tests.support import res_fixtures
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.versions_fixtures import change_counter

entity_store = import_geoblender("design.entity_store")
entities = import_geoblender("design.entities")
provenance = import_geoblender("design.provenance")
design_params = import_geoblender("design.params")
model = import_geoblender("design.model")
messages = import_geoblender("design.messages")
platform = import_geoblender("design.platform")
core_params = import_geoblender("core.params")
operations = import_geoblender("core.provenance.operations")
versions_model = import_geoblender("core.versions.model")
res_provenance = import_geoblender("reserves.provenance")
access = import_geoblender("gis.masks.access")
gis = import_geoblender("gis")

DesignError = messages.DesignError
GRID = qfx.grid_of(qfx.COARSE_STEP_M)
"""La rejilla gruesa de la cantera (200 × 200 celdas de 2 m)."""
START = qfx.START_DATASET
LOADING, WORKSHOP, TOWER = "Plataforma de carga", "Plataforma de taller", "Plataforma de la torre"
WITH_AXIS, NO_AXIS = "Explanada con eje", "Explanada sin eje"
USER = "Samuel (IMGA)"
HOLE_DATASET = "gis_dtm_hueco"
"""Un terreno igual al de la cantera con un hueco sin dato de 5 × 4 celdas (80 m²) en la «Plataforma de
carga»: las celdas de centro x de 151 a 159 m e y de 277 a 283 m (locales)."""
HOLE_BOX = (150.0, 276.0, 160.0, 284.0)
HOLE_CELLS, HOLE_AREA_M2 = 20, 80.0
HOLE_FIRST_LOCAL = (151.0, 283.0)
"""El centro de la primera celda del hueco, de norte a sur y de oeste a este (local)."""
BAD_LAYER = "gis_fea_plataformas_mal"
POINTS_LAYER = "gis_fea_puntos"
BAD_NAMES = ("Eje con ancho negativo", "Eje con cota imposible", "Eje sin cota", "Duplicada",
             "Duplicada", "Eje en bajada")
ENTITY_TYPES = ("des.platform", "des.declare_constraints", "des.entity_layer")
LINES = ("ancho", "cota_inicial", "pendiente")


def never(request: Any) -> Any:  # solo declara que se repite sola
    raise AssertionError("las pruebas de preparar no recalculan ni reproducen")


def entity_definitions() -> tuple[Any, ...]:
    """Los tres tipos de las entidades con sus funciones y sus cifras, como los registrará ``bl``."""
    return (*provenance.entity_operation_defs({t: never for t in ENTITY_TYPES},
                                              {t: never for t in ENTITY_TYPES}),
            *provenance.ENTITY_FIGURES)


def line_fields(layer: str = efx.AXES_LAYER, **changes: Any) -> Any:
    """Los campos de una plataforma de una capa de líneas, con su ancho."""
    base: dict[str, Any] = {"layer": layer, "start_level_field": "cota_inicial",
                            "gradient_field": "pendiente", "width_field": "ancho"}
    return model.PlatformFields(**{**base, **changes})


def polygon_fields(*, linked: bool = True) -> Any:
    """Los de una capa de polígonos, con su eje enlazado en la de líneas o sin él."""
    link = {"axis_field": efx.LINK_FIELD, "axis_layer": efx.AXES_LAYER} if linked else {}
    return model.PlatformFields(layer=efx.POLYGONS_LAYER, start_level_field="cota_inicial",
                                gradient_field="pendiente", **link)


def request(name: str = LOADING, **changes: Any) -> Any:
    """Una plataforma de la capa de ejes completa, por el nombre de su geometría, sobre el terreno
    de la cantera, con un alcance de 20 m."""
    base: dict[str, Any] = {"name": name, "fields": line_fields(), "feature": name, "start": START,
                            "edge_angle_deg": 35.0, "reach_m": 20.0}
    return model.PlatformRequest(**{**base, **changes})


def polygon_request(name: str = WITH_AXIS, *, linked: bool = True, **changes: Any) -> Any:
    return request(name, fields=polygon_fields(linked=linked), **changes)


def drive[T](work: Generator[None, None, T]) -> T:
    """Lo que devuelve ``work`` (unidades de preparación) llevado hasta el final."""
    while True:
        try:
            next(work)
        except StopIteration as stop:
            return stop.value  # type: ignore[no-any-return]


def cancel_if_running(handle: Any) -> None:
    """Deja cancelada la operación de la prueba si sigue «en curso»."""
    try:
        handle.cancel("Prueba")
    except Exception as exc:  # noqa: BLE001 - solo se calla «ya no está en curso»
        if getattr(exc, "code", "") != "core.operation_not_running":
            raise


def bad_layer() -> Any:
    """Una capa de ejes con valores que se rechazan: un ancho negativo, una cota de 5.000 m, una sin
    cota y dos geometrías con el mismo nombre; y una pendiente que baja (-3 %). Todos van por el eje
    de la «Plataforma de carga»."""
    path = ((cfx.absolute(efx.AXES[0].path),),)
    return qfx.LayerData(
        BAD_LAYER, "line", (path,) * len(BAD_NAMES), BAD_NAMES,
        {"ancho": (-5.0, 20.0, 20.0, 20.0, 20.0, 20.0),
         "cota_inicial": (250.0, 5000.0, None, 250.0, 250.0, 250.0),  # type: ignore[dict-item]
         "pendiente": (1.0, 1.0, 1.0, 1.0, 1.0, -3.0)})


def points_layer() -> Any:
    """Una capa de puntos: no es una capa de plataformas."""
    return qfx.LayerData(POINTS_LAYER, "point", (((cfx.absolute([(150.0, 150.0)]),),),),
                         ("Punto",), {})


def hole_raster() -> Any:
    """El terreno de la cantera con el hueco de :data:`HOLE_BOX` sin dato."""
    x, y = qfx.local_centers(GRID)
    left, bottom, right, top = HOLE_BOX
    hole = (x > left) & (x < right) & (y > bottom) & (y < top)
    return gis.Raster(GRID, np.where(hole, np.nan, qfx.terrain(GRID)), efx.CRS, efx.VERTICAL)


class PrepareCase(efx.EntityProjectCase):
    """Una copia por clase de la cantera con las capas de plataformas, con lo que declara ``des``
    registrado, tres capas más (con valores que se rechazan, de puntos) y el terreno con un hueco,
    y las máscaras de V01 cargadas."""

    STEP_M = qfx.COARSE_STEP_M
    masks_v1: ClassVar[Any]

    @classmethod
    def definitions(cls) -> tuple[Any, ...]:
        """Los tipos de las entidades que registra la clase, con sus cifras: las funciones de recalcular y
        reproducir no se llaman (:func:`entity_definitions`); una historia que las usa de verdad (T14)
        da las reales."""
        return entity_definitions()

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_definitions((*design_params.DEFINITIONS,
                                          *design_params.QUARRY_DEFINITIONS))
        cls.addClassCleanup(core_params.unregister_definitions, "des")
        core_params.register_definitions(res_provenance.VERIFY_DEFINITIONS)
        cls.addClassCleanup(core_params.unregister_definitions, "res")
        core_params.register_families(design_params.ENTITY_FAMILIES)
        cls.addClassCleanup(core_params.unregister_families, "des")
        cls.enterClassContext(registered(*cls.definitions()))
        for layer in (bad_layer(), points_layer()):
            qfx.write_feature_layer(cls.project, cls.clock, layer)
        cls.clock.advance(minutes=1)
        res_fixtures.write_grids(cls.project, [("hueco", hole_raster())],
                                 message="Terreno de la prueba con un hueco")
        cls.clock.advance(minutes=1)
        cls.masks_v1 = access.load_masks(cls.project, cls.v1.uid)

    def state(self) -> dict[str, Any]:
        """Todo lo que podría escribir la preparación: el contador de cambios de la base (lo sube
        toda transacción que escribe) y, aparte, lo que se vería: operaciones, datos, parámetros y
        los ficheros de ``rasters/``."""
        return {
            "counter": change_counter(self.root),
            "operations": self.query("SELECT uid, status FROM gb_operation ORDER BY rowid"),
            "datasets": self.query("SELECT uid, status, content_sha256 FROM gb_dataset "
                                   "ORDER BY rowid"),
            "parameters": self.query("SELECT key, scope_uid, value FROM gb_parameter "
                                     "ORDER BY rowid"),
            "files": sorted(path.name for path in (self.root / "rasters").iterdir())}

    def prepare(self, asked: Any, *, version: Any = "default", **options: Any) -> Any:
        """:func:`prepare_platform` en V01 con sus máscaras."""
        which = self.v1.uid if version == "default" else version
        return entity_store.prepare_platform(self.project, asked, version=which,
                                             masks=options.pop("masks", self.masks_v1), **options)

    def units(self, asked: Any, **options: Any) -> Any:
        """:func:`prepare_platform_units` en V01 con sus máscaras, hasta el final: la
        :class:`PreparedPlatform`."""
        return drive(entity_store.prepare_platform_units(
            self.project, asked, self.v1, options.pop("masks", self.masks_v1), **options))

    def refused(self, asked: Any, expected: str, **options: Any) -> Any:
        """``asked`` se rechaza con el código ``expected`` y **no escribe nada**; devuelve el error."""
        before = self.state()
        with self.assertRaises(DesignError) as caught:
            self.prepare(asked, **options)
        self.assertEqual(caught.exception.code, expected)
        self.assertEqual(self.state(), before, "el rechazo ha escrito algo")
        return caught.exception

    def names(self, error: Any, **expected: Any) -> None:
        """El rechazo nombra lo que se espera (en sus valores y en su texto)."""
        for key, value in expected.items():
            self.assertEqual(error.values[key], value, key)
            if not isinstance(value, float):  # los decimales salen con coma en el texto
                self.assertIn(str(value), error.text)


# ---------------------------------------------------------------------------------------------
# El camino bueno
# ---------------------------------------------------------------------------------------------


class PreparedPlatformTest(PrepareCase):
    """RF-015-06 (y RF-015-01, RF-015-19): lo que se lee, en la rejilla del proyecto y sin escribir."""

    def test_a_line_platform_is_prepared_without_writing(self) -> None:
        """RF-015-06, RF-015-01: la capa de ejes, la geometría por su nombre y la superficie de
        partida, el código ``PLT-001``, la rejilla y las máscaras de la versión dejan un
        ``PlatformJob`` con todo lo leído (la superficie bit a bit, los campos de la capa como
        parámetros) y la ``OperationStart`` con sus ajustes, entradas (la capa, la partida y las
        máscaras, con sus papeles) y parámetros; el trabajo cuadra con la huella a mano (1.000
        celdas, 4.000 m²; rasante de 250,01 a 251,99 m); nada se escribe."""
        asked = request()
        before = self.state()
        prepared = self.units(asked)
        self.assertEqual(self.state(), before)
        job = prepared.job
        self.assertEqual(prepared.code, "PLT-001")
        self.assertEqual(job.code, "PLT-001")
        self.assertEqual(prepared.fid, efx.axis_fid(LOADING))
        self.assertTrue(job.grid.same_geometry(self.masks_v1.grid))
        self.assertTrue(np.array_equal(job.start, qfx.terrain(GRID)))
        self.assertTrue(np.array_equal(job.cut_allowed, self.masks_v1.cut_allowed()))
        # RF-012-13: el relleno admitido incluye la franja de solo relleno (de x = 20 a 40 m)
        fill = self.masks_v1.fill_allowed() | self.masks_v1.fill_strip()
        self.assertTrue(np.array_equal(job.fill_allowed, fill))
        self.assertTrue((fill & ~self.masks_v1.fill_allowed()).any())
        self.assertEqual(job.geometry.kind, "line")
        self.assertTrue(cp.same_parts(job.geometry.parts, self.read_layer(efx.AXES_LAYER).parts[0]))
        self.assertEqual(dict(job.values), {
            "name": LOADING, "layer": efx.AXES_LAYER, "feature": "1", "start": START,
            "width_m": 20.0, "start_level_m": 250.0, "gradient_pct": 1.0, "mode": "cut",
            "edge_angle_deg": 35.0, "reach_m": 20.0, "mesh_factor": 1.0, "counter_tol_m": 0.1,
            "metric": "exact", "protect": False})
        footprint = prepared.footprint
        self.assertEqual(footprint.cell_count, 1000)
        self.assertEqual(footprint.area_m2, 4000.0)
        levels = footprint.levels[footprint.cells]
        self.assertAlmostEqual(float(levels.min()), 250.01, delta=1e-9)
        self.assertAlmostEqual(float(levels.max()), 251.99, delta=1e-9)
        start = prepared.start
        self.assertEqual((start.op_type, start.name, start.version_code),
                         ("des.platform", LOADING, self.v1.code))
        self.assertEqual(dict(start.settings), provenance.platform_settings(asked, "PLT-001"))
        self.assertEqual(start.params, provenance.platform_params("PLT-001", asked))
        self.assertEqual([(use.item, str(use.role)) for use in start.inputs[:2]],
                         [(efx.AXES_LAYER, "entity_layer"), (START, "surface")])
        self.assertEqual(start.inputs[2:], self.masks_v1.uses())
        self.assertEqual(prepared.start_surface, START)
        self.assertIsNone(prepared.support_surface)
        self.assertEqual(sorted(prepared.common), sorted(provenance.PLATFORM_COMMON_PARAMS))

    def test_prepare_platform_gives_the_operation_start(self) -> None:
        """RF-015-02 (plan 015 §5.3.1): ``prepare_platform`` devuelve la ``OperationStart`` que
        da la preparación entera, y sin pasar las máscaras las carga (están al día)."""
        asked = request()
        start = self.prepare(asked)
        prepared = self.units(asked)
        for name in ("op_type", "name", "version_uid", "version_code", "settings", "inputs",
                     "params", "seen", "supersedes", "parts"):
            self.assertEqual(getattr(start, name), getattr(prepared.start, name), name)
        loaded = entity_store.prepare_platform(self.project, asked, version=self.v1.code)
        self.assertEqual(loaded.inputs, start.inputs)

    def test_a_polygon_with_its_linked_axis(self) -> None:
        """RF-015-19, RF-015-06: un polígono lleva, sin ancho, su geometría, las partes de la línea
        enlazada por su campo ``eje`` y su nombre; sus 80 × 50 m son 1.000 celdas de 2 m."""
        prepared = self.units(polygon_request(WITH_AXIS))
        geometry = prepared.job.geometry
        self.assertEqual(geometry.kind, "polygon")
        self.assertEqual(geometry.axis_name, "Eje de la explanada")
        axes = self.read_layer(efx.AXES_LAYER)
        self.assertTrue(cp.same_parts(geometry.axis_parts,
                                      axes.parts[efx.axis_fid("Eje de la explanada") - 1]))
        self.assertNotIn("width_m", prepared.job.values)
        self.assertEqual(prepared.job.values["start_level_m"], 235.0)
        self.assertEqual(prepared.job.values["gradient_pct"], 1.5)
        self.assertEqual(prepared.footprint.cell_count, 1000)
        self.assertEqual(prepared.start.inputs[:3][1].role, "entity_axis_layer")

    def test_a_polygon_without_an_axis_uses_the_principal_one(self) -> None:
        """RF-015-19: sin enlace (el campo ``eje`` vacío, o sin ese campo en la petición), el
        polígono no lleva eje y la huella avisa del eje principal."""
        for linked in (False, True):
            with self.subTest(linked=linked):
                prepared = self.units(polygon_request(NO_AXIS, linked=linked))
                self.assertIsNone(prepared.job.geometry.axis_parts)
                self.assertEqual([n.code for n in prepared.footprint.notices],
                                 ["des.platform_axis_principal"])
                self.assertEqual(prepared.job.values["start_level_m"], 240.0)

    def test_the_feature_by_name_or_by_fid(self) -> None:
        """RF-015-01: la geometría se elige por su nombre o por su ``fid`` (como texto) y da la misma;
        el parámetro ``feature`` que se escribirá es el ``fid``."""
        by_name = self.units(request(TOWER))
        by_fid = self.units(request(TOWER, feature=str(efx.axis_fid(TOWER))))
        self.assertEqual((by_name.fid, by_fid.fid), (3, 3))
        self.assertTrue(cp.same_parts(by_name.job.geometry.parts, by_fid.job.geometry.parts))
        self.assertEqual(by_name.job.values["feature"], "3")
        self.assertEqual({row.param.value: row.value for row in by_fid.rows}["feature"], "3")

    def test_the_defaults_and_the_chosen_values(self) -> None:
        """RF-015-08 (plan §5.2.2): lo que no se pide toma el valor por defecto de su parámetro (D-5,
        D-7, D-8 y D-22: «en corte», factor 1,0, tolerancia 0,1 m, exacta; D-4: no protege) y lo que se
        pide, el suyo (más la superficie de apoyo, la pendiente máxima y el resguardo)."""
        plain = self.units(request()).job.values
        chosen = self.units(request(
            mode="cut_fill", mesh_factor=0.5, counter_tol_m=0.2, metric="chamfer5",
            max_slope_pct=2.0, protect=False, guard_m=3.0, support=START)).job.values
        self.assertEqual((plain["mode"], plain["mesh_factor"], plain["counter_tol_m"],
                          plain["metric"], plain["protect"]), ("cut", 1.0, 0.1, "exact", False))
        self.assertEqual((chosen["mode"], chosen["mesh_factor"], chosen["counter_tol_m"],
                          chosen["metric"], chosen["max_slope_pct"], chosen["guard_m"],
                          chosen["support"]), ("cut_fill", 0.5, 0.2, "chamfer5", 2.0, 3.0, START))
        for absent in ("support", "max_slope_pct", "guard_m", "reason"):
            self.assertNotIn(absent, plain)

    def test_the_support_surface_is_an_input_of_the_operation(self) -> None:
        """RF-015-04, RF-015-15: la superficie de apoyo de la petición se lee, se comprueba y es una
        entrada ``supported_on`` de la operación (resuelta) y un parámetro que lee."""
        asked = request(support=START)
        prepared = self.units(asked)
        self.assertEqual(prepared.support_surface, START)
        self.assertIn((START, "supported_on"),
                      [(use.item, str(use.role)) for use in prepared.start.inputs])
        self.assertIn("des.platform.plt_001.support", prepared.start.params)

    def test_a_surface_with_a_hole_outside_the_footprint_is_fine(self) -> None:
        """RF-015-09: lo que falta de dato fuera de la huella no se rechaza (la «Plataforma de taller»
        queda lejos del hueco)."""
        prepared = self.units(request(WORKSHOP, start=HOLE_DATASET))
        self.assertEqual(prepared.start_surface, HOLE_DATASET)
        window = prepared.footprint.window
        self.assertFalse(np.isnan(prepared.job.start[window][prepared.footprint.cells]).any())
        self.assertTrue(np.isnan(prepared.job.start).any())

    def test_the_rows_of_the_entity_with_their_origin(self) -> None:
        """RF-015-01, RF-015-02, RF-008-01: las filas que escribirá ``set_entity_params`` son todas las
        de la plataforma que tienen valor, sin las opcionales que no se piden: los campos de la capa
        con su origen «capa X, campo Y, entidad Z» (la cota inicial, la pendiente y el ancho), lo que
        eligió la persona con el del diálogo y lo que no pidió, el valor por defecto con la
        procedencia de su definición; todas ADOPTADO, de la clase «persona» salvo las de un valor por
        defecto («algoritmo»)."""
        prepared = self.units(request())
        rows = {row.param.value: row for row in prepared.rows}
        self.assertEqual(sorted(rows), sorted(
            ("name", "layer", "feature", "start", "width_m", "start_level_m", "gradient_pct",
             "mode", "edge_angle_deg", "reach_m", "mesh_factor", "counter_tol_m", "metric",
             "protect")))
        for row in prepared.rows:
            self.assertEqual(row.key, design_params.entity_key("PLT-001", row.param))
        for param, field in (("width_m", "ancho"), ("start_level_m", "cota_inicial"),
                             ("gradient_pct", "pendiente")):
            self.assertEqual(rows[param].source,
                             f"capa «{efx.AXES_LAYER}», campo «{field}», entidad «{LOADING}»")
            self.assertEqual(rows[param].source_kind, "person")
        self.assertEqual(rows["width_m"].value, 20.0)
        self.assertEqual(rows["start"].value, START)
        for param in ("name", "layer", "feature", "start", "edge_angle_deg", "reach_m"):
            self.assertIn(LOADING, rows[param].source)
            self.assertEqual(rows[param].source_kind, "person")
        for param in ("mode", "mesh_factor", "counter_tol_m", "metric", "protect"):
            self.assertEqual(rows[param].source_kind, "algorithm", param)
            self.assertEqual(rows[param].source,
                             design_params.PLATFORM_PARAMS[param].source, param)
        for row in prepared.rows:
            self.assertTrue(row.reason.strip(), row.key)

    def test_the_values_corrected_in_the_dialog_win_over_the_layer(self) -> None:
        """RF-015-01, RF-015-19, RF-008-01 (T15; plan §5.2.1: «el diálogo deja corregirlos»): la cota inicial,
        la pendiente y el ancho que la persona corrige en el diálogo (``start_level_m``, ``gradient_pct`` y
        ``width_m`` de la petición) son los de la entidad, con el origen del diálogo, y la capa no se lee
        para ellos; un valor igual al de la capa conserva su origen «capa X, campo Y, entidad Z»; lo que no se
        corrige sale de la capa como siempre; la capa no se toca."""
        before = self.state()
        plain = {row.param.value: row for row in self.units(request()).rows}
        corrected = self.units(request(start_level_m=249.0, gradient_pct=0.5, width_m=20.0))
        rows = {row.param.value: row for row in corrected.rows}
        values = corrected.job.values
        self.assertEqual((values["start_level_m"], values["gradient_pct"], values["width_m"]),
                         (249.0, 0.5, 20.0))
        dialog = f"diálogo de «Plataforma…», entidad «{LOADING}»"
        for param in ("start_level_m", "gradient_pct"):
            self.assertEqual((rows[param].source, rows[param].source_kind), (dialog, "person"))
            self.assertIn(LOADING, rows[param].reason)
            self.assertNotEqual(rows[param].reason, plain[param].reason)
        self.assertEqual((rows["start_level_m"].value, rows["gradient_pct"].value), (249.0, 0.5))
        self.assertEqual(rows["width_m"], plain["width_m"], "20 m es lo que dice la capa: su origen")
        self.assertEqual(rows["width_m"].source,
                         f"capa «{efx.AXES_LAYER}», campo «ancho», entidad «{LOADING}»")
        # la rasante con los valores corregidos (249 m al 0,5 %: de 249,005 a 249,995 m), no con los de la capa
        levels = corrected.footprint.levels[corrected.footprint.cells]
        self.assertAlmostEqual(float(levels.min()), 249.005, delta=1e-9)
        self.assertAlmostEqual(float(levels.max()), 249.995, delta=1e-9)
        self.assertEqual(self.state(), before)

    def test_a_value_the_layer_does_not_have_can_be_typed_in_the_dialog(self) -> None:
        """RF-015-08, RF-015-19 (T15): la capa no da la cota de «Eje sin cota»: sin más, se rechaza
        (``des.entity_field_value``, sin elegir ninguna por la persona); con la que escribe ella en el
        diálogo, se prepara, con el origen del diálogo. Un nombre de campo que la capa no tiene se rechaza
        igual, con o sin valor escrito."""
        asked = request("Eje sin cota", fields=line_fields(BAD_LAYER))
        self.refused(asked, "des.entity_field_value")
        prepared = self.units(request("Eje sin cota", fields=line_fields(BAD_LAYER),
                                      start_level_m=250.0))
        rows = {row.param.value: row for row in prepared.rows}
        self.assertEqual(rows["start_level_m"].value, 250.0)
        self.assertIn("diálogo", rows["start_level_m"].source)
        self.assertIn("capa", rows["gradient_pct"].source, "la pendiente sí sale de la capa")
        error = self.refused(request(fields=line_fields(gradient_field="inclinacion"),
                                     gradient_pct=1.0), "des.quarry_layer_field")
        self.assertEqual(error.values["value"], "inclinacion")

    def test_the_dialog_proposes_the_values_of_the_layer_without_refusing_what_is_missing(self) -> None:
        """RF-015-19 (T15): ``layer_values`` da la cota inicial, la pendiente y el ancho de la geometría
        elegida de la capa (por su nombre o su ``fid``), sin escribir nada; de un polígono, sin ancho; el que
        la geometría no tiene (sin valor) sale ``None`` en lugar de rechazarse (lo rechaza el cálculo); una
        geometría que la capa no tiene o un campo que no es suyo, sí."""
        param = design_params.PlatformParam
        before = self.state()
        found = entity_store.layer_values(self.project, line_fields(), LOADING)
        self.assertEqual(found, {param.START_LEVEL: 250.0, param.GRADIENT: 1.0, param.WIDTH: 20.0})
        self.assertEqual(entity_store.layer_values(self.project, line_fields(), "1"), found)
        polygon = entity_store.layer_values(self.project, polygon_fields(), WITH_AXIS)
        self.assertEqual(polygon, {param.START_LEVEL: 235.0, param.GRADIENT: 1.5, param.WIDTH: None})
        missing = entity_store.layer_values(self.project, line_fields(BAD_LAYER), "Eje sin cota")
        self.assertEqual((missing[param.START_LEVEL], missing[param.WIDTH]), (None, 20.0))
        for feature, code in (("No existe", "des.entity_feature_unknown"),
                              ("Duplicada", "des.entity_feature_ambiguous")):
            with self.assertRaises(DesignError) as caught:
                entity_store.layer_values(self.project, line_fields(BAD_LAYER), feature)
            self.assertEqual(caught.exception.code, code)
        with self.assertRaises(DesignError) as caught:
            entity_store.layer_values(self.project, line_fields(width_field="ancho_malo"), LOADING)
        self.assertEqual(caught.exception.code, "des.quarry_layer_field")
        self.assertEqual(self.state(), before)

    def test_a_corrected_value_out_of_range_is_refused_and_a_width_of_a_polygon_is_a_program_error(
            self) -> None:
        """RF-015-08 (T15): un valor corregido fuera de rango se rechaza como el de la capa
        (``des.entity_param_range``); un ancho para una capa de polígonos no es del diálogo: un error del
        programa (``ValueError``) al formar la petición."""
        error = self.refused(request(width_m=-5.0), "des.entity_param_range")
        self.assertEqual(error.field, "des.platform.plt_001.width_m")
        with self.assertRaises(ValueError):
            polygon_request(width_m=20.0)
        with self.assertRaises(TypeError):
            request(start_level_m="250")


# ---------------------------------------------------------------------------------------------
# Los rechazos (sin escribir nada)
# ---------------------------------------------------------------------------------------------


class VersionRefusalTest(PrepareCase):
    """RF-009-21, RF-015-02: sin versión activa o en una que no se edita, no se prepara nada."""

    def test_needs_an_editable_version(self) -> None:
        """Sin versión activa, ``core.version_required``; una que no existe, ``core.version_unknown``;
        en una SUPERADO, ``core.version_not_editable``: ninguna escribe nada."""
        before = self.state()
        for version, code in ((None, "core.version_required"), ("", "core.version_required"),
                              ("V99", "core.version_unknown")):
            with self.subTest(version=version):
                with self.assertRaises(versions_model.VersionError) as caught:
                    self.prepare(request(), version=version)
                self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.state(), before)
        with self.project.write_transaction() as conn:
            conn.execute("UPDATE gb_version SET status = 'VIGENTE' WHERE uid = ?", (self.v2.uid,))
            conn.execute("UPDATE gb_version SET status = 'SUPERADO', reason_closed = ? "
                         "WHERE uid = ?", ("Prueba de la 015", self.v2.uid))
        closed = self.state()
        with self.assertRaises(versions_model.VersionError) as caught:
            self.prepare(request(), version=self.v2.uid)
        self.assertEqual(caught.exception.code, "core.version_not_editable")
        self.assertEqual(self.state(), closed)
        with self.assertRaises(versions_model.VersionError) as caught:  # también por unidades
            drive(entity_store.prepare_platform_units(self.project, request(), self.v2,
                                                      self.masks_v1))
        self.assertEqual(caught.exception.code, "core.version_not_editable")


class GeometryRefusalTest(PrepareCase):
    """RF-015-08: una geometría que no es válida se rechaza con la capa, la entidad y lo que le
    pasa (los defectos del margen este de la cantera, T01)."""

    def test_an_invalid_geometry(self) -> None:
        """Un eje que se corta, cerrado o de longitud cero, un polígono que se corta, sin área o sin
        celdas y un eje enlazado que no cruza su polígono: cada uno con su código, la capa y la
        entidad nombradas."""
        cases = (
            (request("Eje que se corta"), "des.platform_self_intersects", efx.AXES_LAYER),
            (request("Eje cerrado"), "des.platform_axis_closed", efx.AXES_LAYER),
            (request("Eje de longitud cero"), "des.platform_axis_length_zero", efx.AXES_LAYER),
            (polygon_request("Polígono que se corta", linked=False),
             "des.platform_self_intersects", efx.POLYGONS_LAYER),
            (polygon_request("Polígono sin área", linked=False), "des.platform_area_zero",
             efx.POLYGONS_LAYER),
            (polygon_request("Polígono sin celdas", linked=False), "des.platform_no_cells",
             efx.POLYGONS_LAYER),
            (polygon_request("Explanada con eje que no la cruza"),
             "des.platform_axis_not_crossing", efx.POLYGONS_LAYER))
        for asked, code, layer in cases:
            with self.subTest(entity=asked.name):
                error = self.refused(asked, code)
                self.names(error, layer=layer, entity=asked.name)

    def test_a_layer_that_is_not_lines_or_polygons(self) -> None:
        """RF-015-08, RF-015-19: una capa de puntos no es una capa de plataformas."""
        asked = request("Punto", fields=line_fields(POINTS_LAYER, width_field=None))
        error = self.refused(asked, "des.platform_layer_kind")
        self.assertEqual(error.values["layer"], POINTS_LAYER)
        self.assertIn("puntos", error.text)

    def test_a_feature_that_the_layer_does_not_have_or_has_twice(self) -> None:
        """RF-015-01, RF-015-08: una geometría que la capa no tiene (por nombre o por ``fid``) o con el
        nombre repetido (hay que elegirla por su ``fid``)."""
        for feature in ("No existe", "99"):
            with self.subTest(feature=feature):
                error = self.refused(request(feature=feature), "des.entity_feature_unknown")
                self.names(error, layer=efx.AXES_LAYER, value=feature)
        asked = request("Una duplicada", fields=line_fields(BAD_LAYER), feature="Duplicada")
        error = self.refused(asked, "des.entity_feature_ambiguous")
        self.names(error, layer=BAD_LAYER, value="Duplicada", fids="4, 5")
        chosen = self.units(request("Una duplicada", fields=line_fields(BAD_LAYER), feature="4"))
        self.assertEqual(chosen.fid, 4)

    def test_the_axis_of_a_polygon_is_a_line_of_its_axis_layer(self) -> None:
        """RF-015-19: la capa de ejes de un polígono es de líneas (``des.corridor_not_lines``) y la
        línea que enlaza su campo ``eje`` está en ella (``des.entity_feature_unknown``, con la capa
        de ejes y el número): el enlace de «Explanada con eje» con otra capa."""
        def with_axes(layer: str, name: str) -> Any:
            return request(name, fields=model.PlatformFields(
                layer=efx.POLYGONS_LAYER, start_level_field="cota_inicial",
                gradient_field="pendiente", axis_field=efx.LINK_FIELD, axis_layer=layer))

        error = self.refused(with_axes(POINTS_LAYER, WITH_AXIS), "des.corridor_not_lines")
        self.assertEqual(error.values["layer"], POINTS_LAYER)
        asked = with_axes(BAD_LAYER, "Explanada con eje que no la cruza")  # su eje es la línea 9
        error = self.refused(asked, "des.entity_feature_unknown")
        self.names(error, layer=BAD_LAYER, value=efx.axis_fid("Eje corto"))


class FieldRefusalTest(PrepareCase):
    """RF-015-08: lo que falta o sale de rango, sin elegir ningún valor por la persona."""

    def test_a_layer_field_without_value_or_that_does_not_exist(self) -> None:
        """Un eje sin ancho o sin cota inicial en su capa, o un campo que la capa no tiene: la capa,
        la entidad y el campo (con el ``—`` del valor que falta)."""
        error = self.refused(request("Eje sin ancho"), "des.entity_field_value")
        self.names(error, layer=efx.AXES_LAYER, entity="Eje sin ancho")
        self.assertEqual((error.field, error.value), ("ancho", "—"))
        asked = request("Eje sin cota", fields=line_fields(BAD_LAYER))
        error = self.refused(asked, "des.entity_field_value")
        self.assertEqual(error.field, "cota_inicial")
        self.names(error, layer=BAD_LAYER, entity="Eje sin cota")
        error = self.refused(request(fields=line_fields(width_field="ancho_malo")),
                             "des.quarry_layer_field")
        self.assertEqual(error.values["value"], "ancho_malo")
        self.assertEqual(error.values["layer"], efx.AXES_LAYER)

    def test_a_parameter_without_value_and_without_default(self) -> None:
        """El ángulo de borde y el alcance no tienen valor por defecto (D-7, D-20): sin ellos, se
        rechaza con la capa, la entidad y la clave del campo, y no se elige ninguno; tampoco un
        resguardo que falta a quien protege (D-19)."""
        for changes, field in (({"edge_angle_deg": None}, "edge_angle_deg"),
                               ({"reach_m": None}, "reach_m"),
                               ({"protect": True}, "guard_m")):
            with self.subTest(changes=changes):
                error = self.refused(request(**changes), "des.entity_param_missing")
                self.assertEqual(error.field, f"des.platform.plt_001.{field}")
                self.names(error, layer=efx.AXES_LAYER, entity=LOADING)

    def test_a_value_out_of_range(self) -> None:
        """Un ancho negativo (de la capa), un alcance de cero o de más de 10.000 m, un ángulo de 90°,
        un factor de malla de 0, una tolerancia negativa y una pendiente máxima de 0 %: el campo y el
        valor, con la capa y la entidad."""
        cases = (
            (request("Eje con ancho negativo", fields=line_fields(BAD_LAYER)), "width_m", -5.0),
            (request(reach_m=0.0), "reach_m", 0.0),
            (request(reach_m=10000.5), "reach_m", 10000.5),
            (request(edge_angle_deg=90.0), "edge_angle_deg", 90.0),
            (request(mesh_factor=0.0), "mesh_factor", 0.0),
            (request(counter_tol_m=-0.5), "counter_tol_m", -0.5),
            (request(max_slope_pct=0.0), "max_slope_pct", 0.0))
        for asked, field, value in cases:
            with self.subTest(field=field, value=value):
                error = self.refused(asked, "des.entity_param_range")
                self.assertEqual(error.field, f"des.platform.plt_001.{field}")
                self.assertEqual(error.value, value)
                self.names(error, layer=asked.fields.layer, entity=asked.name)

    def test_a_level_outside_the_terrain_plus_or_minus_1000_m(self) -> None:
        """RF-015-08: una cota inicial de 5.000 m (el terreno va de 180,15625 a 307,84375 m)."""
        asked = request("Eje con cota imposible", fields=line_fields(BAD_LAYER))
        error = self.refused(asked, "des.platform_level_range")
        self.assertEqual((error.field, error.value), ("cota_inicial", 5000.0))
        self.names(error, layer=BAD_LAYER, entity="Eje con cota imposible")

    def test_a_gradient_over_the_maximum_is_a_ramp(self) -> None:
        """RF-015-08 (D-6): con una pendiente máxima fijada, la rasante que la pasa se rechaza (es
        una rampa); igual a ella, no."""
        error = self.refused(request(max_slope_pct=0.5), "des.platform_max_slope")
        self.assertEqual((error.field, error.value), ("pendiente", 1.0))
        self.names(error, layer=efx.AXES_LAYER, entity=LOADING, maximum=0.5)
        self.assertEqual(self.units(request(max_slope_pct=1.0)).job.values["max_slope_pct"], 1.0)
        down = request("Eje en bajada", fields=line_fields(BAD_LAYER), max_slope_pct=2.0)
        error = self.refused(down, "des.platform_max_slope")  # baja un 3 %: cuenta su valor absoluto
        self.assertEqual(error.value, -3.0)
        steeper = request("Eje en bajada", fields=line_fields(BAD_LAYER), max_slope_pct=3.0)
        self.assertEqual(self.units(steeper).job.values["gradient_pct"], -3.0)

    def test_protecting_in_cut_and_fill_is_refused(self) -> None:
        """RF-015-12: una plataforma «en corte y relleno» rellena su propia huella y no puede
        declararla «sin relleno»; «en corte», sí."""
        error = self.refused(request(mode="cut_fill", protect=True, guard_m=4.0),
                             "des.platform_protect_cut_fill")
        self.assertEqual(error.field, "des.platform.plt_001.mode")
        self.names(error, layer=efx.AXES_LAYER, entity=LOADING)
        prepared = self.units(request(mode="cut", protect=True, guard_m=4.0))
        self.assertEqual((prepared.job.values["protect"], prepared.job.values["guard_m"]),
                         (True, 4.0))

    def test_a_surface_that_does_not_exist(self) -> None:
        """RF-015-09: una superficie de partida que no existe es ``gis.dataset_unknown`` (nombra la
        superficie), sin escribir nada."""
        before = self.state()
        with self.assertRaises(import_geoblender("gis.messages").GisError) as caught:
            self.prepare(request(start="gis_dtm_no_existe"))
        self.assertEqual(caught.exception.code, "gis.dataset_unknown")
        self.assertEqual(self.state(), before)


class NoDataRefusalTest(PrepareCase):
    """RF-015-09: la falta de dato en la huella se rechaza con la entidad, la superficie y el área
    sin dato con su lugar."""

    def test_no_data_in_the_footprint_of_the_start_surface(self) -> None:
        """El hueco de 5 × 4 celdas de 2 m (80 m²) cae dentro de la huella de la «Plataforma de
        carga»: se nombra la entidad, la superficie de partida, 80 m² y el centro absoluto de la
        primera celda (de norte a sur y de oeste a este: x = 151 m, y = 283 m locales)."""
        error = self.refused(request(start=HOLE_DATASET), "des.entity_nodata")
        x, y = (cfx.BASE[0] + HOLE_FIRST_LOCAL[0], cfx.BASE[1] + HOLE_FIRST_LOCAL[1])
        self.assertEqual((error.values["area"], error.values["x"], error.values["y"]),
                         (HOLE_AREA_M2, x, y))
        self.names(error, entity=LOADING, surface=HOLE_DATASET)
        self.assertEqual(error.field, "des.platform.plt_001.start")
        self.assertEqual(error.values["role"], "partida")
        self.assertIn("80 m²", error.text)

    def test_no_data_in_the_footprint_of_the_support_surface(self) -> None:
        """RF-015-09: lo mismo con la superficie de apoyo (el campo es su parámetro)."""
        error = self.refused(request(support=HOLE_DATASET), "des.entity_nodata")
        self.assertEqual(error.field, "des.platform.plt_001.support")
        self.names(error, entity=LOADING, surface=HOLE_DATASET)
        self.assertEqual(error.values["area"], HOLE_AREA_M2)
        self.assertEqual(error.values["role"], "apoyo")


class ChainRefusalTest(PrepareCase):
    """RF-015-01, RF-015-04: el nombre es único en la versión y de cada superficie parte como mucho
    una entidad; con una plataforma ya en la versión (sus parámetros, sin calcular)."""

    existing: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.existing = drive(entity_store.prepare_platform_units(
            cls.project, request(), cls.v1, cls.masks_v1))
        cls.clock.advance(minutes=1)
        entity_store.set_entity_params(cls.project, cls.existing.rows, version=cls.v1.uid,
                                       decided_by=USER)
        cls.clock.advance(minutes=1)

    def test_the_name_is_unique_in_the_version(self) -> None:
        """RF-015-01: el nombre de una entidad que ya está (aunque no esté calculada) se rechaza
        con la entidad que lo tiene; el mismo nombre en otra capitalización o con otra puntuación
        que da el mismo dato también."""
        error = self.refused(request(LOADING, start=HOLE_DATASET), "des.entity_name_repeated")
        self.names(error, value=LOADING, other=LOADING, version=self.v1.code)
        error = self.refused(request("plataforma de carga", feature=LOADING, start=HOLE_DATASET),
                             "des.entity_name_repeated")
        self.assertEqual(error.values["other"], LOADING)

    def test_a_surface_that_another_entity_already_starts_from(self) -> None:
        """RF-015-04: de la superficie de la que ya parte «Plataforma de carga» no parte otra; el
        rechazo nombra la que ya parte y la superficie. Otra superficie está libre y la entidad
        nueva es la ``PLT-002``."""
        error = self.refused(request(WORKSHOP), "des.entity_start_taken")
        self.names(error, entity=WORKSHOP, other=LOADING, value=START)
        self.assertEqual(error.field, "des.platform.plt_002.start")
        free = self.units(request(WORKSHOP, start=HOLE_DATASET))
        self.assertEqual(free.code, "PLT-002")

    def test_the_same_entity_prepared_again_does_not_clash_with_itself(self) -> None:
        """RF-015-04: con su código (una entidad que ya está en la versión: recalcularla o calcular la
        que dejó «Traer las entidades de…»), el nombre y la partida son los suyos y no chocan."""
        again = self.units(request(), code="PLT-001")
        self.assertEqual(again.code, "PLT-001")

    def test_a_start_that_is_the_surface_of_an_entity_not_calculated(self) -> None:
        """RF-015-04: partir de la superficie de una entidad (``entity:<código>``) que no está
        calculada, no existe o se descartó no tiene superficie que leer: se rechaza con la clave de
        su campo y el valor."""
        for ref in ("entity:PLT-001", "entity:PLT-009"):
            with self.subTest(ref=ref):
                error = self.refused(request(WORKSHOP, start=ref), "des.entity_start_unknown")
                self.assertEqual(error.field, "des.platform.plt_002.start")
                self.names(error, entity=WORKSHOP, value=ref, version=self.v1.code)

    def test_a_chain_that_loops_back_is_refused(self) -> None:
        """RF-015-04: una entidad que parte de su propia superficie cierra un ciclo."""
        error = self.refused(request(start="entity:PLT-001"), "des.entity_chain_cycle",
                             code="PLT-001")
        self.assertIn(LOADING, error.text)


class PendingSectorTest(PrepareCase):
    """RF-015-07: un sector sin búsqueda de intocables vigente rechaza el cálculo solo si lo toca la
    huella o una celda que se mueve."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        with cls.project.write_transaction() as conn:  # el «Sector oeste» (x de 20 a 190 m)
            conn.execute("DELETE FROM core_untouchable_search WHERE sector_code = 'sector_1'")

    def test_the_footprint_in_a_pending_sector(self) -> None:
        """La «Plataforma de carga» (x de 110 a 310 m) está en los dos sectores, y el del oeste está
        pendiente: se rechaza nombrándolo y con la orden que lo busca."""
        error = self.refused(request(), "des.sector_pending")
        self.assertIn("Sector oeste", error.text)
        self.assertIn("Buscar elementos intocables por sector", error.text)
        self.assertEqual(error.values["codes"], "sector_1")

    def test_a_platform_that_does_not_touch_it_is_prepared(self) -> None:
        """La «Plataforma de la torre» (x de 290 a 310 m) y lo que mueve (20 m de alcance) quedan en el
        sector este: no pide la búsqueda del oeste."""
        prepared = self.units(request(TOWER))
        self.assertEqual(prepared.code, "PLT-001")

    def test_a_cell_that_the_edge_moves_in_a_pending_sector(self) -> None:
        """RF-015-07: la huella de la torre sigue en el sector este, pero con 110 m de alcance (a 100 m
        del sector del oeste) el borde puede mover celdas suyas: se rechaza; con 90 m, no."""
        error = self.refused(request(TOWER, reach_m=110.0), "des.sector_pending")
        self.assertIn("Sector oeste", error.text)
        self.assertEqual(self.units(request(TOWER, reach_m=90.0)).code, "PLT-001")


# ---------------------------------------------------------------------------------------------
# Los parámetros de la entidad y la operación
# ---------------------------------------------------------------------------------------------


class EntityParamsCase(PrepareCase):
    """La trampa de la T04: ``begin_operation`` lee cada parámetro de la entidad **de la versión si
    tiene su fila y, si no, del proyecto** (donde antes ha dejado, para cada clave que lee, una fila
    «sin confirmar» con el valor por defecto de su definición, o sin valor): una entidad sin sus filas
    de versión se calcularía con valores sin dueño. ``set_entity_params`` las escribe todas antes.
    Cada prueba escribe las filas de una entidad, así que cada una va en su clase (su copia del
    proyecto)."""

    def project_rows(self) -> dict[str, tuple[Any, bool]]:
        """Las filas de ámbito ``project`` de las plataformas: clave → (valor guardado, si está «sin
        confirmar»)."""
        return {key: (value, bool(unconfirmed)) for key, value, unconfirmed in self.query(
            "SELECT key, value, unconfirmed FROM gb_parameter WHERE key LIKE 'des.platform.%' "
            "AND scope = 'project'")}

    def version_rows(self) -> list[str]:
        """Las claves de las filas de ámbito ``version`` de las plataformas."""
        return [key for (key,) in self.query(
            "SELECT key FROM gb_parameter WHERE key LIKE 'des.platform.%' AND scope = 'version' "
            "ORDER BY key")]


class WrittenRowsTest(EntityParamsCase):
    def test_the_rows_are_version_parameters_and_the_008_reads_them_there(self) -> None:
        """RF-015-01, RF-015-02, RF-008-01, RF-009-29: ``set_entity_params`` escribe una fila de la
        versión por parámetro (y ninguna en el proyecto), ADOPTADO, con su origen, su decisor y su
        motivo; el registro ve la entidad «sin calcular»; ``begin_operation`` lee **todos** los de la
        entidad de la versión, con el valor de su fila; la capa de origen no cambia; una segunda
        entidad es la ``PLT-002``."""
        asked = request()
        prepared = self.units(asked)
        layer_before = self.query("SELECT content_sha256 FROM gb_dataset WHERE name = ?",
                                  efx.AXES_LAYER)
        self.assertEqual((self.version_rows(), self.project_rows()), ([], {}))
        self.clock.advance(minutes=1)
        written = entity_store.set_entity_params(self.project, prepared.rows, version=self.v1.code,
                                                 decided_by=USER)
        self.assertEqual([record.key for record in written], [row.key for row in prepared.rows])
        store = core_params.ParameterStore(self.project)
        for row in prepared.rows:
            record = store.get(row.key, version=self.v1.uid)
            self.assertIsNotNone(record, row.key)
            self.assertEqual((record.scope, record.scope_uid), ("version", self.v1.uid))
            self.assertEqual((record.value, str(record.kind), record.decided_by),
                             (row.value, "ADOPTADO", USER), row.key)
            self.assertEqual((record.source, str(record.source_kind)),
                             (row.source, row.source_kind), row.key)
            self.assertEqual(record.reason, row.reason)
            self.assertFalse(record.unconfirmed, row.key)
        self.assertEqual(self.version_rows(), sorted(row.key for row in prepared.rows))
        self.assertEqual(self.project_rows(), {})
        registry = entities.registry(self.project, self.v1.uid)
        entry = registry.get("PLT-001")
        self.assertEqual((entry.record.name, entry.record.start, str(entry.record.state)),
                         (LOADING, START, "uncalculated"))

        handle = prepared.start.begin(self.project)
        self.addCleanup(cancel_if_running, handle)
        self.assertEqual([item.key for item in handle.params], list(prepared.start.params))
        by_key = {row.key: row.value for row in prepared.rows}
        for item in handle.params:
            if item.key.startswith("des.platform."):
                self.assertEqual((item.scope, item.value), ("version", by_key[item.key]), item.key)
            else:
                self.assertEqual(item.scope, "project", item.key)
        # Lo que deja ``begin_operation`` en el proyecto, para cada clave que lee, es un valor por
        # defecto «sin confirmar» (``ensure_default``) que la operación no lee: la fila de la
        # versión manda. No son entidades: el registro solo cuenta las de la versión.
        entity_keys = {item.key for item in handle.params if item.key.startswith("des.platform.")}
        placeholders = self.project_rows()
        self.assertEqual(set(placeholders), entity_keys)
        self.assertTrue(all(unconfirmed for _value, unconfirmed in placeholders.values()))
        self.assertEqual([item.record.code for item in entities.registry(
            self.project, self.v1.uid)], ["PLT-001"])
        self.assertEqual(self.query("SELECT content_sha256 FROM gb_dataset WHERE name = ?",
                                    efx.AXES_LAYER), layer_before)

        second = self.units(request(WORKSHOP, start=HOLE_DATASET))
        self.assertEqual(second.code, "PLT-002")


class RollbackRowsTest(EntityParamsCase):
    def test_a_row_that_exists_is_not_overwritten_and_a_transaction_that_fails_leaves_nothing(
            self) -> None:
        """RF-015-01: con la transacción de quien llama (``conn``, la del ``commit`` de la T13), las
        filas se deshacen con ella; escribir dos veces las de una entidad es ``core.param_exists`` (no
        se pisa nada)."""
        prepared = self.units(request(TOWER))

        class Rollback(Exception):
            pass

        self.clock.advance(minutes=1)
        with self.assertRaises(Rollback):
            with self.project.write_transaction() as conn:
                entity_store.set_entity_params(self.project, prepared.rows, version=self.v1.uid,
                                               decided_by=USER, conn=conn)
                raise Rollback
        self.assertEqual(self.version_rows(), [])
        with self.project.write_transaction() as conn:
            entity_store.set_entity_params(self.project, prepared.rows, version=self.v1.uid,
                                           decided_by=USER, conn=conn)
        self.assertEqual(len(self.version_rows()), len(prepared.rows))
        with self.assertRaises(core_params.ParamError) as caught:
            entity_store.set_entity_params(self.project, prepared.rows, version=self.v1.uid,
                                           decided_by=USER)
        self.assertEqual(caught.exception.code, "core.param_exists")
        self.assertEqual(len(self.version_rows()), len(prepared.rows))


class DefaultsTrapTest(EntityParamsCase):
    def test_without_its_rows_the_008_reads_the_defaults_from_the_project(self) -> None:
        """La trampa de la T04: con todas las filas menos las de los valores por defecto,
        ``begin_operation`` lee esos cuatro del **proyecto** (su valor por defecto «sin confirmar»,
        sin origen ni decisor de la entidad) y los demás de la versión; por eso ``prepare_platform``
        deja **todas** en ``rows``."""
        prepared = self.units(request(TOWER))
        defaults = {"mode", "mesh_factor", "counter_tol_m", "metric", "protect"}
        rows = tuple(row for row in prepared.rows if row.param.value not in defaults)
        self.assertEqual(len(rows) + len(defaults), len(prepared.rows))
        self.clock.advance(minutes=1)
        entity_store.set_entity_params(self.project, rows, version=self.v1.uid, decided_by=USER)
        handle = prepared.start.begin(self.project)
        self.addCleanup(cancel_if_running, handle)
        scopes = {item.key: item.scope for item in handle.params
                  if item.key.startswith("des.platform.")}
        read_from_project = {key for key, scope in scopes.items() if scope == "project"}
        self.assertEqual(read_from_project, {
            design_params.entity_key("PLT-001", name)
            for name in ("mode", "mesh_factor", "counter_tol_m", "metric")})
        self.assertEqual({key for key, scope in scopes.items() if scope == "version"},
                         {row.key for row in rows if row.key in scopes})


class CatalogTest(unittest.TestCase):
    """Los mensajes que añade la preparación (RF-015-04, RF-015-08): la capa en los rechazos de un
    parámetro y los dos códigos nuevos."""

    def test_the_parameter_refusals_name_the_layer(self) -> None:
        """RF-015-08: «capa, entidad, campo y valor»: el parámetro que falta o está fuera de rango
        nombra también la capa (español e inglés), igual que la pendiente máxima y proteger en «en
        corte y relleno»."""
        for code, extra in (("des.entity_param_missing", {}),
                            ("des.entity_param_range", {"range": "(0; 10 000] m"}),
                            ("des.entity_param_choice", {"choices": "«cut»"}),
                            ("des.platform_max_slope", {"maximum": 0.5}),
                            ("des.platform_protect_cut_fill", {})):
            for language in ("es", "en"):
                with self.subTest(code=code, language=language):
                    text = messages.render(code, language=language, layer="LAYER-X",
                                           entity="ENTITY-X", field="FIELD-X", value="VALUE-X",
                                           **extra)
                    for shown in ("LAYER-X", "ENTITY-X"):
                        self.assertIn(shown, text)


if __name__ == "__main__":
    unittest.main()
