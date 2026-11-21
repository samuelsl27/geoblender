# SPDX-License-Identifier: GPL-3.0-or-later
"""La operación de accesibilidad, la parte de preparar y calcular (spec 017, T17; HU-017-3; RF-017-24, RF-017-25, RF-017-04 y RF-017-30; RF-015-02, RF-015-03 y RF-015-16;
RNF-017-05 y RNF-017-10; plan 017 §5.2.2, §5.2.3, §5.3.2, §5.4 A10 y A11 y §5.7 P-1 y P-9; D-17 y D-18): ``design.access_store`` **prepara** (lee y rechaza antes de calcular, sin
escribir nada) y **calcula por pasos** (las cifras CALCULADO, los avisos y el resumen con las cotas y las listas). Crear, recalcular, reproducir y la lectura para la 012 son de la T17b.

Sobre el proyecto de las pistas (``tests.support.road_data``: la cantera de la 015 con los terrenos como rejillas, en la gruesa de 2 m, 200 × 200 celdas) y, para el cálculo, sobre la
cantera con bancos (CE-017-07) **a mano**: tres bermas comunicadas (135, 125 y 115 m) y una no (105 m), cotas mínima y máxima alcanzables de 115 y 140 m y una zona «requiere
acceso» comunicada y otra no (a 18 m, con 10 m de diferencia de cota en la rejilla de 2 m). Lo que se rechaza lo hace **sin escribir nada** (el contador de cambios de la base, las
operaciones, los datos, los parámetros y los ficheros no se mueven) y nombrando la capa, la accesibilidad, el campo y el valor (RF-017-04).
"""

from __future__ import annotations

import time
import unittest
from collections.abc import Generator
from types import SimpleNamespace
from typing import Any, ClassVar

import numpy as np

from tests.support import quarry_fixtures as qfx
from tests.support import res_fixtures
from tests.support import road_data as rd
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.support.versions_fixtures import change_counter

access = import_geoblender("gis.masks.access")
access_store = import_geoblender("design.access_store")
design_params = import_geoblender("design.params")
gis = import_geoblender("gis")
messages = import_geoblender("design.messages")
preview = import_geoblender("design.preview")
provenance = import_geoblender("design.provenance")
road_model = import_geoblender("design.road_model")
steps = import_geoblender("design.steps")
zones_module = import_geoblender("gis.masks.zones")

DesignError = messages.DesignError
GRID = qfx.grid_of(qfx.COARSE_STEP_M)
"""La rejilla gruesa de la cantera (200 × 200 celdas de 2 m)."""
SURFACE = rd.dataset_of("banco")
"""La cantera con bancos como superficie del proyecto (``gis_dtm_banco``)."""
CODE = "ACC-001"
KEY = "des.access.acc_001."
BERMS_DATASET = "des_brm_cantera"
"""El nombre del dato de cotas de berma de los casos (el de la cantera de la 014 de ``milestone_access_operation``)."""
NO_ENTRIES_LAYER = "gis_fea_sin_entradas"
FINE_DATASET = "gis_dtm_fina"
STEP_BUDGET_S = 0.2
"""RNF-017-06: cada llamada del hilo de Blender, a lo más 0,2 s."""
ENTRY_WITH_DATA, ENTRY_STEEP = "Entrada de la cantera de bancos", "Entrada del tajo"


def drive[T](work: Generator[None, None, T]) -> T:
    """Lo que devuelve ``work`` (unidades de preparación) llevado hasta el final."""
    while True:
        try:
            next(work)
        except StopIteration as stop:
            return stop.value  # type: ignore[no-any-return]


def request(name: str = "Accesibilidad", *, layer: str = rd.ENTRIES_LAYER, surface: str = SURFACE, name_field: str | None = "nombre",
            **changes: Any) -> Any:
    """Una accesibilidad de la capa de entradas de las pistas sobre la cantera con bancos, con los umbrales de la referencia de IMGA (solo de las pruebas)."""
    base: dict[str, Any] = {"walk_slope_pct": rd.ACCESS.walk_slope_pct, "walk_width_m": rd.ACCESS.walk_width_m,
                            "min_berm_area_m2": rd.ACCESS.min_berm_area_m2}
    return road_model.AccessRequest(name, road_model.LayerFields(layer, name_field), surface, **{**base, **changes})


def absolute(point: tuple[float, float]) -> tuple[float, float]:
    """El punto local ``point`` como absoluto en la rejilla de 2 m."""
    x, y = rd.absolute([point], GRID)[0]
    return float(x), float(y)


def run(work: Any) -> Any:
    """Lleva unos pasos hasta el último y devuelve su ``result`` (la ``Calculation`` de ``steps.access_run``); cada paso, en menos de :data:`STEP_BUDGET_S`."""
    last = time.perf_counter()
    found = None
    for step in work:
        now = time.perf_counter()
        assert now - last <= STEP_BUDGET_S, f"un paso tardó {now - last:.3f} s"
        last = now
        found = step.result if step.result is not None else found
    return found


def compute[T](work: Generator[Any, None, T]) -> T:
    """Lleva un generador de pasos hasta el final y devuelve lo que devuelve (el ``AccessOutcome`` de ``access_compute_steps``); cada paso, en menos de :data:`STEP_BUDGET_S`."""
    last = time.perf_counter()
    while True:
        try:
            next(work)
        except StopIteration as stop:
            return stop.value  # type: ignore[no-any-return]
        now = time.perf_counter()
        assert now - last <= STEP_BUDGET_S, f"un paso tardó {now - last:.3f} s"
        last = now


class PrepareCase(rd.RoadProjectCase):
    """Una copia por clase del proyecto de las pistas (rejilla de 2 m) con las máscaras de V01 cargadas, una capa de puntos **sin ningún punto** y una superficie en otra rejilla
    (de 1 m)."""

    STEP_M = qfx.COARSE_STEP_M
    masks_v1: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.masks_v1 = access.load_masks(cls.project, cls.v1.uid)
        sdata.write_layer(cls.project, cls.clock, sdata.FieldsLayer(NO_ENTRIES_LAYER, "point", (), (), {}))
        fine = qfx.grid_of(qfx.STEP_M)
        res_fixtures.write_grids(cls.project, [("fina", gis.Raster(fine, np.full(fine.shape, 100.0), rd.CRS, rd.VERTICAL))],
                                 message="Superficie de 1 m de la prueba de preparar la accesibilidad")

    def state(self) -> dict[str, Any]:
        """Todo lo que podría escribir la preparación o el cálculo: el contador de cambios de la base y, aparte, lo que se vería: operaciones, datos, parámetros y los ficheros de
        ``rasters/``."""
        return {
            "counter": change_counter(self.root),
            "operations": self.query("SELECT uid, status FROM gb_operation ORDER BY rowid"),
            "datasets": self.query("SELECT uid, status, content_sha256 FROM gb_dataset ORDER BY rowid"),
            "parameters": self.query("SELECT key, scope_uid, value FROM gb_parameter ORDER BY rowid"),
            "files": sorted(path.name for path in (self.root / "rasters").iterdir())}

    def prepare(self, asked: Any, *, version: Any = "default", **options: Any) -> Any:
        """:func:`prepare_access` con V01 por defecto y sus máscaras."""
        which = self.v1.uid if version == "default" else version
        return access_store.prepare_access(self.project, asked, version=which, masks=options.pop("masks", self.masks_v1), **options)

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
            self.assertNotIn("?", text)
        return error

    def names(self, error: Any, **expected: Any) -> None:
        """El rechazo nombra lo que se espera (en sus valores y en su texto)."""
        for key, value in expected.items():
            self.assertEqual(error.values[key], value, key)
            if not isinstance(value, float):  # los decimales salen con coma en el texto
                self.assertIn(str(value), error.text)


class AccessProjectTest(PrepareCase):
    """RF-017-24, RF-017-25, RF-017-04, RF-015-03, RF-015-08 y RF-015-29: preparar, rechazar y calcular sobre el proyecto (una sola copia: ninguna prueba de la clase cambia el
    proyecto), siempre **sin escribir nada**. Lo que cambia el proyecto (cerrar una versión, escribir las bermas y las dos superficies de una cantera) es de
    ``milestone_access_operation``."""

    # --- Lo que se lee (RF-017-24, RF-017-25, RF-015-03, RF-015-08) ---

    def test_a_version_access_is_prepared_without_writing(self) -> None:
        """RF-017-24, RF-015-03: la capa de entradas, la superficie del proyecto, el código ``ACC-001``, la rejilla y las máscaras de V01 dejan un ``AccessJob`` con todo lo leído (la
        superficie bit a bit; las dos entradas en absolutas con su nombre; los tres umbrales; lo intocable, el bit ``UNTOUCHABLE`` de las máscaras) y la ``OperationStart`` de
        ``des.road_access`` con sus ajustes, entradas (la superficie, la capa de entradas con su papel y las máscaras) y parámetros; nada se escribe."""
        asked = request()
        before = self.state()
        prepared = self.prepare(asked)
        self.assertEqual(self.state(), before)
        self.assertEqual((prepared.code, prepared.op_type, prepared.existing, prepared.version.uid), (CODE, provenance.ROAD_ACCESS, False, self.v1.uid))
        self.assertEqual((prepared.version_uid, prepared.surface, prepared.layer), (self.v1.uid, SURFACE, rd.ENTRIES_LAYER))
        job = prepared.job
        self.assertIs(job.request, asked)
        self.assertEqual((job.code, job.grid), (CODE, GRID))
        np.testing.assert_array_equal(job.surface, rd.bank_surface(GRID))
        self.assertEqual([(entry.name, entry.x, entry.y) for entry in job.entries],
                         [(ENTRY_WITH_DATA, *absolute(rd.BANK_ENTRY)), (ENTRY_STEEP, *absolute(rd.PIT_ENTRY))])
        self.assertEqual((job.walk_slope_pct, job.walk_width_m, job.min_berm_area_m2), (16.0, 4.0, 300.0))
        wall = (self.masks_v1.classes & np.uint16(64)) != 0
        self.assertTrue(wall.any(), "la cantera de la 014 tiene un intocable (la torre)")
        np.testing.assert_array_equal(job.untouchable, wall)
        self.assertEqual((job.final, job.berms, job.platforms, job.zones), (None, (), (), ()))
        start = prepared.start
        self.assertEqual((start.op_type, start.name, start.version_uid, start.supersedes), (provenance.ROAD_ACCESS, "Accesibilidad", self.v1.uid, None))
        self.assertEqual(dict(start.settings), {"name": "Accesibilidad", "code": CODE, "entries": {"name_field": "nombre"}})
        self.assertEqual(dict(start.settings), provenance.access_settings(asked, CODE))
        self.assertEqual([(use.item, str(use.role)) for use in start.inputs],
                         [(SURFACE, "surface"), (rd.ENTRIES_LAYER, "access_entries"), *((use.item, str(use.role)) for use in self.masks_v1.uses())])
        self.assertEqual(start.params, provenance.access_params(CODE))
        self.assertIs(start.masks, self.masks_v1)
        by_units = drive(access_store.prepare_access_units(self.project, asked, self.v1, self.masks_v1))  # RF-017-30: por unidades da lo mismo
        self.assertEqual((by_units.code, by_units.job.entries, by_units.rows), (CODE, job.entries, prepared.rows))
        self.assertEqual(self.prepare(request("Otra")).code, CODE)  # RF-015-01: sin ninguna accesibilidad en la versión, ``ACC-001`` con cualquier nombre

    def test_the_parameters_of_the_entity_come_with_their_origin(self) -> None:
        """RF-015-08, D-17: las seis filas de los parámetros de la entidad (nombre, superficie, capa de entradas y los tres umbrales: sin valor por defecto), todas del diálogo
        con su procedencia de la persona; los umbrales como números, sin ninguno elegido por ella."""
        prepared = self.prepare(request("Con otros umbrales", walk_slope_pct=12.5, walk_width_m=3.0, min_berm_area_m2=250.0))
        self.assertEqual([row.key for row in prepared.rows],
                         [f"{KEY}{name}" for name in ("name", "surface", "entries_layer", "walk_slope_pct", "walk_width_m", "min_berm_area_m2")])
        self.assertEqual(dict(prepared.values), {"name": "Con otros umbrales", "surface": SURFACE, "entries_layer": rd.ENTRIES_LAYER, "walk_slope_pct": 12.5, "walk_width_m": 3.0,
                                                 "min_berm_area_m2": 250.0})
        for row in prepared.rows:
            self.assertEqual(row.source_kind, "person", row.key)
            self.assertIn("Con otros umbrales", row.source)
            self.assertEqual(row.value, prepared.values[str(row.param)])

    def test_the_entry_names_come_from_the_name_field_or_the_fid(self) -> None:
        """RF-017-24: sin campo de nombre, la entrada se llama por su ``fid``; con él, por su campo."""
        prepared = self.prepare(request(name_field=None))
        self.assertEqual([entry.name for entry in prepared.job.entries], ["1", "2"])


    # --- Lo que se rechaza (RF-017-04, RF-015-08), nombrando la capa, la accesibilidad, el campo y el valor ---

    def test_no_entry_point(self) -> None:
        """RF-017-04: una capa de puntos sin ningún punto se rechaza (``des.access_no_entry``) nombrando la capa y la accesibilidad."""
        error = self.refused(request(layer=NO_ENTRIES_LAYER), "des.access_no_entry")
        self.names(error, layer=NO_ENTRIES_LAYER, entity="Accesibilidad")

    def test_an_entry_without_data(self) -> None:
        """RF-017-04: un punto de entrada sin dato (aquí, fuera de la rejilla) se rechaza (``des.access_entry_no_data``) nombrando la capa, el punto, la superficie y su lugar."""
        error = self.refused(request(layer=rd.POINTS_LAYER), "des.access_entry_no_data")
        x, y = absolute((-20.0, 200.0))
        self.names(error, layer=rd.POINTS_LAYER, entity="Accesibilidad", value="Punto fuera de la rejilla", surface=SURFACE, x=round(x, 2), y=round(y, 2))

    def test_a_parameter_without_value_or_out_of_range(self) -> None:
        """RF-015-08, D-17: la pendiente, el ancho o el área mínima sin valor (no se elige ninguno) o fuera de su rango se rechazan nombrando la entidad, el campo y el valor."""
        for field in ("walk_slope_pct", "min_berm_area_m2"):
            with self.subTest(field=field, case="missing"):
                error = self.refused(request(**{field: None}), "des.entity_param_missing")
                self.names(error, layer=rd.ENTRIES_LAYER, entity="Accesibilidad", field=f"{KEY}{field}")
        for field, bad in (("walk_width_m", -1.0),):
            with self.subTest(field=field, case="range"):
                error = self.refused(request(**{field: bad}), "des.entity_param_range")
                self.names(error, entity="Accesibilidad", field=f"{KEY}{field}", value=bad)

    def test_a_surface_on_another_grid_or_unknown(self) -> None:
        """RF-011-02, RF-017-24: una superficie en otra rejilla (``des.surface_mismatch``) o que no existe (``gis.dataset_unknown``) se rechaza antes de leer una celda."""
        error = self.refused(request(surface=FINE_DATASET), "des.surface_mismatch")
        self.names(error, surface=FINE_DATASET)
        error = self.refused(request(surface="gis_dtm_no_existe"), "gis.dataset_unknown")
        self.assertEqual(error.value, "gis_dtm_no_existe")

    def test_the_entries_layer(self) -> None:
        """RF-017-04: una capa que no es de puntos (``des.access_layer_not_points``), un campo de nombre que no tiene (``des.access_layer_field``) o una capa que no existe
        (``gis.dataset_unknown``)."""
        error = self.refused(request(layer=rd.ZONES_LAYER), "des.access_layer_not_points")
        self.assertEqual((error.values["layer"], error.values["entity"]), (rd.ZONES_LAYER, "Accesibilidad"))
        error = self.refused(request(name_field="no_existe"), "des.access_layer_field")
        self.assertEqual((error.values["layer"], error.values["value"]), (rd.ENTRIES_LAYER, "no_existe"))
        self.assertIn("nombre", error.values["fields"])
        self.refused(request(layer="gis_fea_no_existe"), "gis.dataset_unknown")

    def test_the_masks_of_another_version_are_a_program_error(self) -> None:
        """RF-013-04 (las máscaras son de versión): preparar en V01 con las máscaras de otra versión es un ``ValueError`` (un error del programa) y no escribe nada."""
        before = self.state()
        with self.assertRaises(ValueError):
            drive(access_store.prepare_access_units(self.project, request(), self.v1, SimpleNamespace(version_uid=self.v2.uid)))
        self.assertEqual(self.state(), before)

    # --- «Calcular» (RF-017-24, RF-015-03, RF-015-29, RF-017-30): la ``Calculation`` con el resultado, las cifras y el resumen, y nada escrito ---

    def test_calculating_writes_nothing_and_gives_the_summary(self) -> None:
        """RF-015-03: «Calcular» sobre la cantera con bancos y las dos entradas del proyecto (la del tajo cae en la pared del 97 %: avisa) da la ``Calculation`` de
        ``des.road_access`` con su resultado (115 y 140 m), sus cifras y su resumen (con el aviso de la entrada y las cotas), y no escribe **nada**: ni la base de datos, ni los
        ficheros, ni las operaciones, los datos o los parámetros."""
        before = self.state()
        calculation = run(steps.access_run(self.project, request(), version=self.v1.uid, masks=self.masks_v1))
        try:
            self.assertEqual(self.state(), before)
            self.assertEqual((calculation.op_type, calculation.name, calculation.version, calculation.open), (provenance.ROAD_ACCESS, "Accesibilidad", "V01", True))
            outcome = calculation.outcome
            self.assertEqual((outcome.z_min_m, outcome.z_max_m, outcome.name, outcome.code), (115.0, 140.0, "Accesibilidad", CODE))
            self.assertEqual(calculation.figures, outcome.figures)
            self.assertEqual(figures_of(outcome)["des.acc_z_min_m"], (115.0, "m"))
            summary = calculation.summary
            self.assertEqual((summary.name, summary.code, summary.version, summary.surface), ("Accesibilidad", CODE, "V01", SURFACE))
            self.assertEqual([notice.code for notice in calculation.notices][:2], ["des.access_summary", "des.access_levels"])
            self.assertIn("des.access_entry_not_walkable", [notice.code for notice in calculation.notices])
            self.assertEqual(calculation.message, outcome.message)
            self.assertIn("Accesibilidad", calculation.message)
            self.assertIn("115", calculation.message)
        finally:
            calculation.discard()
        self.assertEqual(self.state(), before)

    def test_creating_is_for_the_next_task(self) -> None:
        """T17: crear la accesibilidad es de la T17b: la ``Calculation`` lo dice (``NotImplementedError``) sin escribir nada y sin cerrarse."""
        calculation = run(steps.access_run(self.project, request(), version=self.v1.uid, masks=self.masks_v1))
        before = self.state()
        try:
            with self.assertRaises(NotImplementedError):
                calculation.create()
            self.assertEqual(self.state(), before)
            self.assertTrue(calculation.open)
        finally:
            calculation.discard()

    def test_closing_halfway_leaves_nothing(self) -> None:
        """RF-015-29, RF-017-30: cerrar el generador a mitad del cálculo (Esc, desactivar Geoblender) no deja nada: el estado del proyecto es el de antes; ni operación, ni
        dato, ni parámetro, ni fichero."""
        before = self.state()
        work = steps.access_run(self.project, request(), version=self.v1.uid, masks=self.masks_v1)
        self.assertIsNone(next(work).result)
        work.close()
        self.assertEqual(self.state(), before)
        work = steps.access_run(self.project, request(), version=self.v1.uid, masks=self.masks_v1)
        seen = []
        for step in work:
            seen.append(step)
            if step.phase == "access_compute":  # ya preparada y calculando: la Calculation aún no existe
                break
        work.close()
        self.assertTrue(seen and all(step.result is None for step in seen))
        self.assertEqual(self.state(), before)

    def test_a_rejection_comes_when_advancing_and_writes_nothing(self) -> None:
        """RF-017-04, RF-015-29: sin ningún punto de entrada, «Calcular» se rechaza al avanzar y no deja nada."""
        before = self.state()
        with self.assertRaises(DesignError) as caught:
            run(steps.access_run(self.project, request(layer=NO_ENTRIES_LAYER), version=self.v1.uid, masks=self.masks_v1))
        self.assertEqual(caught.exception.code, "des.access_no_entry")
        self.assertEqual(self.state(), before)


class ReadingsTest(unittest.TestCase):
    """RF-017-24, RF-017-25: lo que sale de las máscaras y de las huellas, sin proyecto."""

    def test_untouchable_is_the_class_bit_of_the_masks(self) -> None:
        """T15-a: lo que no se atraviesa es el bit ``UNTOUCHABLE`` de la rejilla de clases (intocables y exclusiones), no los demás."""
        classes = np.zeros((4, 5), dtype=np.uint16)
        classes[1, 2] = 64
        classes[2, 3] = 64 | 8 | 512
        classes[3, 0] = 8 | 16 | 512 | 128
        found = access_store.untouchable_cells(SimpleNamespace(classes=classes))
        wanted = np.zeros((4, 5), dtype=bool)
        wanted[1, 2] = wanted[2, 3] = True
        np.testing.assert_array_equal(found, wanted)

    def test_the_zones_that_require_access_one_by_one(self) -> None:
        """RF-017-25: una zona por restricción de tipo «requiere acceso» (cada una con sus celdas por índice en filas, no la unión), en el orden de las máscaras; los demás tipos
        y la banda hacia dentro de un límite legal no cuentan."""
        grid = gis.Grid(0.0, 6.0, 1.0, 1.0, 8, 6)
        first = np.zeros(grid.shape, dtype=bool)
        first[1, 1:4] = True
        second = np.zeros(grid.shape, dtype=bool)
        second[4, 5:8] = True
        second[3, 7] = True
        other = np.zeros(grid.shape, dtype=bool)
        other[0, :] = True
        runs = zones_module.Runs
        masks = SimpleNamespace(grid=grid, zones={"acceso_a": runs.from_mask(first), "concesion": runs.from_mask(other), "acceso_b": runs.from_mask(second),
                                                  "concesion:inner": runs.from_mask(other)},
                                ctypes={"acceso_a": "requires_access", "concesion": "legal_limit", "acceso_b": "requires_access"})
        found = access_store.access_zones(masks)
        self.assertEqual([zone.code for zone in found], ["acceso_a", "acceso_b"])
        np.testing.assert_array_equal(found[0].cells, np.flatnonzero(first.ravel()))
        np.testing.assert_array_equal(found[1].cells, np.flatnonzero(second.ravel()))
        self.assertEqual(found[0].cells.dtype, np.int64)
        self.assertEqual(access_store.access_zones(SimpleNamespace(grid=grid, zones={}, ctypes={})), ())

    def test_a_footprint_in_runs_is_a_list_of_cells(self) -> None:
        """RF-017-25: la huella de una plataforma (tramos de fila ``(fila, primera, final excluida)``) son sus celdas por índice en filas; sin tramos, ninguna."""
        found = access_store.platform_cells(((0, 1, 3), (2, 4, 7)), 8)
        np.testing.assert_array_equal(found, [1, 2, 20, 21, 22])
        self.assertEqual(found.dtype, np.int64)
        self.assertEqual(access_store.platform_cells((), 8).size, 0)


# --- Calcular ----------------------------------------------------------------------------------------------------------------


def bank_job(*, entries: Any = (rd.BANK_ENTRY,), final: np.ndarray | None = None, with_lists: bool = True, **changes: Any) -> Any:
    """Un ``AccessJob`` de la cantera con bancos en la rejilla de 2 m (CE-017-07): la berma de cada cota, la plataforma de la berma de 125 m y las dos zonas «requiere acceso»."""
    kind: dict[str, Any] = {}
    if with_lists:
        kind = {"berms": [road_model.BermGrid(BERMS_DATASET, rd.bank_berms(GRID))],
                "platforms": [road_model.AccessCells("PLT-001", "Plataforma de la berma 125", np.flatnonzero(rd.bank_platform_mask(GRID).ravel()))],
                "zones": [road_model.AccessCells(name.lower().replace(" ", "_"), name, np.flatnonzero(rd.bank_zone_mask(name, GRID).ravel())) for name in rd.BANK_ZONE_BOXES]}
    return rd.access_job(GRID, rd.bank_surface(GRID), entries, final=final, **{**kind, **changes})


def figures_of(outcome: Any) -> dict[str, tuple[float, str]]:
    """Las cifras del resultado por su clave: ``(valor, unidad)``."""
    return {figure.key: (figure.value, figure.unit) for figure in outcome.figures}


class ComputeTest(unittest.TestCase):
    """RF-017-24, RF-017-25, RF-017-04, RF-017-30: calcular por pasos, las cifras CALCULADO con su ámbito, los avisos y el resumen."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.job = bank_job()
        cls.outcome = compute(access_store.access_compute_steps(cls.job))

    def test_the_figures_of_the_bank_case(self) -> None:
        """RF-017-24, RF-017-25, CE-017-07: las nueve cifras de ``des.road_access`` **a mano** (cota mínima 115 m y máxima 140 m; tres de cuatro bermas comunicadas, la plataforma y
        una de dos zonas), con su unidad y el ámbito de la entidad; sin superficie final, ``des.acc_z_min_final_m`` no existe."""
        values = figures_of(self.outcome)
        self.assertEqual(values["des.acc_z_min_m"], (115.0, "m"))
        self.assertEqual(values["des.acc_z_max_m"], (140.0, "m"))
        self.assertEqual(values["des.acc_area_m2"], (self.outcome.area_m2, "m2"))
        self.assertGreater(self.outcome.area_m2, 0.0)
        self.assertEqual({key: value for key, value in values.items() if key.endswith(("_reached", "_total", "_missing"))},
                         {"des.acc_berms_reached": (3, "-"), "des.acc_berms_total": (4, "-"), "des.acc_platforms_reached": (1, "-"),
                          "des.acc_zones_reached": (1, "-"), "des.acc_zones_missing": (1, "-")})
        self.assertNotIn("des.acc_z_min_final_m", values)
        self.assertEqual([figure.key for figure in self.outcome.figures], [item.key for item in provenance.ACCESS_FIGURES if item.key in values])
        for figure in self.outcome.figures:
            self.assertEqual(dict(figure.scope), provenance.entity_figure_scope("Accesibilidad de prueba", CODE), figure.key)

    def test_the_counts_of_the_zones_are_not_symmetric(self) -> None:
        """RF-017-25: con una sola zona, la comunicada (``Zona con acceso``) da 1 alcanzada y 0 sin alcanzar; la que no (``Zona sin acceso``), 0 y 1; sin ninguna, 0 y 0."""
        for names, wanted in ((("Zona con acceso",), (1, 0)), (("Zona sin acceso",), (0, 1)), ((), (0, 0))):
            with self.subTest(zones=names):
                zones = [road_model.AccessCells(name.lower().replace(" ", "_"), name, np.flatnonzero(rd.bank_zone_mask(name, GRID).ravel())) for name in names]
                values = figures_of(compute(access_store.access_compute_steps(bank_job(zones=zones))))
                self.assertEqual((values["des.acc_zones_reached"][0], values["des.acc_zones_missing"][0]), wanted)

    def test_the_outcome_keeps_everything_the_domain_computed(self) -> None:
        """RF-017-25: el resultado es el del dominio (``road_access.access``) con las cifras y los avisos compuestos encima: la rejilla de lo alcanzable, las cotas, las listas
        de bermas, plataformas y zonas, igual."""
        domain = import_geoblender("design.road_access").access(self.job)
        np.testing.assert_array_equal(self.outcome.reachable, domain.reachable)
        self.assertEqual((self.outcome.z_min_m, self.outcome.z_max_m, self.outcome.area_m2, self.outcome.z_min_final_m),
                         (domain.z_min_m, domain.z_max_m, domain.area_m2, domain.z_min_final_m))
        self.assertEqual((self.outcome.berms, self.outcome.platforms, self.outcome.zones), (domain.berms, domain.platforms, domain.zones))
        self.assertTrue(self.outcome.reachable.flags.writeable is False)

    def test_the_final_surface_adds_its_figure(self) -> None:
        """RF-017-24 (error 23): con una superficie final, ``des.acc_z_min_final_m`` es la cota mínima alcanzable sobre ella, junto a la de la explotación."""
        outcome = compute(access_store.access_compute_steps(bank_job(final=rd.bank_surface(GRID) + 10.0)))
        values = figures_of(outcome)
        self.assertEqual(values["des.acc_z_min_final_m"], (125.0, "m"))
        self.assertEqual(values["des.acc_z_min_m"], (115.0, "m"))
        self.assertEqual(outcome.z_min_final_m, 125.0)

    def test_an_entry_that_is_not_on_walkable_ground_warns_and_the_calculation_goes_on(self) -> None:
        """T15 (decisión de la sesión principal): una entrada en una celda **no transitable** (aquí, la del tajo, sobre la pared del 97 %) **avisa** (``des.access_entry_not_walkable``,
        nombrando la entrada y su lugar) y no es un rechazo: no alcanza nada y el cálculo sigue con las demás (lo alcanzable es el mismo que sin ella)."""
        both = compute(access_store.access_compute_steps(bank_job(entries=(rd.BANK_ENTRY, rd.PIT_ENTRY))))
        alone = self.outcome
        np.testing.assert_array_equal(both.reachable, alone.reachable)
        self.assertEqual((both.z_min_m, both.z_max_m), (alone.z_min_m, alone.z_max_m))
        warned = [notice for notice in both.notices if notice.code == "des.access_entry_not_walkable"]
        self.assertEqual(len(warned), 1)
        x, y = absolute(rd.PIT_ENTRY)
        self.assertEqual((warned[0].values["value"], warned[0].values["x"], warned[0].values["y"]), ("E2", round(x, 2), round(y, 2)))
        self.assertEqual(warned[0].values["entity"], "Accesibilidad de prueba")
        self.assertEqual(warned[0].severity, "warning")
        self.assertIn("E2", warned[0].text("es"))
        self.assertEqual([n.code for n in alone.notices], [])

    def test_nothing_reached_is_said(self) -> None:
        """RF-017-24: si ninguna entrada es transitable no se alcanza ninguna celda: ``des.access_nothing_reached`` (un aviso) y, sin celdas, ninguna cota ni el área (la cifra de
        la cota no existe) sin ser un rechazo."""
        outcome = compute(access_store.access_compute_steps(bank_job(entries=(rd.PIT_ENTRY,))))
        self.assertIsNone(outcome.z_min_m)
        codes = [notice.code for notice in outcome.notices]
        self.assertEqual(codes, ["des.access_entry_not_walkable", "des.access_nothing_reached"])
        values = figures_of(outcome)
        self.assertNotIn("des.acc_z_min_m", values)
        self.assertEqual(values["des.acc_area_m2"], (0.0, "m2"))
        self.assertEqual(values["des.acc_berms_reached"], (0, "-"))

    def test_the_rejections_of_rf_017_04_come_when_advancing(self) -> None:
        """RF-017-04: sin entradas o con una sin dato, el cálculo se rechaza al avanzar (antes de calcular) nombrando la capa y la accesibilidad."""
        with self.assertRaises(DesignError) as caught:
            next(access_store.access_compute_steps(bank_job(entries=())))
        self.assertEqual(caught.exception.code, "des.access_no_entry")
        with self.assertRaises(DesignError) as caught:
            next(access_store.access_compute_steps(bank_job(entries=((-20.0, 200.0),))))
        self.assertEqual(caught.exception.code, "des.access_entry_no_data")

    def test_each_step_is_short_and_closing_leaves_nothing(self) -> None:
        """RNF-017-06, RF-017-30: cada paso, a lo más 0,2 s; cerrar el generador a mitad no deja nada (no escribe ni modifica la superficie, lo intocable ni lo alcanzable)."""
        job = bank_job()
        before = (job.surface.tobytes(), job.untouchable.tobytes())
        work = access_store.access_compute_steps(job)
        seen = [next(work)]
        self.assertTrue(all(step.result is None for step in seen))
        work.close()
        self.assertEqual((job.surface.tobytes(), job.untouchable.tobytes()), before)
        compute(access_store.access_compute_steps(job))
        self.assertEqual((job.surface.tobytes(), job.untouchable.tobytes()), before)


class SummaryTest(unittest.TestCase):
    """RF-017-24, RF-017-25, RF-015-03: el resumen de «Calcular» con las cotas y las listas, sin proyecto."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.job = bank_job(entries=(rd.BANK_ENTRY, rd.PIT_ENTRY))
        cls.outcome = compute(access_store.access_compute_steps(cls.job))
        cls.summary = access_store.access_summary(cls.outcome, version="V01", surface=SURFACE)

    def test_the_header_and_the_levels(self) -> None:
        """RF-017-24: la cabecera (cuántas bermas, plataformas y zonas se comunican de las que hay) y las cotas mínima y máxima y el área alcanzables, con sus valores."""
        first, second = self.summary.notices[:2]
        self.assertEqual((first.code, second.code), ("des.access_summary", "des.access_levels"))
        self.assertEqual((first.values["berms"], first.values["berms_reached"], first.values["platforms"], first.values["platforms_reached"],
                          first.values["zones"], first.values["zones_reached"]), (4, 3, 1, 1, 2, 1))
        self.assertEqual((second.values["z_min"], second.values["z_max"], second.values["area"]), (115.0, 140.0, self.outcome.area_m2))
        self.assertEqual((self.summary.name, self.summary.code, self.summary.version, self.summary.surface, self.summary.final),
                         ("Accesibilidad de prueba", CODE, "V01", SURFACE, None))
        self.assertEqual((self.summary.z_min_m, self.summary.z_max_m, self.summary.area_m2, self.summary.z_min_final_m), (115.0, 140.0, self.outcome.area_m2, None))
        self.assertEqual(self.summary.figures, self.outcome.figures)

    def test_the_lists_are_complete_and_the_warnings_name_what_is_not_communicated(self) -> None:
        """RF-017-25: las listas del resumen son las enteras (tramos de berma, plataformas y zonas, comunicados o no); en los avisos, cada tramo de berma, plataforma y zona que
        **no** se comunica (la berma de 105 m con su cota, área y lugar; la zona con su lugar, distancia y diferencia de cota) y ninguno de los comunicados."""
        self.assertEqual((self.summary.berms, self.summary.platforms, self.summary.zones), (self.outcome.berms, self.outcome.platforms, self.outcome.zones))
        missing = {notice.code: notice for notice in self.summary.notices if notice.code.endswith(("_missing", "_missing_unplaced"))}
        self.assertEqual(sorted(missing), ["des.access_berm_missing", "des.access_zone_missing"])
        berm, zone = missing["des.access_berm_missing"], missing["des.access_zone_missing"]
        self.assertEqual((berm.values["level"], berm.values["area"], berm.values["stretch"]), (105.0, 8000.0, 1))
        self.assertEqual((zone.values["code"], zone.values["distance"], zone.values["difference"]), ("zona_sin_acceso", 18.0, 10.0))
        self.assertEqual((zone.values["x"], zone.values["y"]), (699861.0, 4399841.0))
        self.assertTrue(all(notice.severity == "warning" for notice in missing.values()))
        self.assertIn("E2", [notice.values.get("value") for notice in self.summary.notices if notice.code == "des.access_entry_not_walkable"])

    def test_every_notice_has_a_text_in_both_languages(self) -> None:
        """Principio 10: cada línea del resumen se escribe en español y en inglés sin dejar ningún marcador sin llenar."""
        self.assertEqual(len(self.summary.lines("es")), len(self.summary.notices))
        for language in ("es", "en"):
            for line in self.summary.lines(language):
                self.assertNotIn("{", line)
                self.assertTrue(line.strip())
        self.assertEqual(len(self.summary.warnings()), sum(1 for notice in self.summary.notices if notice.severity == "warning"))

    def test_a_long_list_of_what_is_missing_is_cut_with_a_note(self) -> None:
        """RF-017-25: de lo que no se comunica se avisan los ``SUMMARY_ITEMS`` primeros de cada lista y una nota con los que faltan; la lista entera sigue en el resumen."""
        many = tuple(road_model.BermReach(number, 100.0 + number, 500.0, False, 10.0 * number, 20.0 * number, "des_brm_x") for number in range(1, 16))
        outcome = road_model.AccessOutcome(name="Larga", code=CODE, reachable=np.zeros((2, 2), dtype=bool), z_min_m=None, z_max_m=None, area_m2=0.0, berms=many)
        summary = access_store.access_summary(outcome, version="V01", surface=SURFACE)
        codes = [notice.code for notice in summary.notices]
        self.assertEqual(codes.count("des.access_berm_missing"), preview.SUMMARY_ITEMS)
        self.assertEqual(codes.count("des.access_more"), 1)
        more = next(notice for notice in summary.notices if notice.code == "des.access_more")
        self.assertEqual(more.values["more"], 15 - preview.SUMMARY_ITEMS)
        self.assertEqual(len(summary.berms), 15)

    def test_what_will_be_obsolete_is_a_note(self) -> None:
        """RF-015-03, RF-015-16: lo que quedará obsoleto al repetirla (la lista entera y una nota con la cuenta y los nombres de las ``SUMMARY_ITEMS`` primeras)."""
        found = tuple(preview.Obsolete(preview.ObsoleteKind.DEPENDENT, f"Verificación {number}", "res.verify_constraints", f"uid{number}") for number in range(3))
        summary = access_store.access_summary(self.outcome, version="V01", surface=SURFACE, obsolete=found)
        self.assertEqual(summary.obsolete, found)
        last = summary.notices[-1]
        self.assertEqual((last.code, last.values["operations"]), ("des.access_obsolete_dependents", 3))
        self.assertEqual(access_store.access_summary(self.outcome, version="V01", surface=SURFACE).obsolete, ())
        self.assertNotIn("des.access_obsolete_dependents", [notice.code for notice in self.summary.notices])


if __name__ == "__main__":
    unittest.main()
