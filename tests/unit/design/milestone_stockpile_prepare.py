# SPDX-License-Identifier: GPL-3.0-or-later
"""Preparar y rechazar la detección de acopios: lo que se lee y se rechaza antes de calcular (spec 016, T11; HU-016-1;
RF-016-02, RF-016-03, RF-016-04, RF-015-08, RF-015-09; RF-015-01, RF-015-07; plan 016 §5.2.1, §5.2.2 y §5.3.1; ADR-0031 §2;
D-15, D-17, D-20).

Sobre la cantera sintética de los acopios (``tests.support.stockpile_data``, T01), en la rejilla gruesa de 2 m (200 × 200
celdas) con las cinco marcas de la cantera (``Acopio 1`` a ``Acopio 5``: cuadrados de 20 × 20 m, **10 × 10 celdas** de 2 m
cada uno), el levantamiento y el de antes como superficies del proyecto y una copia del levantamiento como superficie de
**V01** (una versión). Las cuentas están hechas a mano (un bucle sobre los centros de celda, no el código):

- **El camino bueno** (:class:`PreparedDetectionTest`): ``prepare_detection`` da, sin escribir nada, el ``StockpileJob`` con
  la superficie bit a bit, las cinco marcas rasterizadas (a mano: filas 145 a 154 del Acopio 1 al 3 y 85 a 94 del 4 y el 5;
  columnas 45 a 54, 55 a 64, 115 a 124, 60 a 69 y 115 a 124; el margen de 6 m del 3 y los materiales), los umbrales de D-3 y
  el de la 011 (0,30 m), las 19 filas de los parámetros con su procedencia, y lo que anotará la operación; **del proyecto**
  si la superficie es del proyecto (también sin versión activa: ``des.stockpile_detect_project``, sin máscaras y sin dato de
  versión: RF-009-05) y **de la versión** si es de una versión (``des.stockpile_detect``, con las máscaras); el perímetro
  de los candidatos (las máscaras de la versión o la restricción del proyecto: el mismo); una marca con superficie de base
  propia (RF-016-03); y cuántas celdas tiene una marca con hueco, con dos partes o recortada por la rejilla.
- **Los rechazos** (:class:`MarkLayersTest`, :class:`NotEditableTest`), cada uno **sin escribir nada** y nombrando la capa, la
  entidad, el campo y el valor (RF-015-08): versión (sin versión activa en una superficie de versión, desconocida, no
  editable), superficie inexistente, campo de la capa que no está o no es del tipo, capa que no es de polígonos, nombre de
  marca que falta o repetido, margen negativo o fuera de rango, geometría no válida o sin celdas, capa sin marcas, parámetro
  sin valor o fuera de rango, ``base`` inexistente, en otra rejilla o de otra versión, y **marcas solapadas nombrando las
  dos**; las que solo se tocan por el borde no se rechazan (Acopio 1 y 2).
- **Los nombres** (:class:`NamesTest`): el código ``STK-nnn`` es correlativo **por ámbito** y el nombre es único en él.
- **La detección no llama a** ``refuse_pending`` (spec §8: no mueve celdas).
Spec 016, T43 (RNF-016-06): pasó del «verde» al paso «hito» (P-13), sin cambiar ninguna prueba; antes, ``test_stockpile_prepare.py``.
"""

from __future__ import annotations

import unittest
from collections.abc import Generator
from types import MappingProxyType
from typing import Any, ClassVar
from unittest import mock

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import quarry_fixtures as qfx
from tests.support import res_fixtures
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.versions_fixtures import change_counter

access = import_geoblender("gis.masks.access")
core_params = import_geoblender("core.params")
design_params = import_geoblender("design.params")
entity_store = import_geoblender("design.entity_store")
gis = import_geoblender("gis")
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")
operations = import_geoblender("core.provenance.operations")
provenance = import_geoblender("design.provenance")
res_params = import_geoblender("reserves.params")
sectors = import_geoblender("design.sectors")
stockpile_store = import_geoblender("design.stockpile_store")
store = import_geoblender("design.store")
versions_model = import_geoblender("core.versions.model")
versions_read = import_geoblender("core.versions.read")

DesignError = messages.DesignError
GRID = qfx.grid_of(qfx.COARSE_STEP_M)
"""La rejilla gruesa de la cantera (200 × 200 celdas de 2 m)."""
USER = "Samuel (IMGA)"
PROBE = "des.probe_surface"
"""El tipo de operación de prueba de V01 que escribe el levantamiento como superficie de la versión (solo desde esta prueba)."""
VERSION_SURFACE_NAME = "Levantamiento de V01"
VERSION_SURFACE = provenance.dataset_name(provenance.STOCKPILE_SURFACE_GRID, VERSION_SURFACE_NAME)
"""El levantamiento como dato de V01 (``des_stp_levantamiento_de_v01``): una superficie **de una versión**."""
FINE_DATASET = "gis_dtm_fina"
"""Una superficie del proyecto en una rejilla de 1 m (no es la del proyecto)."""
NAMES = ("Acopio 1", "Acopio 2", "Acopio 3", "Acopio 4", "Acopio 5")
BOXES = {"Acopio 1": (90.0, 90.0, 110.0, 110.0), "Acopio 2": (110.0, 90.0, 130.0, 110.0),
         "Acopio 3": (230.0, 90.0, 250.0, 110.0), "Acopio 4": (120.0, 210.0, 140.0, 230.0),
         "Acopio 5": (230.0, 210.0, 250.0, 230.0)}

# Los marcadores de lo que rechaza cada capa de defectos.
LAYER_OVERLAP, LAYER_DUPLICATED, LAYER_NEGATIVE, LAYER_HUGE = (
    "gis_fea_marcas_solapadas", "gis_fea_marcas_repetidas", "gis_fea_marca_margen_negativo", "gis_fea_marca_margen_enorme")
LAYER_BLANK, LAYER_BOW, LAYER_FLAT, LAYER_OUT, LAYER_EMPTY = (
    "gis_fea_marca_sin_nombre", "gis_fea_marca_corbata", "gis_fea_marca_plana", "gis_fea_marca_fuera",
    "gis_fea_marcas_vacia")
LAYER_BASE_OK, LAYER_BASE_MISSING, LAYER_BASE_FINE, LAYER_BASE_VERSION = (
    "gis_fea_marcas_base", "gis_fea_marca_base_falta", "gis_fea_marca_base_fina", "gis_fea_marca_base_de_version")


def drive[T](work: Generator[None, None, T]) -> T:
    """Lo que devuelve ``work`` (unidades de preparación) llevado hasta el final."""
    while True:
        try:
            next(work)
        except StopIteration as stop:
            return stop.value  # type: ignore[no-any-return]


def never(request: Any) -> Any:  # solo declara que se repite sola
    raise AssertionError("las pruebas de preparar no recalculan ni reproducen")


def hand_cells(box: tuple[float, float, float, float], step: float = 2.0, size: int = 200) -> np.ndarray:
    """Las celdas de una rejilla de ``size`` × ``size`` de ``step`` m (fila 0 al norte) cuyo centro está dentro de la caja
    local ``box``, a mano: un bucle sobre los centros, no el código; como índices planos ordenados."""
    left, bottom, right, top = box
    columns = [j for j in range(size) if left < (j + 0.5) * step < right]
    rows = [i for i in range(size) if bottom < size * step - (i + 0.5) * step < top]
    return np.array(sorted(i * size + j for i in rows for j in columns), dtype=np.int64)


def layer_of(name: str, rings: list[Any], names: list[str], **fields: tuple[Any, ...]) -> Any:
    """Una capa de marcas de polígonos de un solo anillo cada una, con ``fields`` (campo → valor por marca)."""
    return sdata.FieldsLayer(name, "polygon", tuple(((ring,),) for ring in rings), tuple(names), fields)


def defect_layers() -> tuple[Any, ...]:
    """Las capas de marcas con **un** defecto cada una (la preparación lee todas las marcas de la capa y se para en el
    primero): dos marcas solapadas, un nombre repetido, un margen negativo y otro enorme, una marca sin nombre, un
    polígono que se corta a sí mismo, otro sin área, uno fuera de la rejilla, una capa vacía y las de las bases."""
    box = cfx.rectangle
    bow = cfx.absolute([(10.0, 10.0), (30.0, 30.0), (30.0, 10.0), (10.0, 30.0), (10.0, 10.0)])
    flat = cfx.absolute([(10.0, 10.0), (20.0, 10.0), (30.0, 10.0), (10.0, 10.0)])
    mark = (230.0, 210.0, 250.0, 230.0)
    return (
        layer_of(LAYER_OVERLAP, [box(*BOXES["Acopio 1"]), box(100.0, 90.0, 120.0, 110.0)], ["A", "B"]),
        layer_of(LAYER_DUPLICATED, [box(20.0, 20.0, 40.0, 40.0), box(60.0, 20.0, 80.0, 40.0)],
                 ["Repetida", "Repetida"]),
        layer_of(LAYER_NEGATIVE, [box(*mark)], ["Mala"], margen=(-3.0,)),
        layer_of(LAYER_HUGE, [box(*mark)], ["Enorme"], margen=(5000.0,)),
        layer_of(LAYER_BLANK, [box(20.0, 20.0, 40.0, 40.0), box(60.0, 20.0, 80.0, 40.0)], ["a", "b"],
                 etiqueta=("Uno", None)),
        layer_of(LAYER_BOW, [bow], ["Corbata"]),
        layer_of(LAYER_FLAT, [flat], ["Plana"]),
        layer_of(LAYER_OUT, [box(1000.0, 1000.0, 1020.0, 1020.0)], ["Fuera"]),
        layer_of(LAYER_EMPTY, [], []),
        layer_of(LAYER_BASE_OK, [box(*BOXES["Acopio 5"]), box(*BOXES["Acopio 4"])], ["Con base", "Sin base"],
                 base=(sdata.PREVIOUS_DATASET, None)),
        layer_of(LAYER_BASE_MISSING, [box(*mark)], ["Falta"], base=("no_existe",)),
        layer_of(LAYER_BASE_FINE, [box(*mark)], ["Fina"], base=(FINE_DATASET,)),
        layer_of(LAYER_BASE_VERSION, [box(*mark)], ["De versión"], base=(VERSION_SURFACE,)),
    )


def fields(layer: str = sdata.MARKS_LAYER, **changes: Any) -> Any:
    """Los campos de la capa de marcas de la cantera (``nombre``, ``margen`` y ``material``; sin la ``base``)."""
    base: dict[str, Any] = {"layer": layer, "name_field": "nombre", "margin_field": "margen",
                            "material_field": "material"}
    return model.StockpileFields(**{**base, **changes})


def request(name: str = "Acopios", *, layer: str = sdata.MARKS_LAYER, surface: str = sdata.SURVEY_DATASET,
            marks: dict[str, Any] | None = None, **changes: Any) -> Any:
    """Una detección de las marcas de la cantera sobre el levantamiento del proyecto, con los valores por defecto de D-3."""
    return model.StockpileRequest(name, fields(layer, **(marks or {})), surface, **changes)


class PrepareCase(sdata.StockpileProjectCase):
    """Una copia por clase de la cantera de los acopios con lo que declara ``des`` (las operaciones de la 016, las familias
    de sus parámetros y el umbral de la 011) registrado, el levantamiento como superficie de **V01** (escrito con el
    escritor de versión) y las máscaras de V01 cargadas."""

    STEP_M = qfx.COARSE_STEP_M
    masks_v1: ClassVar[Any]

    @classmethod
    def write_version_surface(cls) -> None:
        """Escribe el levantamiento como dato de V01 (:data:`VERSION_SURFACE`) con el escritor de versión: una superficie que
        es **de una versión** (D-15)."""
        raster = gis.Raster(cls.grid, sdata.survey(cls.grid), sdata.CRS, sdata.VERTICAL)
        begun = store._start(cls.project, PROBE, VERSION_SURFACE_NAME, cls.v1, None, {"name": VERSION_SURFACE_NAME}, (),
                             (), None)
        cls.clock.advance(minutes=1)
        with store.design_writer(cls.project, PROBE, VERSION_SURFACE_NAME,
                                 version=cls.v1.uid) as writer:
            drive(writer.grid_steps(provenance.STOCKPILE_SURFACE_GRID, raster))
            writer.commit(begun, message="Superficie de V01 de la prueba de preparar la detección")
        cls.clock.advance(minutes=1)

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        core_params.register_definitions(res_params.DEFINITIONS)
        cls.addClassCleanup(core_params.unregister_definitions, "res")
        core_params.register_families(design_params.SUPPORTED_FAMILIES)
        cls.addClassCleanup(core_params.unregister_families, "des")
        probe = provenance.OperationType(PROBE, "Surface of a version of the tests", (provenance.STOCKPILE_SURFACE_GRID,), ())
        cls.enterClassContext(mock.patch.object(provenance, "OPERATION_TYPES_BY_NAME", MappingProxyType(
            {**provenance.OPERATION_TYPES_BY_NAME, PROBE: probe})))
        cls.enterClassContext(registered(probe.definition(never)))
        cls.write_version_surface()
        cls.masks_v1 = access.load_masks(cls.project, cls.v1.uid)

    def state(self) -> dict[str, Any]:
        """Todo lo que podría escribir la preparación: el contador de cambios de la base (lo sube toda transacción que
        escribe) y, aparte, lo que se vería: operaciones, datos, parámetros y los ficheros de ``rasters/``."""
        return {
            "counter": change_counter(self.root),
            "operations": self.query("SELECT uid, status FROM gb_operation ORDER BY rowid"),
            "datasets": self.query("SELECT uid, status, content_sha256 FROM gb_dataset ORDER BY rowid"),
            "parameters": self.query("SELECT key, scope_uid, value FROM gb_parameter ORDER BY rowid"),
            "files": sorted(path.name for path in (self.root / "rasters").iterdir())}

    def prepare(self, asked: Any, *, version: Any = "default", **options: Any) -> Any:
        """:func:`prepare_detection` con V01 por defecto y sus máscaras."""
        which = self.v1.uid if version == "default" else version
        return stockpile_store.prepare_detection(self.project, asked, version=which,
                                                 masks=options.pop("masks", self.masks_v1), **options)

    def refused(self, asked: Any, expected: str, **options: Any) -> Any:
        """``asked`` se rechaza con el código ``expected`` y **no escribe nada**; devuelve el error, cuyo texto no deja
        ningún marcador sin llenar en ninguno de los dos idiomas."""
        before = self.state()
        with self.assertRaises(DesignError) as caught:
            self.prepare(asked, **options)
        error = caught.exception
        self.assertEqual(error.code, expected)
        self.assertEqual(self.state(), before, "el rechazo ha escrito algo")
        for text in (error.text, error.text_in("en")):
            self.assertNotIn("{", text)
            self.assertNotIn("?", text)
        return error

    def names(self, error: Any, **expected: Any) -> None:
        """El rechazo nombra lo que se espera (en sus valores y en su texto)."""
        for key, value in expected.items():
            self.assertEqual(error.values[key], value, key)
            if not isinstance(value, float):  # los decimales salen con coma en el texto
                self.assertIn(str(value), error.text)


# ---------------------------------------------------------------------------------------------
# El camino bueno
# ---------------------------------------------------------------------------------------------


class PreparedDetectionTest(PrepareCase):
    """RF-016-02, RF-016-03, RF-015-08 (y D-15, D-17): lo que se lee, en la rejilla del proyecto y sin escribir."""

    def test_a_version_detection_is_prepared_without_writing(self) -> None:
        """RF-016-02, RF-016-03, RF-015-09: la capa de marcas, la superficie **de V01**, el código ``STK-001``, la rejilla y
        las máscaras de la versión dejan un ``StockpileJob`` con todo lo leído (la superficie bit a bit; las cinco marcas
        rasterizadas **a mano**, con su margen y su material; los umbrales de D-3 y el de la 011) y la ``OperationStart`` de
        ``des.stockpile_detect`` con sus ajustes, entradas (la capa, la superficie y las máscaras, con sus papeles) y
        parámetros; nada se escribe, y las dos marcas que se tocan por el borde (Acopio 1 y 2) no se rechazan."""
        asked = request(surface=VERSION_SURFACE)
        before = self.state()
        prepared = self.prepare(asked)
        self.assertEqual(self.state(), before)
        self.assertEqual((prepared.scope, prepared.code, prepared.op_type, prepared.existing),
                         (stockpile_store.VERSION, "STK-001", provenance.STOCKPILE_DETECT, False))
        self.assertEqual(prepared.version.uid, self.v1.uid)
        self.assertEqual((prepared.version_uid, prepared.surface, prepared.layer),
                         (self.v1.uid, VERSION_SURFACE, sdata.MARKS_LAYER))
        job = prepared.job
        self.assertEqual((job.name, job.code), ("Acopios", "STK-001"))
        self.assertTrue(job.grid.same_geometry(self.masks_v1.grid))
        self.assertTrue(np.array_equal(job.surface, sdata.survey(GRID), equal_nan=True))
        self.assertEqual([mark.key for mark in job.marks], list(NAMES))
        for mark in job.marks:
            with self.subTest(mark=mark.key):
                self.assertEqual(mark.cells.dtype, np.int64)
                self.assertEqual(mark.cells.tolist(), hand_cells(BOXES[mark.key]).tolist())
                self.assertEqual(mark.cells.size, 100)
        self.assertEqual([mark.margin_m for mark in job.marks], [None, None, 6.0, None, None])
        self.assertEqual([mark.material for mark in job.marks], ["mineral", "mineral", "estéril", "estéril", "mineral"])
        self.assertEqual([mark.base for mark in job.marks], [None] * 5)
        self.assertEqual(dict(prepared.fids), {name: index for index, name in enumerate(NAMES, start=1)})
        plane = job.params.plane
        self.assertEqual((plane.crown_inner_m, plane.crown_outer_m, plane.crown_slope_deg, plane.crown_flat_min_m2,
                          plane.max_residual_m, plane.fit_rounds, plane.tilt_max_deg, plane.support_quantile),
                         (1.0, 3.0, 12.0, 10.0, 1.0, 4, 4.0, 0.6))  # D-3
        self.assertEqual((job.params.margin_m, job.params.turns, job.params.threshold_m), (10.0, 6, 0.3))  # D-3, D-17
        self.assertIsNone(job.candidates)
        self.assertIsNone(job.perimeter)
        self.assertEqual(dict(job.bases), {})
        start = prepared.start
        self.assertEqual((start.op_type, start.name, start.version_code), (provenance.STOCKPILE_DETECT, "Acopios",
                                                                           self.v1.code))
        self.assertFalse(start.is_project)
        self.assertEqual(dict(start.settings), provenance.stockpile_settings(asked, "STK-001"))
        self.assertEqual(start.params, provenance.stockpile_params("STK-001", asked))
        self.assertEqual([(use.item, str(use.role)) for use in start.inputs[:2]],
                         [(sdata.MARKS_LAYER, "marks_layer"), (VERSION_SURFACE, "surface")])
        self.assertEqual(start.inputs[2:], self.masks_v1.uses())
        self.assertIn(design_params.ANTHROPIC_PRESENCE, start.params)

    def test_the_prepared_detection_by_units_is_the_same(self) -> None:
        """RF-016-02 (plan 016 §5.3.1): ``prepare_detection_units`` cede el hilo en varias unidades y da la misma
        preparación que ``prepare_detection``; sin ``masks`` carga las de V01 (están al día)."""
        asked = request(surface=VERSION_SURFACE)
        work = stockpile_store.prepare_detection_units(self.project, asked, version=self.v1.uid)
        units = 0
        while True:
            try:
                next(work)
                units += 1
            except StopIteration as stop:
                by_units = stop.value
                break
        self.assertGreaterEqual(units, 4)
        whole = self.prepare(asked)
        for name in ("code", "scope", "surface", "layer", "fids", "values"):
            self.assertEqual(getattr(by_units, name), getattr(whole, name), name)
        for name in ("op_type", "name", "version_uid", "settings", "inputs", "params", "seen"):
            self.assertEqual(getattr(by_units.start, name), getattr(whole.start, name), name)
        self.assertEqual(by_units.rows, whole.rows)
        self.assertTrue(all(np.array_equal(a.cells, b.cells) for a, b in zip(by_units.job.marks, whole.job.marks,
                                                                             strict=True)))

    def test_a_detection_on_a_project_surface_is_of_the_project(self) -> None:
        """RF-016-02, RF-009-05, D-15: sobre una superficie **del proyecto**, la detección es del proyecto —también sin
        versión activa—: el tipo ``des.stockpile_detect_project`` (de proyecto), sin versión ni máscaras, con el código
        ``STK-001`` del proyecto, y **ningún dato que consume es de una versión**; con una versión activa, la misma."""
        asked = request()
        before = self.state()
        alone = self.prepare(asked, version=None)
        with_version = self.prepare(asked)
        self.assertEqual(self.state(), before)
        for prepared in (alone, with_version):
            with self.subTest(version=prepared.version_uid):
                self.assertEqual((prepared.scope, prepared.code, prepared.op_type, prepared.version),
                                 (stockpile_store.PROJECT, "STK-001", provenance.STOCKPILE_DETECT_PROJECT, None))
                self.assertIsNone(prepared.version_uid)
                self.assertTrue(prepared.start.is_project)
                self.assertEqual(prepared.start.version_code, "")
                self.assertIsNone(prepared.start.masks)
                self.assertEqual([(use.item, str(use.role)) for use in prepared.start.inputs],
                                 [(sdata.MARKS_LAYER, "marks_layer"), (sdata.SURVEY_DATASET, "surface")])
                self.assertEqual(prepared.start.params, provenance.stockpile_params("STK-001", asked))
                self.assertTrue(np.array_equal(prepared.job.surface, sdata.survey(GRID), equal_nan=True))
        self.assertEqual(alone.rows, with_version.rows)
        for use in alone.start.inputs:  # RF-009-05: nada de lo que consume es de una versión
            with self.project.read() as conn:
                record = import_geoblender("core.datasets.registry").get(conn, use.item)
                owners = versions_read.dataset_versions(conn, [record.uid])
            self.assertEqual(owners[record.uid], "", use.item)

    def test_the_default_parameters_are_all_written_with_their_origin(self) -> None:
        """RF-016-02, RF-008-01 (trampa de la T04 de la 015): las 20 filas de la entidad —**todas**, también las de los
        valores por defecto— con la clave ``des.stockpile.stk_001.*`` y su procedencia: los de D-3 ADOPTADO «sin confirmar»
        de origen ``algorithm`` (la inclinación máxima y el cuantil, HIPÓTESIS), y lo que se pidió en el diálogo, de la persona.
        Las **decisiones** sobre los candidatos (T13, P-14) también: sin decidir nadie es el texto vacío válido, con el origen
        de su familia («vacío por defecto», de la persona que decide), para que la operación lo lea y decidir la deje obsoleta."""
        prepared = self.prepare(request(margin_m=12.5, turns=3))
        rows = {row.param: row for row in prepared.rows}
        self.assertEqual(len(rows), 20)
        self.assertEqual(set(rows), {"name", "layer", "surface", "candidates", "margin_m", "crown_inner_m",
                                     "crown_outer_m", "crown_slope_deg", "crown_flat_min_m2", "max_residual_m",
                                     "fit_rounds", "turns", "tilt_max_deg", "support_quantile", "open_diameter_m",
                                     "min_height_m", "min_area_m2", "max_area_m2", "decisions", "protect"})
        self.assertEqual((rows["decisions"].value, rows["decisions"].source_kind),
                         (stockpile_store.EMPTY_DECISIONS, "person"))
        self.assertIn("vacío por defecto", rows["decisions"].source)
        for row in rows.values():
            self.assertEqual(row.key, f"des.stockpile.stk_001.{row.param}")
        self.assertEqual((rows["name"].value, rows["layer"].value, rows["surface"].value, rows["candidates"].value),
                         ("Acopios", sdata.MARKS_LAYER, sdata.SURVEY_DATASET, False))
        self.assertEqual((rows["margin_m"].value, rows["turns"].value, rows["crown_outer_m"].value,
                          rows["open_diameter_m"].value, rows["protect"].value), (12.5, 3, 3.0, 31.0, False))
        for asked in ("name", "layer", "surface", "candidates", "margin_m", "turns"):
            self.assertEqual(rows[asked].source_kind, "person", asked)
            self.assertIn("Acopios", rows[asked].source)
        for default in ("crown_inner_m", "crown_slope_deg", "fit_rounds", "tilt_max_deg", "support_quantile",
                        "open_diameter_m", "max_area_m2", "protect"):
            self.assertEqual(rows[default].source_kind, "algorithm", default)
        self.assertEqual({entity_store._row_kind(rows[name]) for name in ("margin_m", "crown_inner_m", "max_area_m2")},
                         {"ADOPTADO"})
        self.assertEqual({entity_store._row_kind(rows[name]) for name in ("tilt_max_deg", "support_quantile")},
                         {"HIPÓTESIS"})
        self.assertEqual(prepared.values["margin_m"], 12.5)

    def test_the_candidates_get_the_perimeter_of_the_scope(self) -> None:
        """RF-016-08, RF-012-13, D-15: pidiendo los candidatos, la detección trae sus umbrales y el **perímetro de
        actuación**: en una detección de versión, el de las máscaras de V01 (el bit ``PERIMETER`` de su rejilla de clases) y,
        en una del proyecto, **el de la restricción del proyecto** (las celdas enteras dentro del perímetro o, sin él, del
        límite legal): en la cantera, el mismo; y la del proyecto consume la capa de restricciones de polígonos y lee la
        «activa» de las restricciones que forman el perímetro."""
        wanted = (self.masks_v1.classes & 8) != 0
        self.assertTrue(wanted.any() and not wanted.all())
        by_version = self.prepare(request(surface=VERSION_SURFACE, candidates=True))
        by_project = self.prepare(request(candidates=True), version=None)
        for prepared in (by_version, by_project):
            with self.subTest(scope=prepared.scope):
                self.assertTrue(np.array_equal(prepared.job.perimeter, wanted))
                found = prepared.job.candidates
                self.assertEqual((found.open_diameter_m, found.min_height_m, found.min_area_m2, found.max_area_m2),
                                 (31.0, 2.0, 150.0, 20000.0))
                self.assertIs(found.footprint, prepared.job.params)
                self.assertTrue(prepared.values["candidates"])
        self.assertIn(operations.Use("core_constraint_polygon", "constraints_polygon"), by_project.start.inputs)
        active = [key for key in by_project.start.params if key.startswith("core.constraint.")]
        self.assertTrue(active and all(key.endswith(".active") for key in active), active)
        self.assertEqual([key for key in by_version.start.params if key.startswith("core.constraint.")], [])
        self.assertNotIn(operations.Use("core_constraint_polygon", "constraints_polygon"), by_version.start.inputs)
        source = access.open_masks(self.project, self.v1.uid)  # sin celdas: el perímetro lee la rejilla de clases entera
        from_source = self.prepare(request(surface=VERSION_SURFACE, candidates=True), masks=source)
        self.assertTrue(np.array_equal(from_source.job.perimeter, wanted))
        self.assertEqual(from_source.start.inputs[2:], source.uses())
        plain = self.prepare(request(), version=None)  # sin candidatos, el perímetro no se lee ni se consume
        self.assertIsNone(plain.job.perimeter)
        self.assertNotIn(operations.Use("core_constraint_polygon", "constraints_polygon"), plain.start.inputs)

    def test_the_marks_are_the_cells_whose_centre_is_inside(self) -> None:
        """RF-016-02 (D-16 de la 013): una marca son las celdas cuyo **centro** queda dentro de su polígono, por la regla
        par-impar: con un hueco (84 celdas, a mano), con dos partes (50), recortada por el borde de la rejilla (50: solo
        las de centro dentro de ella) y las que no tienen ninguna (fuera de la rejilla o más pequeña que una celda) dan un
        array vacío; siempre ordenadas, sin repetir y como índices planos ``int64``."""
        box = cfx.rectangle
        found = stockpile_store.mark_cells
        found_hole = found([(box(90.0, 90.0, 110.0, 110.0), box(96.0, 96.0, 104.0, 104.0))], GRID)
        expected = set(hand_cells((90.0, 90.0, 110.0, 110.0)).tolist()) - set(
            hand_cells((96.0, 96.0, 104.0, 104.0)).tolist())
        self.assertEqual((found_hole.size, set(found_hole.tolist())), (84, expected))
        parts = [(box(90.0, 90.0, 100.0, 100.0),), (box(110.0, 110.0, 120.0, 120.0),)]
        self.assertEqual(found(parts, GRID).tolist(), sorted(
            hand_cells((90.0, 90.0, 100.0, 100.0)).tolist() + hand_cells((110.0, 110.0, 120.0, 120.0)).tolist()))
        west = found([(box(-10.0, 90.0, 10.0, 110.0),)], GRID)
        self.assertEqual(west.tolist(), hand_cells((0.0, 90.0, 10.0, 110.0)).tolist())
        self.assertEqual(west.size, 50)
        for nothing in ([(box(1000.0, 1000.0, 1020.0, 1020.0),)], [(box(11.2, 11.2, 11.7, 11.7),)], []):
            with self.subTest(parts=len(nothing)):
                empty = found(nothing, GRID)
                self.assertEqual((empty.size, empty.dtype), (0, np.int64))
        self.assertTrue(np.all(np.diff(west) > 0))

    def test_the_detection_does_not_ask_for_the_search_of_untouchables(self) -> None:
        """RF-015-07, spec §8 («la detección, que no mueve celdas, no la pide»): la preparación **no llama a**
        ``refuse_pending`` —ni la de ``design.sectors`` ni la que importan las entidades—, aunque sus marcas toquen un
        sector con la búsqueda pendiente."""
        with mock.patch.object(sectors, "refuse_pending", side_effect=AssertionError("no se llama")) as pending, \
                mock.patch.object(entity_store, "refuse_pending", side_effect=AssertionError("no se llama")) as held:
            prepared = self.prepare(request(surface=VERSION_SURFACE, candidates=True))
        pending.assert_not_called()
        held.assert_not_called()
        self.assertEqual(len(prepared.job.marks), 5)
        self.assertFalse(hasattr(stockpile_store, "refuse_pending"))

    def test_an_existing_code_is_kept_and_the_name_may_be_its_own(self) -> None:
        """RF-015-01, RF-016-10: con el ``code`` de una entidad que ya está en el ámbito (recalcularla), la preparación lo
        conserva, ``existing`` lo dice (``Crear`` no escribe otra vez sus parámetros) y la operación que sustituye
        (``supersedes``) puede quedarse con los nombres de sus datos."""
        prepared = self.prepare(request(), code="STK-007", supersedes=None)
        self.assertEqual((prepared.code, prepared.existing, prepared.job.code), ("STK-007", True, "STK-007"))
        self.assertTrue(all(row.key.startswith("des.stockpile.stk_007.") for row in prepared.rows))


# ---------------------------------------------------------------------------------------------
# Los rechazos (sin escribir nada)
# ---------------------------------------------------------------------------------------------


class MarkLayersTest(PrepareCase):
    """RF-016-02, RF-016-03, RF-016-04, RF-015-08, RF-015-09: las capas de marcas con un defecto (cada rechazo, sin escribir
    nada y nombrando la capa, la entidad, el campo y el valor) y la de las bases propias."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        for layer in defect_layers():
            sdata.write_layer(cls.project, cls.clock, layer)
        fine = qfx.grid_of(qfx.STEP_M)
        res_fixtures.write_grids(cls.project, [("fina", gis.Raster(fine, np.full(fine.shape, 100.0), sdata.CRS,
                                                                  sdata.VERTICAL))],
                                 message="Superficie en una rejilla de 1 m")
        cls.clock.advance(minutes=1)

    def test_a_mark_with_its_own_base_surface(self) -> None:
        """RF-016-03, D-20: la marca que nombra en su campo ``base`` una superficie del proyecto en su rejilla la lleva
        como ``mark.base`` y el trabajo, la superficie leída bit a bit (``job.bases``); la otra marca, sin base; la superficie
        de base es una **entrada** de la operación, con el papel de las superficies."""
        prepared = self.prepare(request(layer=LAYER_BASE_OK, marks={"base_field": "base", "margin_field": None,
                                                                    "material_field": None}),
                                version=None)
        self.assertEqual([(mark.key, mark.base) for mark in prepared.job.marks],
                         [("Con base", sdata.PREVIOUS_DATASET), ("Sin base", None)])
        self.assertEqual(list(prepared.job.bases), [sdata.PREVIOUS_DATASET])
        self.assertTrue(np.array_equal(prepared.job.bases[sdata.PREVIOUS_DATASET], sdata.previous_survey(GRID),
                                       equal_nan=True))
        self.assertIn(operations.Use(sdata.PREVIOUS_DATASET, "surface"), prepared.start.inputs)

    def test_marks_that_overlap_name_the_two(self) -> None:
        """RF-016-04 (decisión de la sesión principal, 18/11/2026): dos marcas se solapan si alguna celda tiene su centro
        en las dos; se rechaza **nombrando las dos**, el área común (a mano: 5 columnas × 10 filas × 4 m² = 200 m²) y el
        centro de las celdas comunes (x = 105 m, y = 100 m locales); las que solo se tocan por el borde (Acopio 1 y 2 de la
        cantera, que comparten el lado x = 110 m) no se rechazan."""
        error = self.refused(request(layer=LAYER_OVERLAP, marks={"margin_field": None, "material_field": None}),
                             "des.stockpile_marks_overlap")
        self.names(error, mark="A", other="B", area=200.0)
        self.assertEqual((error.values["x"], error.values["y"]), (sdata.BASE[0] + 105.0, sdata.BASE[1] + 100.0))
        self.assertIn("«A»", error.text)
        self.assertIn("«B»", error.text)
        touching = self.prepare(request(), version=None)
        self.assertEqual({mark.key for mark in touching.job.marks} >= {"Acopio 1", "Acopio 2"}, True)

    def test_a_missing_field_of_the_layer_is_refused(self) -> None:
        """RF-015-08: un campo de la capa que no está, o que no es del tipo que se lee (el nombre, el material y la base
        son de texto; el margen, un número), se rechaza con la capa, el campo de la petición, el valor y los campos que
        sirven."""
        for param, change in (("margin_field", {"margin_field": "no_existe"}), ("name_field", {"name_field": "margen"}),
                              ("margin_field", {"margin_field": "nombre"}),
                              ("material_field", {"material_field": "margen"}),
                              ("base_field", {"base_field": "margen"})):
            with self.subTest(param=param, change=change):
                error = self.refused(request(marks=change), "des.stockpile_layer_field")
                self.names(error, field=param, value=next(iter(change.values())), layer=sdata.MARKS_LAYER)
        listed = self.refused(request(marks={"margin_field": "no_existe"}), "des.stockpile_layer_field").values["fields"]
        self.assertEqual(listed, "margen")

    def test_a_layer_that_is_not_of_polygons_is_refused(self) -> None:
        """RF-016-02: la capa de puntos de los espesores no es de marcas (``des.layer_not_polygons``)."""
        error = self.refused(request(layer=sdata.THICKNESS_POINTS_LAYER, marks={"margin_field": None,
                                                                                "material_field": None,
                                                                                "name_field": "nombre"}),
                             "des.layer_not_polygons")
        self.names(error, layer=sdata.THICKNESS_POINTS_LAYER, value="puntos")

    def test_a_mark_without_a_name_or_with_a_repeated_one_is_refused(self) -> None:
        """RF-016-02, RF-015-08: la clave de la marca es su nombre (única): sin él, ``des.entity_field_value`` con su
        ``fid``; dos marcas con el mismo, ``des.stockpile_mark_repeated`` con el nombre y los dos ``fid``; sin campo de
        nombre, la clave es el ``fid``."""
        error = self.refused(request(layer=LAYER_BLANK, marks={"name_field": "etiqueta", "margin_field": None,
                                                               "material_field": None}),
                             "des.entity_field_value")
        self.names(error, layer=LAYER_BLANK, entity="fid 2", field="etiqueta")
        error = self.refused(request(layer=LAYER_DUPLICATED, marks={"margin_field": None, "material_field": None}),
                             "des.stockpile_mark_repeated")
        self.names(error, layer=LAYER_DUPLICATED, value="Repetida", fids="1, 2")
        by_fid = self.prepare(request(layer=LAYER_DUPLICATED, marks={"name_field": None, "margin_field": None,
                                                                    "material_field": None}), version=None)
        self.assertEqual([mark.key for mark in by_fid.job.marks], ["1", "2"])

    def test_a_negative_or_out_of_range_margin_is_refused(self) -> None:
        """RF-015-08: un margen negativo (−3 m) o fuera del rango de ``margin_m`` (5.000 m) se rechaza con la capa, la
        marca, el campo de la capa, el valor y el rango."""
        for layer, value in ((LAYER_NEGATIVE, -3.0), (LAYER_HUGE, 5000.0)):
            with self.subTest(layer=layer):
                error = self.refused(request(layer=layer, marks={"material_field": None}), "des.entity_param_range")
                self.names(error, layer=layer, field="margen", value=value)
                self.assertIn(error.values["entity"], ("Mala", "Enorme"))
                self.assertIn("[0; 1", error.text)  # el rango de margin_m: de 0 a 1 000 m

    def test_an_invalid_polygon_is_refused(self) -> None:
        """RF-016-04: un polígono que se corta a sí mismo, otro sin área y uno que no tiene ninguna celda en la rejilla
        (fuera de ella) se rechazan con la capa, la marca y el problema (``self_intersecting``, ``no_area``)."""
        plain = {"margin_field": None, "material_field": None}
        error = self.refused(request(layer=LAYER_BOW, marks=plain), "des.stockpile_mark_geometry")
        self.names(error, layer=LAYER_BOW, entity="Corbata", value="self_intersecting")
        error = self.refused(request(layer=LAYER_FLAT, marks=plain), "des.stockpile_mark_geometry")
        self.names(error, layer=LAYER_FLAT, entity="Plana", value="no_area")
        error = self.refused(request(layer=LAYER_OUT, marks=plain), "des.stockpile_mark_no_cells")
        self.names(error, layer=LAYER_OUT, entity="Fuera")

    def test_a_layer_without_marks_needs_the_candidates(self) -> None:
        """RF-016-02, RF-016-08: una capa sin ninguna marca no tiene nada que detectar si no se piden los candidatos
        (``des.stockpile_no_marks``); con ellos, la preparación sigue con **ninguna marca** y los candidatos."""
        plain = {"margin_field": None, "material_field": None, "name_field": None}
        error = self.refused(request(layer=LAYER_EMPTY, marks=plain), "des.stockpile_no_marks")
        self.names(error, layer=LAYER_EMPTY)
        prepared = self.prepare(request(layer=LAYER_EMPTY, marks=plain, candidates=True), version=None)
        self.assertEqual(prepared.job.marks, ())
        self.assertIsNotNone(prepared.job.candidates)

    def test_the_parameters_are_checked_before_recording_anything(self) -> None:
        """RF-015-08: un parámetro fuera de su rango (el margen de la detección, las vueltas), sin valor (la superficie en
        blanco; el resguardo si protege) o con las áreas de los candidatos al revés se rechaza con la capa, la entidad, la
        clave del campo y el valor, antes de leer la superficie."""
        key = "des.stockpile.stk_001."
        error = self.refused(request(margin_m=-1.0), "des.entity_param_range")
        self.names(error, field=f"{key}margin_m", value=-1.0, entity="Acopios", layer=sdata.MARKS_LAYER)
        error = self.refused(request(turns=0), "des.entity_param_range")
        self.names(error, field=f"{key}turns", value=0)
        error = self.refused(request(protect=True), "des.entity_param_missing")
        self.names(error, field=f"{key}guard_m", entity="Acopios")
        error = self.refused(request(surface=""), "des.entity_param_missing")
        self.names(error, field=f"{key}surface")
        error = self.refused(request(candidates=True, min_area_m2=500.0, max_area_m2=100.0), "des.entity_param_range")
        self.names(error, field=f"{key}min_area_m2", value=500.0)
        self.assertIn("100", error.values["range"])
        guarded = self.prepare(request(protect=True, guard_m=4.0), version=None)
        self.assertEqual((guarded.values["protect"], guarded.values["guard_m"]), (True, 4.0))

    def test_the_surface_is_checked(self) -> None:
        """RF-016-02, RF-009-21, RF-011-02, RF-011-03: una superficie que no existe es ``gis.dataset_unknown``; la de V01
        sin versión activa pide la versión (``core.version_required``) y con otra versión, ``des.surface_other_version``; una
        versión que no existe, ``core.version_unknown``; y una superficie en otra rejilla se compara con la del proyecto
        antes de leer una celda (``des.surface_mismatch``); ninguna escribe nada."""
        before = self.state()
        with self.assertRaises(Exception) as caught:
            self.prepare(request(surface="gis_dtm_no_existe"))
        self.assertEqual(caught.exception.code, "gis.dataset_unknown")
        with self.assertRaises(versions_model.VersionError) as caught:
            self.prepare(request(surface=VERSION_SURFACE), version=None)
        self.assertEqual(caught.exception.code, "core.version_required")
        with self.assertRaises(versions_model.VersionError) as caught:
            self.prepare(request(), version="V99")
        self.assertEqual(caught.exception.code, "core.version_unknown")
        self.assertEqual(self.state(), before)
        error = self.refused(request(surface=FINE_DATASET), "des.surface_mismatch")
        self.names(error, surface=FINE_DATASET)
        error = self.refused(request(surface=VERSION_SURFACE), "des.surface_other_version", version=self.v2.uid)
        self.names(error, surface=VERSION_SURFACE)

    def test_a_base_surface_is_refused_if_it_is_missing_or_in_another_grid(self) -> None:
        """RF-016-03, RF-011-02, RF-009-05: la ``base`` de una marca que no existe (``gis.dataset_unknown``), que está en
        otra rejilla (``des.surface_mismatch``, antes de leer una celda) o que es de una versión
        (``des.surface_other_version``: una detección del proyecto no consume un dato de versión) se rechaza; la marca de la
        cantera que nombra ``levantamiento_previo`` (la etiqueta, no el nombre del dato) tampoco existe."""
        only_base = {"margin_field": None, "material_field": None, "base_field": "base"}
        before = self.state()
        for layer, code in ((LAYER_BASE_MISSING, "gis.dataset_unknown"), (sdata.MARKS_LAYER, "gis.dataset_unknown")):
            with self.subTest(layer=layer):
                with self.assertRaises(Exception) as caught:
                    self.prepare(request(layer=layer, marks=only_base), version=None)
                self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.state(), before)
        error = self.refused(request(layer=LAYER_BASE_FINE, marks=only_base), "des.surface_mismatch", version=None)
        self.names(error, surface=FINE_DATASET)
        error = self.refused(request(layer=LAYER_BASE_VERSION, marks=only_base), "des.surface_other_version", version=None)
        self.names(error, surface=VERSION_SURFACE)


class NotEditableTest(PrepareCase):
    """RF-009-21: una detección de una versión no se prepara si la versión no se edita."""

    def test_a_closed_version_does_not_prepare_a_detection_on_its_surface(self) -> None:
        """RF-009-21: en una superficie de V01, con V01 SUPERADA (``core.version_not_editable``), ni por la preparación
        entera ni por unidades, sin escribir nada; una superficie del proyecto se sigue admitiendo (la detección es del
        proyecto: no necesita la versión)."""
        with self.project.write_transaction() as conn:
            conn.execute("UPDATE gb_version SET status = 'VIGENTE' WHERE uid = ?", (self.v1.uid,))
            conn.execute("UPDATE gb_version SET status = 'SUPERADO', reason_closed = ? WHERE uid = ?",
                         ("Prueba de la 016", self.v1.uid))
        closed = self.state()
        with self.assertRaises(versions_model.VersionError) as caught:
            self.prepare(request(surface=VERSION_SURFACE))
        self.assertEqual(caught.exception.code, "core.version_not_editable")
        with self.assertRaises(versions_model.VersionError) as caught:
            drive(stockpile_store.prepare_detection_units(self.project, request(surface=VERSION_SURFACE),
                                                          version=self.v1.uid))
        self.assertEqual(caught.exception.code, "core.version_not_editable")
        self.assertEqual(self.state(), closed)
        prepared = self.prepare(request(), version=None)
        self.assertEqual(prepared.scope, stockpile_store.PROJECT)


# ---------------------------------------------------------------------------------------------
# Los nombres y los códigos
# ---------------------------------------------------------------------------------------------


class NamesTest(PrepareCase):
    """RF-015-01, RF-016-02 (D-15, H-3): el código es correlativo **por ámbito** y el nombre es único en él."""

    def test_codes_are_per_scope_and_names_are_unique_in_each(self) -> None:
        """Una detección que ya está en el proyecto (sus parámetros, escritos como los escribirá «Crear») deja la siguiente
        en ``STK-002`` del proyecto y no cambia la de V01 (``STK-001``); el mismo nombre en el proyecto es
        ``des.stockpile_name_repeated_project`` y en la versión, ``des.entity_name_repeated`` (también el que da el mismo
        nombre de dato), cada uno nombrando la entidad que lo tiene."""
        first = self.prepare(request("Patio"), version=None)
        self.assertEqual(first.code, "STK-001")
        entity_store.set_entity_params(self.project, first.rows, version=None, decided_by=USER)
        again = self.prepare(request("Otro patio"), version=None)
        self.assertEqual(again.code, "STK-002")
        self.assertEqual(self.prepare(request("Patio de V01", surface=VERSION_SURFACE)).code, "STK-001")
        for name in ("Patio", "patio", "PATIO "):
            with self.subTest(name=name):
                error = self.refused(request(name), "des.stockpile_name_repeated_project", version=None)
                self.names(error, other="Patio")
        entity_store.set_entity_params(self.project, self.prepare(request("Patio de V01", surface=VERSION_SURFACE)).rows,
                                       version=self.v1.uid, decided_by=USER)
        self.assertEqual(self.prepare(request("Segundo", surface=VERSION_SURFACE)).code, "STK-002")
        error = self.refused(request("patio de v01", surface=VERSION_SURFACE), "des.entity_name_repeated")
        self.names(error, other="Patio de V01", version=self.v1.code)
        self.assertEqual(self.prepare(request("Tercero"), version=None).code, "STK-002")  # el del proyecto, aparte



class ThresholdTest(PrepareCase):
    """RF-016-02, D-17: el umbral de la huella es el de la 011 (``res.anthropic_presence_m``, un parámetro **del proyecto**),
    **leído por su clave**: el del proyecto o, sin él, el de su definición (0,30 m); lo mismo en las dos detecciones, y la
    operación lo lee (``stockpile_params``: cambiarlo la deja obsoleta con su causa)."""

    def write_threshold(self, value: float, *, version: str | None) -> None:
        """Escribe el umbral de la 011 como parámetro del proyecto o de la versión ``version``."""
        with self.project.write_transaction() as conn:
            core_params.ParameterStore(self.project).create(
                conn, design_params.ANTHROPIC_PRESENCE, value, kind="ADOPTADO", source="Prueba de la T11",
                source_kind="person", decided_by=USER, reason="Prueba de la T11", version=version)

    def test_the_threshold_is_read_by_its_key_in_each_scope(self) -> None:
        """Sin fila, el de la definición (0,30 m); con uno del proyecto (0,5 m), el de las dos detecciones; V01 no admite el suyo."""
        by_version, by_project = request(surface=VERSION_SURFACE), request()
        self.assertEqual(self.prepare(by_version).job.params.threshold_m, 0.3)
        self.write_threshold(0.5, version=None)
        self.assertEqual(self.prepare(by_version).job.params.threshold_m, 0.5)
        self.assertEqual(self.prepare(by_project, version=None).job.params.threshold_m, 0.5)
        self.assertEqual(self.prepare(by_project).job.params.threshold_m, 0.5)  # con V01 activa: sigue siendo del proyecto
        with self.assertRaises(core_params.ParamError):  # es del proyecto: ninguna versión tiene el suyo (011, D-7)
            self.write_threshold(0.4, version=self.v1.uid)


if __name__ == "__main__":
    unittest.main()
